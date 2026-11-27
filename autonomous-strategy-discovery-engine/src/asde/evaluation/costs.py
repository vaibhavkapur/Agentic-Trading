"""Transaction cost scenarios and deterministic cost computation."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Any, Dict

from asde.errors import DataContractError
from asde.types import sha256_canonical


@dataclass(frozen=True)
class CostScenario:
    """Explicit transaction and financing cost model (all rates in basis points)."""

    name: str
    description: str
    commission_bps: float
    half_spread_bps: float
    slippage_bps: float
    borrow_annual_bps: float
    impact_coeff_bps: float
    currency: str = "USD"

    def validate(self) -> None:
        fields = (
            self.commission_bps,
            self.half_spread_bps,
            self.slippage_bps,
            self.borrow_annual_bps,
            self.impact_coeff_bps,
        )
        if any(v < 0.0 for v in fields):
            raise DataContractError(f"Cost parameters must be non-negative in scenario {self.name!r}.")

    @property
    def linear_trade_bps(self) -> float:
        return self.commission_bps + self.half_spread_bps + self.slippage_bps

    def bar_cost(
        self,
        traded_notional_fraction: float,
        short_notional_fraction: float,
        annualization_factor: int = 252,
    ) -> float:
        """Compute total fractional NAV cost for a single bar.

        Args:
            traded_notional_fraction: Sum of abs(target_weight - drifted_weight) across assets.
            short_notional_fraction: Sum of abs(min(weight, 0)) across assets.
            annualization_factor: Trading bars per year.
        """
        linear_cost = traded_notional_fraction * (self.linear_trade_bps / 10_000.0)
        # Mild non-linear market impact proportional to traded_notional^1.5
        impact_cost = (traded_notional_fraction ** 1.5) * (self.impact_coeff_bps / 10_000.0)
        borrow_cost = short_notional_fraction * (self.borrow_annual_bps / 10_000.0) / float(annualization_factor)
        return linear_cost + impact_cost + borrow_cost

    def fingerprint(self) -> str:
        return sha256_canonical(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_cost_scenarios(path: Path) -> Dict[str, CostScenario]:
    """Load and validate versioned transaction-cost scenarios."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    currency = raw.get("currency", "USD")
    scenarios: Dict[str, CostScenario] = {}
    for name, sdata in raw["scenarios"].items():
        scenario = CostScenario(
            name=sdata["name"],
            description=sdata["description"],
            commission_bps=float(sdata["commission_bps"]),
            half_spread_bps=float(sdata["half_spread_bps"]),
            slippage_bps=float(sdata["slippage_bps"]),
            borrow_annual_bps=float(sdata["borrow_annual_bps"]),
            impact_coeff_bps=float(sdata["impact_coeff_bps"]),
            currency=currency,
        )
        scenario.validate()
        scenarios[name] = scenario
    return scenarios
