"""Close decisions, next opening auction fills and close-to-close rewards."""
import math
from dataclasses import dataclass
from numbers import Integral

from .market import ContractError, validate

TARGETS = (0.0, 0.5, 1.0)
STATE_SHAPE = (3, 3, 5)


@dataclass(frozen=True)
class MarketRules:
    initial_cash: float = 10000
    fee_bps: float = 2
    slippage_bps: float = 5
    participation: float = 0.05

    def __post_init__(self):
        limits = ((self.fee_bps, 0, 1000), (self.slippage_bps, 0, 1000),
                  (self.participation, 0, 1))
        if not math.isfinite(self.initial_cash) or self.initial_cash <= 0 or any(
            not low <= value <= high for value, low, high in limits
        ):
            raise ContractError("rules", "Invalid starting capital, cost or participation limit")


def direction(change):
    return 2 if change > 0.002 else 0 if change < -0.002 else 1


class AllocationEnv:
    def __init__(self, bars, rules=MarketRules(), start=0, end=None):
        self.bars = validate(bars)
        self.rules = rules
        self.start = start
        self.end = len(bars) - 1 if end is None else end
        if not 0 <= self.start < self.end < len(bars):
            raise ContractError("window", "Invalid decision/valuation window")
        self.active = False

    def reset(self, *, seed=None, options=None):
        # Given a session series, fills and observations are deterministic.
        self.index = self.start
        self.cash = self.rules.initial_cash
        self.shares = 0.0
        self.active = True
        return self.observation(), self.account()

    def account(self):
        bar = self.bars[self.index]
        return dict(time=bar.closed.isoformat(), cash=self.cash, shares=self.shares,
                    equity=self.cash + self.shares * bar.close_usd)

    def observation(self):
        i = self.index
        price = self.bars[i].close_usd
        changes = [price / self.bars[max(0, i - lag)].close_usd - 1 for lag in (1, 5)]
        value = self.shares * price
        exposure = value / (self.cash + value)
        return (direction(changes[0]), direction(changes[1]), round(4 * exposure))

    def step(self, action):
        if not self.active:
            raise ContractError("inactive", "Reset before taking another step")
        if isinstance(action, bool) or not isinstance(action, Integral) or not 0 <= action < len(TARGETS):
            raise ContractError("action", "Expected allocation action 0, 1 or 2")
        previous = self.account()
        bar = self.bars[self.index + 1]
        mid = bar.open_usd
        weight = TARGETS[action]
        value = self.shares * mid
        delta_usd = weight * (self.cash + value) - value
        sign = 1 if delta_usd >= 0 else -1
        slip = self.rules.slippage_bps / 10000
        fee = self.rules.fee_bps / 10000
        fill_price = mid * (1 + sign * slip)
        # Solve for target weight after fees and adverse price movement.
        friction = abs(fill_price - mid) + fee * fill_price
        desired = abs(delta_usd) / (mid + sign * weight * friction)
        affordable = self.cash / (fill_price * (1 + fee)) if sign > 0 else self.shares
        quantity = sign * min(desired, affordable, self.rules.participation * bar.auction_shares)
        commission = abs(quantity) * fill_price * fee
        self.cash = max(0.0, self.cash - quantity * fill_price - commission)
        self.shares += quantity
        self.index += 1
        self.active = self.index < self.end
        info = self.account()
        info.update(decision_time=previous["time"], fill_time=bar.opened.isoformat(),
                    target_weight=weight, requested_shares=sign * desired, filled_shares=quantity,
                    fill_price=fill_price if quantity else None, notional=abs(quantity) * mid,
                    fee=commission, slippage=abs(quantity) * abs(fill_price - mid))
        reward = math.log(info["equity"] / previous["equity"])
        return self.observation(), reward, not self.active, False, info
