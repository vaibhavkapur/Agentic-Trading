"""Version-one synthetic bar contract and fixture boundary."""
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


class ContractError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class Bar:
    opened: datetime
    closed: datetime
    available: datetime
    open_usd: float
    close_usd: float
    auction_shares: float


def validate(bars):
    if len(bars) < 2:
        raise ContractError("short_series", "At least two sessions are required")
    previous = None
    for bar in bars:
        if any(t.utcoffset() != timedelta(0) for t in (bar.opened, bar.closed, bar.available)):
            raise ContractError("timezone", "Session times must be UTC")
        if not (bar.opened < bar.closed == bar.available) or (previous and previous >= bar.opened):
            raise ContractError("causality", "Sessions must be ordered and published at decision close")
        if not all(math.isfinite(x) and x > 0 for x in (bar.open_usd, bar.close_usd)):
            raise ContractError("price", "Prices must be positive and finite")
        if not math.isfinite(bar.auction_shares) or bar.auction_shares < 0:
            raise ContractError("liquidity", "Auction shares must be finite and nonnegative")
        previous = bar.closed
    return tuple(bars)


def load_fixture(directory):
    path = directory / "sessions.csv"
    manifest = json.loads((directory / "manifest.json").read_text())
    if (manifest.get("schema"), manifest.get("asset"), manifest.get("currency"),
        manifest.get("provenance")) != ("synthetic-sessions/v1", "SIM-USD", "USD", "generated"):
        raise ContractError("schema", "Unsupported market input")
    if digest(path) != manifest["sha256"]:
        raise ContractError("digest", "Session file does not match its manifest")
    with path.open(newline="") as stream:
        bars = []
        for row in csv.DictReader(stream):
            times = [datetime.fromisoformat(row[key].replace("Z", "+00:00"))
                     for key in ("opened", "closed", "available")]
            bars.append(Bar(*times, *[float(row[key]) for key in
                                      ("open_usd", "close_usd", "auction_shares")]))
    if len(bars) != manifest["sessions"]:
        raise ContractError("count", "Unexpected session count")
    return validate(bars)
