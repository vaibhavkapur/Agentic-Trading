"""Deterministic synthetic point-in-time market fixtures with SHA-256 manifests."""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from rarp import SCHEMA_VERSION
from rarp.domain.dsl import DataManifest
from rarp.domain.errors import LeakageError, RARPValidationError
from rarp.domain.types import parse_utc_iso, sha256_bytes


@dataclass(frozen=True)
class MarketBar:
    symbol: str
    event_time_utc: str
    available_time_utc: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    currency: str = "USD"


def generate_synthetic_fixture(
    output_dir: Path,
    dataset_name: str = "synthetic_multi_regime_equities_v1",
    symbols: Sequence[str] = ("SYN_EQ_A", "SYN_EQ_B", "SYN_EQ_C"),
    num_days: int = 360,
    seed: int = 42,
    start_date_utc: str = "2023-01-02T21:00:00Z",
) -> Tuple[Path, Path, DataManifest]:
    """Generate deterministic multi-regime synthetic daily bars with explicit UTC timestamps.

    Generates realistic trending, mean-reverting, and high-volatility regimes without
    promising alpha or using unlicensed market data.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{dataset_name}.csv"
    manifest_path = output_dir / f"{dataset_name}.manifest.json"

    rng = random.Random(seed)
    start_dt = parse_utc_iso(start_date_utc)

    # Generate business-day timestamps (Mon-Fri).
    timestamps: List[dt.datetime] = []
    cur = start_dt
    while len(timestamps) < num_days:
        if cur.weekday() < 5:
            timestamps.append(cur)
        cur += dt.timedelta(days=1)

    rows: List[Dict[str, str]] = []
    for sym_idx, symbol in enumerate(symbols):
        price = 100.0 + sym_idx * 25.0
        prev_ret = 0.0
        for day_idx, ts in enumerate(timestamps):
            # Regime schedule: alternating mild momentum, choppy mean-reversion, and volatility shift.
            phase = (day_idx // 60) % 3
            if phase == 0:
                drift = 0.0007 + 0.25 * prev_ret
                vol = 0.011 + 0.002 * sym_idx
            elif phase == 1:
                drift = 0.0002 - 0.18 * prev_ret
                vol = 0.013 + 0.001 * sym_idx
            else:
                drift = 0.0005 + 0.20 * prev_ret
                vol = 0.018 + 0.002 * sym_idx

            shock = rng.gauss(0.0, vol)
            ret = max(-0.15, min(0.15, drift + shock))
            open_p = round(price * (1.0 + rng.gauss(0.0, 0.002)), 6)
            close_p = round(max(1.0, price * math.exp(ret)), 6)
            high_p = round(max(open_p, close_p) * (1.0 + abs(rng.gauss(0.0, 0.004))), 6)
            low_p = round(min(open_p, close_p) * max(0.5, 1.0 - abs(rng.gauss(0.0, 0.004))), 6)
            volume = round(500_000.0 * (1.0 + 0.4 * abs(shock) / max(vol, 1e-6)) * (1.0 + 0.1 * sym_idx), 2)

            event_iso = ts.isoformat().replace("+00:00", "Z")
            # Available immediately at close (point-in-time causal: available_time_utc == event_time_utc).
            avail_iso = event_iso

            rows.append(
                {
                    "symbol": symbol,
                    "event_time_utc": event_iso,
                    "available_time_utc": avail_iso,
                    "open": f"{open_p:.6f}",
                    "high": f"{high_p:.6f}",
                    "low": f"{low_p:.6f}",
                    "close": f"{close_p:.6f}",
                    "volume": f"{volume:.2f}",
                    "currency": "USD",
                }
            )
            prev_ret = ret
            price = close_p

    # Sort deterministically by (event_time_utc, symbol).
    rows.sort(key=lambda r: (r["event_time_utc"], r["symbol"]))

    fieldnames = [
        "symbol",
        "event_time_utc",
        "available_time_utc",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "currency",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    content_hash = sha256_bytes(csv_path.read_bytes())
    manifest = DataManifest(
        manifest_id=f"manifest_{dataset_name}_seed{seed}",
        dataset_name=dataset_name,
        schema_version=SCHEMA_VERSION,
        source_type="synthetic_deterministic",
        entitlement="PERMITTED_INTERNAL_RESEARCH_SYNTHETIC",
        license_notes="Synthetic fixture generated deterministically for local prototype validation; not live market data.",
        symbols=tuple(symbols),
        row_count=len(rows),
        start_event_time_utc=rows[0]["event_time_utc"],
        end_event_time_utc=rows[-1]["event_time_utc"],
        content_sha256=content_hash,
        created_at_utc="2026-01-01T00:00:00Z",
        file_path=csv_path.name,
    )
    manifest.validate()
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return csv_path, manifest_path, manifest


def load_dataset_with_manifest(manifest_path: Path) -> Tuple[DataManifest, Dict[str, List[MarketBar]]]:
    """Load dataset CSV, verify SHA-256 against manifest, and enforce point-in-time invariants."""
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = DataManifest.from_dict(manifest_data)
    manifest.validate()

    csv_path = manifest_path.parent / manifest.file_path
    if not csv_path.exists():
        raise RARPValidationError(f"Dataset file missing: {csv_path}")

    actual_hash = sha256_bytes(csv_path.read_bytes())
    if actual_hash != manifest.content_sha256:
        raise LeakageError(
            "Dataset content SHA-256 does not match versioned DataManifest (possible post-hoc or future-data mutation)",
            {
                "manifest_id": manifest.manifest_id,
                "expected_sha256": manifest.content_sha256,
                "actual_sha256": actual_hash,
            },
        )

    bars_by_symbol: Dict[str, List[MarketBar]] = {}
    row_count = 0
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            bar = MarketBar(
                symbol=row["symbol"],
                event_time_utc=row["event_time_utc"],
                available_time_utc=row["available_time_utc"],
                open_price=float(row["open"]),
                high_price=float(row["high"]),
                low_price=float(row["low"]),
                close_price=float(row["close"]),
                volume=float(row["volume"]),
                currency=row.get("currency", "USD"),
            )
            bars_by_symbol.setdefault(bar.symbol, []).append(bar)
            row_count += 1

    if row_count != manifest.row_count:
        raise LeakageError(
            f"Row count mismatch against manifest: expected {manifest.row_count}, got {row_count}",
            {"manifest_id": manifest.manifest_id, "expected": manifest.row_count, "actual": row_count},
        )

    verify_point_in_time_integrity(bars_by_symbol)
    return manifest, bars_by_symbol


def verify_point_in_time_integrity(bars_by_symbol: Dict[str, List[MarketBar]]) -> None:
    """Enforce chronological monotonicity and strict point-in-time availability (no future-data leakage)."""
    if not bars_by_symbol:
        raise RARPValidationError("Dataset contains no bars")

    for symbol, bars in bars_by_symbol.items():
        prev_event: dt.datetime | None = None
        for idx, bar in enumerate(bars):
            event_dt = parse_utc_iso(bar.event_time_utc)
            avail_dt = parse_utc_iso(bar.available_time_utc)
            if avail_dt > event_dt:
                raise LeakageError(
                    f"Future-data availability violation for {symbol} at bar {idx}: "
                    f"available_time_utc ({bar.available_time_utc}) > event_time_utc ({bar.event_time_utc})",
                    {
                        "symbol": symbol,
                        "bar_index": idx,
                        "event_time_utc": bar.event_time_utc,
                        "available_time_utc": bar.available_time_utc,
                    },
                )
            if prev_event is not None and event_dt <= prev_event:
                raise LeakageError(
                    f"Non-monotonic timestamps for {symbol} at bar {idx}",
                    {
                        "symbol": symbol,
                        "bar_index": idx,
                        "prev_event_time_utc": prev_event.isoformat(),
                        "event_time_utc": bar.event_time_utc,
                    },
                )
            if bar.close_price <= 0 or bar.open_price <= 0:
                raise RARPValidationError(f"Non-positive price for {symbol} at bar {idx}")
            prev_event = event_dt
