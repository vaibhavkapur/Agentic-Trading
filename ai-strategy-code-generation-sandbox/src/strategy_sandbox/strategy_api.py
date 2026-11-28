"""Restricted, strictly causal Strategy API exposed to untrusted strategy code.

Generated strategy code must define:
    def on_bar(ctx) -> list[dict]:
        ...

The StrategyContext provides read-only views of current and historical bars
strictly up to ctx.step (no future bars are ever present in memory), read-only
portfolio state, read-only parameters, a bounded mutable state dict, and a
deterministic seeded PRNG.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class BarView:
    """Immutable market bar view exposed to strategy code (notes stripped)."""

    timestamp: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class PositionView:
    """Immutable position snapshot exposed to strategy code."""

    symbol: str
    quantity: float
    avg_cost: float
    market_value: float


class DeterministicRNG:
    """Restricted deterministic PRNG wrapper seeded from StrategySpec.seed."""

    __slots__ = ("_rng",)

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def random(self) -> float:
        return self._rng.random()

    def uniform(self, a: float, b: float) -> float:
        return self._rng.uniform(a, b)

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        return self._rng.gauss(mu, sigma)

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)


class StrategyContext:
    """Strictly causal, read-only context passed into on_bar(ctx)."""

    __slots__ = (
        "_step",
        "_timestamp",
        "_current_bars",
        "_history_by_symbol",
        "_cash",
        "_equity",
        "_positions",
        "_params",
        "_state",
        "_rng",
    )

    def __init__(
        self,
        *,
        step: int,
        timestamp: str,
        current_bars: dict[str, BarView],
        history_by_symbol: dict[str, tuple[BarView, ...]],
        cash: float,
        equity: float,
        positions: dict[str, PositionView],
        params: dict[str, Any],
        state: dict[str, Any],
        rng: DeterministicRNG,
    ) -> None:
        self._step = step
        self._timestamp = timestamp
        self._current_bars = MappingProxyType(dict(current_bars))
        self._history_by_symbol = {sym: tuple(bars) for sym, bars in history_by_symbol.items()}
        self._cash = float(cash)
        self._equity = float(equity)
        self._positions = MappingProxyType(dict(positions))
        self._params = MappingProxyType(dict(params))
        self._state = state
        self._rng = rng

    @property
    def step(self) -> int:
        return self._step

    @property
    def timestamp(self) -> str:
        return self._timestamp

    @property
    def current_bars(self) -> Mapping[str, BarView]:
        return self._current_bars

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def positions(self) -> Mapping[str, PositionView]:
        return self._positions

    @property
    def params(self) -> Mapping[str, Any]:
        return self._params

    @property
    def state(self) -> dict[str, Any]:
        return self._state

    @property
    def rng(self) -> DeterministicRNG:
        return self._rng

    def history(self, symbol: str, lookback: int | None = None) -> tuple[BarView, ...]:
        """Return immutable tuple of historical bars up to and including the current step."""
        bars = self._history_by_symbol.get(symbol, ())
        if lookback is None:
            return bars
        if not isinstance(lookback, int) or lookback <= 0:
            raise ValueError("lookback must be a positive integer")
        return bars[-lookback:]

    def position_qty(self, symbol: str) -> float:
        """Convenience helper returning current share quantity for a symbol."""
        pos = self._positions.get(symbol)
        return pos.quantity if pos is not None else 0.0
