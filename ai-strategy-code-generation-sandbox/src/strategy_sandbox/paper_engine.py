"""Pure deterministic paper execution and double-entry accounting engine.

Isolated strictly from I/O and untrusted strategy code.
Accounting convention:
- Market orders emitted on bar t fill at bar t close adjusted by slippage_bps:
    BUY  fill_price = close * (1 + slippage_bps / 10_000)
    SELL fill_price = close * (1 - slippage_bps / 10_000)
- Commission = abs(quantity) * fill_price * (commission_bps / 10_000).
- Exact portfolio accounting identity enforced at every bar:
    equity = cash + sum(qty_i * close_i)
    equity - initial_cash == realized_pnl + unrealized_pnl - cumulative_commission
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .contracts import (
    AccountingSummary,
    AssetBar,
    CheckResult,
    DatasetManifest,
    EquityPoint,
    FillRecord,
    OrderIntent,
    RejectedOrderRecord,
    StrategySpec,
)


@dataclass
class _PositionState:
    symbol: str
    quantity: float = 0.0
    avg_cost: float = 0.0


def group_bars_by_timestamp(dataset: DatasetManifest) -> list[tuple[datetime, dict[str, AssetBar]]]:
    """Group globally time-ordered bars into chronological step slices."""
    steps: list[tuple[datetime, dict[str, AssetBar]]] = []
    for bar in dataset.bars:
        if not steps or steps[-1][0] != bar.timestamp:
            steps.append((bar.timestamp, {bar.symbol: bar}))
        else:
            steps[-1][1][bar.symbol] = bar
    return steps


class PaperPortfolioEngine:
    """Pure state-transition engine for deterministic paper trading and accounting."""

    def __init__(self, spec: StrategySpec) -> None:
        self.spec = spec
        self.initial_cash: float = float(spec.initial_cash)
        self.cash: float = float(spec.initial_cash)
        self.positions: dict[str, _PositionState] = {}
        self.last_prices: dict[str, float] = {}
        self.realized_pnl: float = 0.0
        self.cumulative_commission: float = 0.0
        self.cumulative_slippage_cost: float = 0.0
        self.total_notional_turnover: float = 0.0

        self.fills: list[FillRecord] = []
        self.rejected_orders: list[RejectedOrderRecord] = []
        self.equity_curve: list[EquityPoint] = []
        self._target_symbols: set[str] = set(spec.target_symbols)

    def current_positions_snapshot(self, current_bars: dict[str, AssetBar]) -> dict[str, dict[str, float]]:
        """Serialize current portfolio positions for read-only StrategyContext."""
        snapshot: dict[str, dict[str, float]] = {}
        for sym, pos in sorted(self.positions.items()):
            if abs(pos.quantity) <= 1e-12:
                continue
            mark = current_bars[sym].close if sym in current_bars else self.last_prices.get(sym, pos.avg_cost)
            snapshot[sym] = {
                "symbol": sym,
                "quantity": pos.quantity,
                "avg_cost": pos.avg_cost,
                "market_value": pos.quantity * mark,
            }
        return snapshot

    def mark_to_market_equity(self, current_bars: dict[str, AssetBar]) -> float:
        """Compute current mark-to-market equity before processing orders on this step."""
        total_pos_value = 0.0
        for sym, pos in self.positions.items():
            if abs(pos.quantity) <= 1e-12:
                continue
            mark = current_bars[sym].close if sym in current_bars else self.last_prices.get(sym, pos.avg_cost)
            total_pos_value += pos.quantity * mark
        return self.cash + total_pos_value

    def process_step(
        self,
        *,
        step: int,
        timestamp: datetime,
        current_bars: dict[str, AssetBar],
        orders: Sequence[OrderIntent],
    ) -> EquityPoint:
        """Apply orders on a single bar and record mark-to-market equity & invariants."""
        for sym, bar in current_bars.items():
            self.last_prices[sym] = bar.close

        for order in orders:
            self._apply_order(step=step, timestamp=timestamp, current_bars=current_bars, order=order)

        return self._record_equity_point(step=step, timestamp=timestamp)

    def _apply_order(
        self,
        *,
        step: int,
        timestamp: datetime,
        current_bars: dict[str, AssetBar],
        order: OrderIntent,
    ) -> None:
        sym = order.symbol
        if sym not in self._target_symbols:
            self._reject(step, timestamp, order, f"Symbol '{sym}' not in spec target_symbols")
            return
        if sym not in current_bars:
            self._reject(step, timestamp, order, f"No bar available for '{sym}' at step {step}")
            return

        ref_price = current_bars[sym].close
        slippage_frac = self.spec.slippage_bps / 10_000.0
        comm_frac = self.spec.commission_bps / 10_000.0

        signed_qty = order.quantity if order.side == "BUY" else -order.quantity
        fill_price = ref_price * (1.0 + slippage_frac) if order.side == "BUY" else ref_price * (1.0 - slippage_frac)
        if fill_price <= 0.0 or not math.isfinite(fill_price):
            self._reject(step, timestamp, order, "Computed non-positive fill price")
            return

        notional = abs(signed_qty) * fill_price
        commission = notional * comm_frac
        slippage_cost = abs(signed_qty) * abs(fill_price - ref_price)

        pos = self.positions.get(sym) or _PositionState(symbol=sym)
        proposed_qty = pos.quantity + signed_qty

        if not self.spec.allow_short and proposed_qty < -1e-9:
            self._reject(
                step,
                timestamp,
                order,
                f"Short selling disabled: current qty={pos.quantity:.6f}, order={order.side} {order.quantity:.6f}",
            )
            return

        proposed_cash = self.cash - (signed_qty * fill_price) - commission
        if self.spec.max_gross_leverage <= 1.0 and proposed_cash < -1e-6:
            self._reject(
                step,
                timestamp,
                order,
                f"Insufficient cash: available={self.cash:.2f}, required={(signed_qty * fill_price) + commission:.2f}",
            )
            return

        # Compute post-trade equity and exposure limits
        projected_equity = proposed_cash
        projected_gross = 0.0
        for other_sym, other_pos in self.positions.items():
            q = proposed_qty if other_sym == sym else other_pos.quantity
            mark = self.last_prices[other_sym]
            projected_equity += q * mark
            projected_gross += abs(q * mark)
        if sym not in self.positions:
            projected_equity += proposed_qty * ref_price
            projected_gross += abs(proposed_qty * ref_price)

        if projected_equity <= 0.0:
            self._reject(step, timestamp, order, "Order would result in non-positive portfolio equity")
            return

        proposed_sym_exposure = abs(proposed_qty * ref_price)
        # Allow risk-reducing trades even if already above limit; block risk-increasing breaches
        prev_sym_exposure = abs(pos.quantity * ref_price)
        if (
            proposed_sym_exposure > prev_sym_exposure + 1e-9
            and (proposed_sym_exposure / projected_equity) > self.spec.max_position_pct + 1e-9
        ):
            self._reject(
                step,
                timestamp,
                order,
                f"Position exposure {proposed_sym_exposure / projected_equity:.4f} exceeds max_position_pct {self.spec.max_position_pct:.4f}",
            )
            return

        prev_gross = sum(
            abs(p.quantity * self.last_prices[s]) for s, p in self.positions.items() if abs(p.quantity) > 1e-12
        )
        if (
            projected_gross > prev_gross + 1e-9
            and (projected_gross / projected_equity) > self.spec.max_gross_leverage + 1e-9
        ):
            self._reject(
                step,
                timestamp,
                order,
                f"Gross leverage {projected_gross / projected_equity:.4f} exceeds max_gross_leverage {self.spec.max_gross_leverage:.4f}",
            )
            return

        # Execute position update & exact realized PnL calculation
        realized_delta = 0.0
        old_qty = pos.quantity
        old_avg = pos.avg_cost

        if abs(old_qty) <= 1e-12:
            pos.quantity = proposed_qty
            pos.avg_cost = fill_price
        elif (old_qty > 0 and signed_qty > 0) or (old_qty < 0 and signed_qty < 0):
            # Adding to existing position
            total_cost = abs(old_qty) * old_avg + abs(signed_qty) * fill_price
            pos.quantity = proposed_qty
            pos.avg_cost = total_cost / abs(proposed_qty)
        else:
            # Reducing, closing, or flipping position
            closed_qty = min(abs(old_qty), abs(signed_qty))
            if old_qty > 0:
                realized_delta = closed_qty * (fill_price - old_avg)
            else:
                realized_delta = closed_qty * (old_avg - fill_price)

            if abs(proposed_qty) <= 1e-12:
                pos.quantity = 0.0
                pos.avg_cost = 0.0
            elif (old_qty > 0 and proposed_qty > 0) or (old_qty < 0 and proposed_qty < 0):
                pos.quantity = proposed_qty
                pos.avg_cost = old_avg
            else:
                # Flipped across zero
                pos.quantity = proposed_qty
                pos.avg_cost = fill_price

        self.positions[sym] = pos
        self.cash = proposed_cash
        self.realized_pnl += realized_delta
        self.cumulative_commission += commission
        self.cumulative_slippage_cost += slippage_cost
        self.total_notional_turnover += notional

        self.fills.append(
            FillRecord(
                step=step,
                timestamp=timestamp,
                symbol=sym,
                side=order.side,
                quantity=order.quantity,
                reference_price=ref_price,
                fill_price=fill_price,
                notional=notional,
                commission=commission,
                slippage_cost=slippage_cost,
                realized_pnl_delta=realized_delta,
                reason=order.reason,
            )
        )

    def _reject(self, step: int, timestamp: datetime, order: OrderIntent, reason: str) -> None:
        self.rejected_orders.append(
            RejectedOrderRecord(
                step=step,
                timestamp=timestamp,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                rejection_reason=reason,
            )
        )

    def _record_equity_point(self, *, step: int, timestamp: datetime) -> EquityPoint:
        positions_mv = 0.0
        unrealized = 0.0
        gross_exposure = 0.0
        for sym, pos in self.positions.items():
            if abs(pos.quantity) <= 1e-12:
                continue
            mark = self.last_prices[sym]
            mv = pos.quantity * mark
            positions_mv += mv
            gross_exposure += abs(mv)
            unrealized += pos.quantity * (mark - pos.avg_cost)

        equity = self.cash + positions_mv
        gross_leverage = (gross_exposure / equity) if equity > 0.0 else float("inf")

        expected_equity = (
            self.initial_cash + self.realized_pnl + unrealized - self.cumulative_commission
        )
        identity_error = abs(equity - expected_equity)

        point = EquityPoint(
            step=step,
            timestamp=timestamp,
            cash=self.cash,
            positions_market_value=positions_mv,
            equity=equity,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=unrealized,
            cumulative_commission=self.cumulative_commission,
            gross_exposure=gross_exposure,
            gross_leverage=gross_leverage,
            identity_error=identity_error,
        )
        self.equity_curve.append(point)
        return point

    def summarize(self) -> AccountingSummary:
        """Compute aggregate accounting metrics over the completed equity curve."""
        if not self.equity_curve:
            return AccountingSummary(
                initial_cash=self.initial_cash,
                final_cash=self.cash,
                final_equity=self.initial_cash,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                total_commission=0.0,
                total_slippage_cost=0.0,
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                trade_count=0,
                rejected_order_count=len(self.rejected_orders),
                turnover=0.0,
                max_observed_leverage=0.0,
                max_accounting_identity_error=0.0,
                ending_positions={},
            )

        last = self.equity_curve[-1]
        peak = self.initial_cash
        max_dd = 0.0
        returns: list[float] = []
        prev_eq = self.initial_cash
        max_lev = 0.0
        max_err = 0.0

        for pt in self.equity_curve:
            if pt.equity > peak:
                peak = pt.equity
            dd = (peak - pt.equity) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
            if prev_eq > 0:
                returns.append((pt.equity - prev_eq) / prev_eq)
            prev_eq = pt.equity
            if pt.gross_leverage > max_lev:
                max_lev = pt.gross_leverage
            if pt.identity_error > max_err:
                max_err = pt.identity_error

        sharpe = 0.0
        if len(returns) >= 2:
            mean_r = sum(returns) / len(returns)
            var_r = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
            std_r = math.sqrt(var_r)
            if std_r > 1e-12:
                sharpe = (mean_r / std_r) * math.sqrt(252.0)

        ending_positions = {
            sym: pos.quantity
            for sym, pos in sorted(self.positions.items())
            if abs(pos.quantity) > 1e-12
        }

        return AccountingSummary(
            initial_cash=self.initial_cash,
            final_cash=last.cash,
            final_equity=last.equity,
            realized_pnl=last.realized_pnl,
            unrealized_pnl=last.unrealized_pnl,
            total_commission=last.cumulative_commission,
            total_slippage_cost=self.cumulative_slippage_cost,
            total_return_pct=((last.equity - self.initial_cash) / self.initial_cash) * 100.0,
            max_drawdown_pct=max_dd * 100.0,
            sharpe_ratio=sharpe,
            trade_count=len(self.fills),
            rejected_order_count=len(self.rejected_orders),
            turnover=self.total_notional_turnover,
            max_observed_leverage=max_lev,
            max_accounting_identity_error=max_err,
            ending_positions=ending_positions,
        )


def verify_accounting_invariants(
    summary: AccountingSummary,
    equity_curve: Sequence[EquityPoint],
    spec: StrategySpec,
    *,
    tolerance: float = 1e-6,
) -> CheckResult:
    """Verify exact accounting reconciliation and risk/numeric invariants."""
    errors: list[str] = []

    if not equity_curve:
        errors.append("Equity curve is empty.")

    if summary.max_accounting_identity_error > tolerance:
        errors.append(
            f"Max accounting identity error {summary.max_accounting_identity_error:.3e} exceeds tolerance {tolerance:.3e}."
        )

    for pt in equity_curve:
        for val_name, val in (
            ("cash", pt.cash),
            ("equity", pt.equity),
            ("realized_pnl", pt.realized_pnl),
            ("unrealized_pnl", pt.unrealized_pnl),
        ):
            if not math.isfinite(val):
                errors.append(f"Non-finite {val_name} at step {pt.step}.")
        if pt.equity <= 0.0:
            errors.append(f"Non-positive equity {pt.equity:.2f} at step {pt.step}.")

    if summary.max_observed_leverage > spec.max_gross_leverage + 1e-6:
        errors.append(
            f"Observed max leverage {summary.max_observed_leverage:.4f} exceeded spec limit {spec.max_gross_leverage:.4f}."
        )

    if errors:
        return CheckResult(
            name="accounting_invariants",
            passed=False,
            code="ACCOUNTING_INVARIANT_VIOLATION",
            message=errors[0],
            details={
                "errors": errors[:10],
                "max_identity_error": summary.max_accounting_identity_error,
                "max_observed_leverage": summary.max_observed_leverage,
            },
        )

    return CheckResult(
        name="accounting_invariants",
        passed=True,
        code="OK",
        message=(
            f"Accounting reconciled across {len(equity_curve)} steps "
            f"(max identity error={summary.max_accounting_identity_error:.2e}, "
            f"trades={summary.trade_count})."
        ),
        details={
            "steps": len(equity_curve),
            "trade_count": summary.trade_count,
            "final_equity": round(summary.final_equity, 6),
            "max_identity_error": summary.max_accounting_identity_error,
            "max_observed_leverage": summary.max_observed_leverage,
        },
    )
