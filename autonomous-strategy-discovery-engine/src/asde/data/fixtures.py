"""Deterministic synthetic market data fixtures and manifest-verified CSV loader."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Dict, List, Optional

from asde.errors import DataContractError, ManifestIntegrityError
from asde.types import DatasetManifest, DatasetSnapshot, MarketBar, format_utc, parse_utc


DEFAULT_SYMBOLS = ["SYN_TECH", "SYN_IND", "SYN_HLTH", "SYN_ENER"]


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _trading_days_utc(start_date: datetime, count: int) -> List[datetime]:
    days: List[datetime] = []
    cur = start_date
    while len(days) < count:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


def generate_synthetic_dataset(
    *,
    seed: int = 20260401,
    num_bars: int = 900,
    symbols: Optional[List[str]] = None,
    regime: str = "multi_regime",
    dataset_id: str = "synthetic_equities_daily_v1",
) -> DatasetSnapshot:
    """Generate a reproducible point-in-time synthetic daily OHLCV dataset.

    Args:
        seed: Deterministic PRNG seed.
        num_bars: Number of trading bars per symbol.
        symbols: Tradable symbol identifiers.
        regime: "multi_regime" (trending + mean-reverting + vol shifts) or "pure_noise" (zero-alpha GBM).
        dataset_id: Stable dataset identifier.
    """
    syms = list(symbols or DEFAULT_SYMBOLS)
    rng = random.Random(seed)
    start_dt = datetime(2020, 1, 2, 21, 0, 0, tzinfo=timezone.utc)
    dates = _trading_days_utc(start_dt, num_bars)
    timestamps = [format_utc(d) for d in dates]

    bars_by_symbol: Dict[str, List[MarketBar]] = {s: [] for s in syms}

    # Generate shared market factor for realistic cross-asset correlation
    mkt_shocks = [rng.gauss(0.0, 0.0085) for _ in range(num_bars)]

    for s_idx, sym in enumerate(syms):
        price = 100.0 + 20.0 * s_idx
        trend_state = 0.0
        for t, dt in enumerate(dates):
            if regime == "pure_noise":
                # Pure zero-drift random walk for multiple-testing inflation scenarios
                ret = rng.gauss(0.0, 0.012)
            else:
                # Multi-regime process with distinct persistent bull/bear/choppy regimes and cross-asset rotation
                phase = (t // 140 + s_idx) % 4
                if phase == 0:
                    drift = 0.0022
                    vol = 0.009
                    ar_coeff = 0.18
                elif phase == 1:
                    drift = -0.0018
                    vol = 0.011
                    ar_coeff = 0.15
                elif phase == 2:
                    drift = 0.0016
                    vol = 0.009
                    ar_coeff = 0.12
                else:
                    drift = -0.0004
                    vol = 0.013
                    ar_coeff = -0.08
                shock = 0.30 * mkt_shocks[t] + rng.gauss(0.0, vol)
                trend_state = ar_coeff * trend_state + shock
                ret = max(-0.12, min(0.12, drift + trend_state))

            open_px = price * math.exp(rng.gauss(0.0, 0.0015))
            close_px = max(1.0, price * math.exp(ret))
            spread_hi = abs(rng.gauss(0.0, 0.004)) + 0.001
            spread_lo = abs(rng.gauss(0.0, 0.004)) + 0.001
            high_px = max(open_px, close_px) * (1.0 + spread_hi)
            low_px = min(open_px, close_px) * max(0.5, 1.0 - spread_lo)
            vol_shares = round(500_000.0 * (1.0 + abs(ret) * 40.0) * (0.8 + 0.4 * rng.random()), 2)

            ev_utc = format_utc(dt)
            av_utc = format_utc(dt + timedelta(minutes=5))
            bar = MarketBar(
                symbol=sym,
                event_time_utc=ev_utc,
                available_time_utc=av_utc,
                open=round(open_px, 6),
                high=round(high_px, 6),
                low=round(low_px, 6),
                close=round(close_px, 6),
                volume=vol_shares,
                currency="USD",
            )
            bar.validate()
            bars_by_symbol[sym].append(bar)
            price = close_px

    manifest = DatasetManifest(
        dataset_id=dataset_id,
        schema_version="1.0.0",
        source_type="synthetic",
        entitlement="permitted_internal_synthetic_fixture",
        license_note="Generated synthetically for reproducible research and testing; no external market data license required.",
        currency="USD",
        frequency="1D",
        symbols=syms,
        start_time_utc=timestamps[0],
        end_time_utc=timestamps[-1],
        row_count=num_bars * len(syms),
        data_file="in_memory",
        data_sha256="in_memory",
        seed=seed,
    )
    return DatasetSnapshot(
        manifest=manifest,
        timestamps_utc=timestamps,
        symbols=syms,
        bars_by_symbol=bars_by_symbol,
    )


def write_dataset_fixture(
    dataset: DatasetSnapshot,
    out_dir: Path,
    *,
    csv_filename: str = "synthetic_equities_daily.csv",
    manifest_filename: str = "synthetic_equities_manifest.json",
) -> Path:
    """Persist a DatasetSnapshot to CSV and write a SHA-256 verified manifest JSON."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / csv_filename

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
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in range(dataset.num_bars):
            for sym in dataset.symbols:
                bar = dataset.bars_by_symbol[sym][t]
                writer.writerow(bar.to_dict())

    data_sha = compute_file_sha256(csv_path)
    manifest = DatasetManifest(
        dataset_id=dataset.manifest.dataset_id,
        schema_version=dataset.manifest.schema_version,
        source_type=dataset.manifest.source_type,
        entitlement=dataset.manifest.entitlement,
        license_note=dataset.manifest.license_note,
        currency=dataset.manifest.currency,
        frequency=dataset.manifest.frequency,
        symbols=list(dataset.symbols),
        start_time_utc=dataset.timestamps_utc[0],
        end_time_utc=dataset.timestamps_utc[-1],
        row_count=dataset.num_bars * len(dataset.symbols),
        data_file=csv_filename,
        data_sha256=data_sha,
        seed=dataset.manifest.seed,
    )
    manifest_path = out_dir / manifest_filename
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def load_dataset_from_manifest(manifest_path: Path) -> DatasetSnapshot:
    """Load and cryptographically verify a dataset from its manifest JSON."""
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        raise DataContractError(f"Dataset manifest not found: {manifest_path}")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = DatasetManifest(**raw)
    csv_path = manifest_path.parent / manifest.data_file
    if not csv_path.exists():
        raise DataContractError(f"Dataset CSV file not found: {csv_path}")

    actual_sha = compute_file_sha256(csv_path)
    if actual_sha != manifest.data_sha256:
        raise ManifestIntegrityError(
            "Dataset SHA-256 checksum mismatch; fixture may be corrupted or tampered.",
            details={
                "manifest_path": str(manifest_path),
                "expected_sha256": manifest.data_sha256,
                "actual_sha256": actual_sha,
            },
        )

    bars_by_symbol: Dict[str, List[MarketBar]] = {s: [] for s in manifest.symbols}
    row_count = 0
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row["symbol"]
            if sym not in bars_by_symbol:
                raise DataContractError(f"Unexpected symbol {sym!r} in dataset CSV.")
            bar = MarketBar(
                symbol=sym,
                event_time_utc=row["event_time_utc"],
                available_time_utc=row["available_time_utc"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                currency=row.get("currency", manifest.currency),
            )
            bar.validate()
            bars_by_symbol[sym].append(bar)
            row_count += 1

    if row_count != manifest.row_count:
        raise ManifestIntegrityError(
            f"Row count mismatch: manifest expects {manifest.row_count}, loaded {row_count}."
        )

    first_sym = manifest.symbols[0]
    timestamps = [b.event_time_utc for b in bars_by_symbol[first_sym]]
    # Verify strict chronological monotonicity and cross-symbol alignment
    parsed = [parse_utc(ts) for ts in timestamps]
    for i in range(1, len(parsed)):
        if parsed[i] <= parsed[i - 1]:
            raise DataContractError(
                f"Non-monotonic timestamps at bar {i}: {timestamps[i - 1]} -> {timestamps[i]}"
            )
    for sym in manifest.symbols[1:]:
        sym_ts = [b.event_time_utc for b in bars_by_symbol[sym]]
        if sym_ts != timestamps:
            raise DataContractError(f"Timestamp misalignment between {first_sym} and {sym}.")

    return DatasetSnapshot(
        manifest=manifest,
        timestamps_utc=timestamps,
        symbols=list(manifest.symbols),
        bars_by_symbol=bars_by_symbol,
    )
