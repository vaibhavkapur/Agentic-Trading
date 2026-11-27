"""Independent deterministic risk service (executed both pre-approval and pre-dispatch)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from trading_platform.domain.config import PolicyConfig, RiskLimitsConfig
from trading_platform.domain.contracts import (
    AccountSnapshot,
    PortfolioProposal,
    QuoteSnapshot,
    RiskAssessment,
    RiskCheckItem,
)
from trading_platform.domain.types import OrderSide, OrderType, RiskStatus


class IndependentRiskService:
    """Deterministic risk engine independent of research and portfolio agents."""

    def __init__(self, *, policy: PolicyConfig, limits: RiskLimitsConfig) -> None:
        self._policy = policy
        self._limits = limits

    def evaluate(
        self,
        *,
        proposal: PortfolioProposal,
        account: AccountSnapshot,
        quotes: dict[str, QuoteSnapshot],
        now_utc: datetime,
        stage: str,
    ) -> RiskAssessment:
        if stage not in {"PRE_APPROVAL", "PRE_DISPATCH"}:
            raise ValueError(f"Unsupported risk evaluation stage: {stage}")

        intent = proposal.order_intent
        checks: list[RiskCheckItem] = []

        # 1. Symbol allowlist check
        symbol_allowed = intent.symbol in self._policy.allowed_symbols
        checks.append(
            RiskCheckItem(
                check_name="symbol_allowlist",
                passed=symbol_allowed,
                code="OK" if symbol_allowed else "SYMBOL_NOT_ALLOWED",
                message=(
                    f"Symbol {intent.symbol} is permitted by policy {self._policy.policy_version}."
                    if symbol_allowed
                    else f"Symbol {intent.symbol} is not in allowed_symbols."
                ),
                observed_value=intent.symbol,
                limit_value=",".join(self._policy.allowed_symbols),
            )
        )

        # 2. Quote availability and staleness check
        quote = quotes.get(intent.symbol)
        quote_age_seconds: float | None = None
        if quote is None:
            checks.append(
                RiskCheckItem(
                    check_name="quote_freshness",
                    passed=False,
                    code="MISSING_MARKET_DATA",
                    message=f"No live/paper quote found for {intent.symbol}.",
                )
            )
            return RiskAssessment(
                assessment_id=f"RISK-{uuid4().hex[:10].upper()}",
                run_id=proposal.run_id,
                proposal_id=proposal.proposal_id,
                stage=stage,
                policy_version=self._policy.policy_version,
                status=RiskStatus.REJECTED,
                checks=checks,
                quote_timestamp_utc=None,
                evaluated_at_utc=now_utc,
                nav_usd=account.cash_usd,
                projected_gross_exposure_usd=Decimal("0.00"),
                projected_position_notional_usd=Decimal("0.00"),
            )

        quote_age_seconds = (now_utc - quote.quote_timestamp_utc).total_seconds()
        quote_fresh = 0 <= quote_age_seconds <= self._limits.max_quote_age_seconds
        checks.append(
            RiskCheckItem(
                check_name="quote_freshness",
                passed=quote_fresh,
                code="OK" if quote_fresh else "STALE_MARKET_DATA",
                message=(
                    f"Quote age {quote_age_seconds:.1f}s within {self._limits.max_quote_age_seconds}s limit."
                    if quote_fresh
                    else f"Quote age {quote_age_seconds:.1f}s exceeds max_quote_age_seconds={self._limits.max_quote_age_seconds}s."
                ),
                observed_value=f"{quote_age_seconds:.1f}s",
                limit_value=f"{self._limits.max_quote_age_seconds}s",
            )
        )

        # 3. Price collar / deviation check for LIMIT orders
        exec_price = intent.limit_price if intent.order_type == OrderType.LIMIT and intent.limit_price else quote.mid
        mid = quote.mid
        deviation_bps = int(((abs(exec_price - mid) / mid) * Decimal("10000")).quantize(Decimal("1")))
        price_ok = deviation_bps <= self._limits.max_price_deviation_bps
        checks.append(
            RiskCheckItem(
                check_name="price_collar",
                passed=price_ok,
                code="OK" if price_ok else "PRICE_DEVIATION_BREACH",
                message=(
                    f"Order price deviation {deviation_bps} bps within {self._limits.max_price_deviation_bps} bps."
                    if price_ok
                    else f"Order price deviation {deviation_bps} bps exceeds {self._limits.max_price_deviation_bps} bps limit."
                ),
                observed_value=f"{deviation_bps}bps",
                limit_value=f"{self._limits.max_price_deviation_bps}bps",
            )
        )

        # Compute current NAV and gross exposure across all positions
        current_gross = Decimal("0.00")
        for sym, pos in account.positions.items():
            px = quotes[sym].last if sym in quotes else pos.avg_cost_usd
            current_gross += (px * Decimal(pos.quantity)).quantize(Decimal("0.01"))
        nav_usd = (account.cash_usd + current_gross).quantize(Decimal("0.01"))

        order_notional = (exec_price * Decimal(intent.quantity)).quantize(Decimal("0.01"))

        # 4. Single order notional cap
        order_cap_ok = order_notional <= self._limits.max_order_notional_usd
        checks.append(
            RiskCheckItem(
                check_name="max_order_notional",
                passed=order_cap_ok,
                code="OK" if order_cap_ok else "ORDER_NOTIONAL_BREACH",
                message=(
                    f"Order notional ${order_notional} within ${self._limits.max_order_notional_usd} cap."
                    if order_cap_ok
                    else f"Order notional ${order_notional} exceeds ${self._limits.max_order_notional_usd} cap."
                ),
                observed_value=str(order_notional),
                limit_value=str(self._limits.max_order_notional_usd),
            )
        )

        # 5. Single order % NAV cap
        order_pct_nav = (order_notional / nav_usd) if nav_usd > Decimal("0") else Decimal("1")
        order_pct_ok = order_pct_nav <= self._limits.max_single_order_pct_nav
        checks.append(
            RiskCheckItem(
                check_name="max_single_order_pct_nav",
                passed=order_pct_ok,
                code="OK" if order_pct_ok else "ORDER_PCT_NAV_BREACH",
                message=(
                    f"Order size {order_pct_nav:.2%} of NAV within {self._limits.max_single_order_pct_nav:.2%}."
                    if order_pct_ok
                    else f"Order size {order_pct_nav:.2%} of NAV exceeds {self._limits.max_single_order_pct_nav:.2%}."
                ),
                observed_value=f"{order_pct_nav:.4f}",
                limit_value=str(self._limits.max_single_order_pct_nav),
            )
        )

        # 6. Inventory / Cash buffer check
        existing_pos = account.positions.get(intent.symbol)
        existing_qty = existing_pos.quantity if existing_pos else 0
        if intent.side == OrderSide.BUY:
            projected_qty = existing_qty + intent.quantity
            projected_cash = (account.cash_usd - order_notional).quantize(Decimal("0.01"))
            cash_ok = projected_cash >= self._limits.min_cash_buffer_usd
            checks.append(
                RiskCheckItem(
                    check_name="cash_buffer",
                    passed=cash_ok,
                    code="OK" if cash_ok else "INSUFFICIENT_CASH_BUFFER",
                    message=(
                        f"Post-trade cash ${projected_cash} meets ${self._limits.min_cash_buffer_usd} buffer."
                        if cash_ok
                        else f"Post-trade cash ${projected_cash} falls below ${self._limits.min_cash_buffer_usd} buffer."
                    ),
                    observed_value=str(projected_cash),
                    limit_value=str(self._limits.min_cash_buffer_usd),
                )
            )
        else:
            projected_qty = existing_qty - intent.quantity
            inventory_ok = projected_qty >= 0
            checks.append(
                RiskCheckItem(
                    check_name="sell_inventory",
                    passed=inventory_ok,
                    code="OK" if inventory_ok else "INSUFFICIENT_POSITION_FOR_SELL",
                    message=(
                        f"Sell quantity {intent.quantity} within held inventory {existing_qty}."
                        if inventory_ok
                        else f"Sell quantity {intent.quantity} exceeds held inventory {existing_qty} (shorting disabled)."
                    ),
                    observed_value=str(intent.quantity),
                    limit_value=str(existing_qty),
                )
            )

        # 7. Post-trade position concentration & gross exposure
        projected_pos_notional = (quote.last * Decimal(max(0, projected_qty))).quantize(Decimal("0.01"))
        current_pos_notional = (quote.last * Decimal(existing_qty)).quantize(Decimal("0.01"))
        projected_gross = (current_gross - current_pos_notional + projected_pos_notional).quantize(
            Decimal("0.01")
        )

        pos_cap_ok = projected_pos_notional <= self._limits.max_position_notional_usd
        checks.append(
            RiskCheckItem(
                check_name="max_position_notional",
                passed=pos_cap_ok,
                code="OK" if pos_cap_ok else "POSITION_NOTIONAL_BREACH",
                message=(
                    f"Projected position ${projected_pos_notional} within ${self._limits.max_position_notional_usd}."
                    if pos_cap_ok
                    else f"Projected position ${projected_pos_notional} exceeds ${self._limits.max_position_notional_usd}."
                ),
                observed_value=str(projected_pos_notional),
                limit_value=str(self._limits.max_position_notional_usd),
            )
        )

        pos_pct_nav = (projected_pos_notional / nav_usd) if nav_usd > Decimal("0") else Decimal("1")
        pos_pct_ok = pos_pct_nav <= self._limits.max_position_pct_nav
        checks.append(
            RiskCheckItem(
                check_name="max_position_pct_nav",
                passed=pos_pct_ok,
                code="OK" if pos_pct_ok else "POSITION_PCT_NAV_BREACH",
                message=(
                    f"Projected position {pos_pct_nav:.2%} of NAV within {self._limits.max_position_pct_nav:.2%}."
                    if pos_pct_ok
                    else f"Projected position {pos_pct_nav:.2%} of NAV exceeds {self._limits.max_position_pct_nav:.2%}."
                ),
                observed_value=f"{pos_pct_nav:.4f}",
                limit_value=str(self._limits.max_position_pct_nav),
            )
        )

        gross_ok = projected_gross <= self._limits.max_gross_exposure_usd
        checks.append(
            RiskCheckItem(
                check_name="max_gross_exposure",
                passed=gross_ok,
                code="OK" if gross_ok else "GROSS_EXPOSURE_BREACH",
                message=(
                    f"Projected gross exposure ${projected_gross} within ${self._limits.max_gross_exposure_usd}."
                    if gross_ok
                    else f"Projected gross exposure ${projected_gross} exceeds ${self._limits.max_gross_exposure_usd}."
                ),
                observed_value=str(projected_gross),
                limit_value=str(self._limits.max_gross_exposure_usd),
            )
        )

        all_passed = all(c.passed for c in checks)
        return RiskAssessment(
            assessment_id=f"RISK-{uuid4().hex[:10].upper()}",
            run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            stage=stage,
            policy_version=self._policy.policy_version,
            status=RiskStatus.APPROVED if all_passed else RiskStatus.REJECTED,
            checks=checks,
            quote_timestamp_utc=quote.quote_timestamp_utc,
            evaluated_at_utc=now_utc,
            nav_usd=nav_usd,
            projected_gross_exposure_usd=projected_gross,
            projected_position_notional_usd=projected_pos_notional,
        )
