from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_engine.market import Bar

ROOT = Path(__file__).resolve().parents[1]


def series(prices):
    bars = []
    for index, (opening, closing, liquidity) in enumerate(prices):
        opened = datetime(2023, 1, 2, 14, 30, tzinfo=timezone.utc) + timedelta(days=index)
        closed = opened + timedelta(hours=6, minutes=30)
        bars.append(Bar(opened, closed, closed, opening, closing, liquidity))
    return tuple(bars)


def flat(count):
    return series([(100, 100, 100000)] * count)
