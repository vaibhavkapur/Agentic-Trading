"""Shared pytest fixtures for unit, integration, and scenario tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trading_platform.service import TradingPlatform

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_TIME = datetime(2026, 11, 27, 14, 30, 0, tzinfo=UTC)


class MutableClock:
    """Deterministic controllable UTC clock for TTL expiry and quote staleness tests."""

    def __init__(self, current: datetime = BASE_TIME) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> datetime:
        self.current = self.current + timedelta(seconds=seconds)
        return self.current


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock(BASE_TIME)


@pytest.fixture
def platform(clock: MutableClock) -> TradingPlatform:
    svc = TradingPlatform.from_project_root(PROJECT_ROOT, db_path=":memory:", clock=clock)
    yield svc
    svc.close()
