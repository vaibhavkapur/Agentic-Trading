"""Deterministic point-in-time signal compiler for the constrained DSL."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, List

from asde.dsl.catalog import validate_strategy_spec
from asde.dsl.schema import StrategyCatalog, StrategySpec
from asde.errors import LookAheadError
from asde.types import DatasetSnapshot, parse_utc


@dataclass
class CompiledSignals:
    """Target portfolio weights indexed by bar index t (applied at bar t execution).

    Invariant:
        target_weights[t] is strictly computed from market bars whose
        available_time_utc <= event_time_utc[t - signal_lag_bars] (i.e. strictly prior bars).
    """

    strategy_id: str
    symbols: List[str]
    target_weights: List[Dict[str, float]]  # length == dataset.num_bars
    signal_lag_bars: int


class SignalCompiler:
    """Compiles validated StrategySpec definitions into point-in-time target weights."""

    def __init__(self, catalog: StrategyCatalog) -> None:
        self.catalog = catalog

    def compile(
        self,
        spec: StrategySpec,
        dataset: DatasetSnapshot,
        *,
        injected_lookahead_bars: int = 0,
    ) -> CompiledSignals:
        """Compile target weights with strict causal / point-in-time enforcement.

        Args:
            spec: Validated declarative strategy specification.
            dataset: Verified market snapshot.
            injected_lookahead_bars: Fault-injection hook (>0 triggers LookAheadError).
        """
        validate_strategy_spec(spec, self.catalog)

        lag = int(spec.parameters.get("signal_lag_bars", 1))
        if injected_lookahead_bars > 0 or lag < 1:
            raise LookAheadError(
                "Look-ahead bias detected during signal compilation.",
                details={
                    "strategy_id": spec.strategy_id,
                    "signal_lag_bars": lag,
                    "injected_lookahead_bars": injected_lookahead_bars,
                },
            )

        self._verify_point_in_time_availability(dataset)

        n = dataset.num_bars
        symbols = list(dataset.symbols)
        closes = {s: [b.close for b in dataset.bars_by_symbol[s]] for s in symbols}
        highs = {s: [b.high for b in dataset.bars_by_symbol[s]] for s in symbols}
        lows = {s: [b.low for b in dataset.bars_by_symbol[s]] for s in symbols}

        raw_weights: List[Dict[str, float]] = [{s: 0.0 for s in symbols} for _ in range(n)]

        if spec.family == "baseline_cash":
            pass
        elif spec.family == "baseline_buy_and_hold":
            w = 1.0 / len(symbols)
            for t in range(lag, n):
                raw_weights[t] = {s: w for s in symbols}
        elif spec.family == "baseline_risk_parity_equal_weight":
            self._compile_risk_parity(raw_weights, closes, symbols, lag, vol_window=20, rebal_every=20)
        elif spec.family == "trend_ma_crossover":
            self._compile_trend_ma(raw_weights, closes, symbols, spec, lag)
        elif spec.family == "mean_reversion_zscore":
            self._compile_mean_reversion(raw_weights, closes, symbols, spec, lag)
        elif spec.family == "volatility_breakout":
            self._compile_vol_breakout(raw_weights, closes, highs, lows, symbols, spec, lag)
        elif spec.family == "dual_momentum":
            self._compile_dual_momentum(raw_weights, closes, symbols, spec, lag)

        capped = [
            self._normalize_weights(w, spec.max_single_asset_weight, spec.max_gross_leverage)
            for w in raw_weights
        ]
        return CompiledSignals(
            strategy_id=spec.strategy_id,
            symbols=symbols,
            target_weights=capped,
            signal_lag_bars=lag,
        )

    @staticmethod
    def _verify_point_in_time_availability(dataset: DatasetSnapshot) -> None:
        """Reject any bar whose available_time_utc leaks ahead of the next execution bar."""
        n = dataset.num_bars
        ts_dt = [parse_utc(ts) for ts in dataset.timestamps_utc]
        for sym, bars in dataset.bars_by_symbol.items():
            if len(bars) != n:
                raise LookAheadError(
                    f"Misaligned bar series length for {sym}: {len(bars)} vs {n}.",
                    details={"symbol": sym},
                )
            for t in range(n):
                ev = parse_utc(bars[t].event_time_utc)
                av = parse_utc(bars[t].available_time_utc)
                if ev != ts_dt[t]:
                    raise LookAheadError(
                        f"Timestamp alignment violation for {sym} at index {t}.",
                        details={"symbol": sym, "bar_time": bars[t].event_time_utc, "expected": dataset.timestamps_utc[t]},
                    )
                if av < ev:
                    raise LookAheadError(
                        f"Point-in-time violation: bar {t} for {sym} available before event_time.",
                        details={"symbol": sym, "event_time_utc": bars[t].event_time_utc, "available_time_utc": bars[t].available_time_utc},
                    )
                if t + 1 < n and av > ts_dt[t + 1]:
                    raise LookAheadError(
                        f"Point-in-time availability violation: bar {t} for {sym} is not yet available at next bar {t + 1}.",
                        details={
                            "symbol": sym,
                            "bar_index": t,
                            "available_time_utc": bars[t].available_time_utc,
                            "next_bar_event_utc": dataset.timestamps_utc[t + 1],
                        },
                    )

    @staticmethod
    def _trailing_vol(series: List[float], idx: int, window: int) -> float:
        if idx < window:
            return 0.0
        rets = []
        for i in range(idx - window + 1, idx + 1):
            prev = series[i - 1]
            if prev > 0.0:
                rets.append(series[i] / prev - 1.0)
        if len(rets) < 2:
            return 0.0
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        return math.sqrt(max(var, 0.0)) * math.sqrt(252.0)

    @staticmethod
    def _sma(series: List[float], idx: int, window: int) -> float:
        return sum(series[idx - window + 1 : idx + 1]) / float(window)

    def _compile_risk_parity(
        self,
        out: List[Dict[str, float]],
        closes: Dict[str, List[float]],
        symbols: List[str],
        lag: int,
        vol_window: int,
        rebal_every: int,
    ) -> None:
        n = len(out)
        last_weights = {s: 0.0 for s in symbols}
        for t in range(n):
            obs = t - lag
            if obs < vol_window:
                continue
            if (t - lag - vol_window) % rebal_every == 0 or sum(abs(v) for v in last_weights.values()) == 0.0:
                inv_vols = {}
                for s in symbols:
                    vol = max(self._trailing_vol(closes[s], obs, vol_window), 0.05)
                    inv_vols[s] = 1.0 / vol
                total = sum(inv_vols.values())
                last_weights = {s: inv_vols[s] / total for s in symbols}
            out[t] = dict(last_weights)

    def _compile_trend_ma(
        self,
        out: List[Dict[str, float]],
        closes: Dict[str, List[float]],
        symbols: List[str],
        spec: StrategySpec,
        lag: int,
    ) -> None:
        fast_w = int(spec.parameters["fast_window"])
        slow_w = int(spec.parameters["slow_window"])
        vol_w = int(spec.parameters["vol_window"])
        target_vol = float(spec.parameters["target_vol"])
        rebal_band = float(spec.parameters["rebalance_band"])
        warmup = max(slow_w, vol_w)
        n = len(out)
        prev_w = {s: 0.0 for s in symbols}
        per_asset_cap = 1.0 / len(symbols)
        for t in range(n):
            obs = t - lag
            if obs < warmup:
                continue
            cur_w = {}
            for s in symbols:
                fast_ma = self._sma(closes[s], obs, fast_w)
                slow_ma = self._sma(closes[s], obs, slow_w)
                direction = 1.0 if fast_ma > slow_ma else (-1.0 if fast_ma < slow_ma else 0.0)
                vol = max(self._trailing_vol(closes[s], obs, vol_w), 0.08)
                scale = min(target_vol / vol, 1.5)
                desired = direction * per_asset_cap * scale
                if abs(desired - prev_w[s]) < rebal_band * per_asset_cap:
                    desired = prev_w[s]
                cur_w[s] = desired
            prev_w = cur_w
            out[t] = cur_w

    def _compile_mean_reversion(
        self,
        out: List[Dict[str, float]],
        closes: Dict[str, List[float]],
        symbols: List[str],
        spec: StrategySpec,
        lag: int,
    ) -> None:
        lookback = int(spec.parameters["lookback_window"])
        entry_z = float(spec.parameters["entry_z"])
        exit_z = float(spec.parameters["exit_z"])
        vol_w = int(spec.parameters["vol_window"])
        target_vol = float(spec.parameters["target_vol"])
        warmup = max(lookback, vol_w)
        n = len(out)
        pos_state = {s: 0.0 for s in symbols}
        per_asset_cap = 1.0 / len(symbols)
        for t in range(n):
            obs = t - lag
            if obs < warmup:
                continue
            cur_w = {}
            for s in symbols:
                window_vals = closes[s][obs - lookback + 1 : obs + 1]
                mean = sum(window_vals) / lookback
                var = sum((x - mean) ** 2 for x in window_vals) / max(lookback - 1, 1)
                std = math.sqrt(max(var, 1e-12))
                z = (closes[s][obs] - mean) / std
                state = pos_state[s]
                if state == 0.0:
                    if z <= -entry_z:
                        state = 1.0
                    elif z >= entry_z:
                        state = -1.0
                elif state > 0.0 and z >= -exit_z:
                    state = 0.0
                elif state < 0.0 and z <= exit_z:
                    state = 0.0
                pos_state[s] = state
                vol = max(self._trailing_vol(closes[s], obs, vol_w), 0.08)
                scale = min(target_vol / vol, 1.5)
                cur_w[s] = state * per_asset_cap * scale
            out[t] = cur_w

    def _compile_vol_breakout(
        self,
        out: List[Dict[str, float]],
        closes: Dict[str, List[float]],
        highs: Dict[str, List[float]],
        lows: Dict[str, List[float]],
        symbols: List[str],
        spec: StrategySpec,
        lag: int,
    ) -> None:
        bo_w = int(spec.parameters["breakout_window"])
        exit_w = int(spec.parameters["exit_window"])
        vol_w = int(spec.parameters["vol_window"])
        target_vol = float(spec.parameters["target_vol"])
        warmup = max(bo_w, exit_w, vol_w) + 1
        n = len(out)
        pos_state = {s: 0.0 for s in symbols}
        per_asset_cap = 1.0 / len(symbols)
        for t in range(n):
            obs = t - lag
            if obs < warmup:
                continue
            cur_w = {}
            for s in symbols:
                px = closes[s][obs]
                upper = max(highs[s][obs - bo_w : obs])
                lower = min(lows[s][obs - bo_w : obs])
                exit_low = min(lows[s][obs - exit_w : obs])
                exit_high = max(highs[s][obs - exit_w : obs])
                state = pos_state[s]
                if px > upper:
                    state = 1.0
                elif px < lower:
                    state = -1.0
                elif state > 0.0 and px < exit_low:
                    state = 0.0
                elif state < 0.0 and px > exit_high:
                    state = 0.0
                pos_state[s] = state
                vol = max(self._trailing_vol(closes[s], obs, vol_w), 0.08)
                scale = min(target_vol / vol, 1.5)
                cur_w[s] = state * per_asset_cap * scale
            out[t] = cur_w

    def _compile_dual_momentum(
        self,
        out: List[Dict[str, float]],
        closes: Dict[str, List[float]],
        symbols: List[str],
        spec: StrategySpec,
        lag: int,
    ) -> None:
        mom_w = int(spec.parameters["momentum_window"])
        top_k = int(spec.parameters["top_k"])
        rebal_every = int(spec.parameters["rebalance_every_bars"])
        n = len(out)
        last_w = {s: 0.0 for s in symbols}
        for t in range(n):
            obs = t - lag
            if obs < mom_w:
                continue
            if (obs - mom_w) % rebal_every == 0:
                scores = []
                for s in symbols:
                    ret = closes[s][obs] / closes[s][obs - mom_w] - 1.0
                    scores.append((ret, s))
                scores.sort(key=lambda x: (-x[0], x[1]))
                winners = [s for ret, s in scores[:top_k] if ret > 0.0]
                last_w = {s: (1.0 / len(winners) if s in winners else 0.0) for s in symbols}
            out[t] = dict(last_w)

    @staticmethod
    def _normalize_weights(
        weights: Dict[str, float],
        max_single: float,
        max_gross: float,
    ) -> Dict[str, float]:
        clipped = {
            s: max(-max_single, min(max_single, float(w)))
            for s, w in weights.items()
        }
        gross = sum(abs(v) for v in clipped.values())
        if gross > max_gross and gross > 0.0:
            factor = max_gross / gross
            clipped = {s: v * factor for s, v in clipped.items()}
        return clipped
