"""Hard-enforced iteration, cost, compute, and token budgets plus stop conditions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Optional

from rarp.domain.dsl import BudgetSpec, StopConditionsSpec
from rarp.domain.errors import BudgetExhaustedError


@dataclass(frozen=True)
class BudgetSnapshot:
    iterations_used: int
    max_iterations: int
    experiments_used: int
    max_experiments: int
    cost_usd_used: float
    max_cost_usd: float
    compute_seconds_used: float
    max_compute_seconds: float
    llm_tokens_used: int
    max_llm_tokens: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StopDecision:
    should_stop: bool
    reason: Optional[str] = None


class BudgetTracker:
    """Atomic budget accounting that guarantees configured limits cannot be exceeded."""

    def __init__(self, budget: BudgetSpec, stop_conditions: StopConditionsSpec) -> None:
        budget.validate()
        stop_conditions.validate()
        self._budget = budget
        self._stop = stop_conditions

        self._iterations_used = 0
        self._experiments_used = 0
        self._cost_usd_used = 0.0
        self._compute_seconds_used = 0.0
        self._llm_tokens_used = 0

        self._consecutive_failures = 0
        self._best_sharpe: Optional[float] = None
        self._rounds_without_improvement = 0

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            iterations_used=self._iterations_used,
            max_iterations=self._budget.max_iterations,
            experiments_used=self._experiments_used,
            max_experiments=self._budget.max_experiments,
            cost_usd_used=round(self._cost_usd_used, 6),
            max_cost_usd=self._budget.max_cost_usd,
            compute_seconds_used=round(self._compute_seconds_used, 6),
            max_compute_seconds=self._budget.max_compute_seconds,
            llm_tokens_used=self._llm_tokens_used,
            max_llm_tokens=self._budget.max_llm_tokens,
        )

    def reserve_iteration(self) -> int:
        if self._iterations_used + 1 > self._budget.max_iterations:
            raise BudgetExhaustedError(
                f"Iteration budget exhausted ({self._iterations_used}/{self._budget.max_iterations})",
                self.snapshot().to_dict(),
            )
        self._iterations_used += 1
        return self._iterations_used

    def reserve_experiment(self, estimated_cost_usd: Optional[float] = None) -> None:
        cost = self._budget.cost_per_experiment_usd if estimated_cost_usd is None else estimated_cost_usd
        if self._experiments_used + 1 > self._budget.max_experiments:
            raise BudgetExhaustedError(
                f"Experiment budget exhausted ({self._experiments_used}/{self._budget.max_experiments})",
                self.snapshot().to_dict(),
            )
        if self._cost_usd_used + cost > self._budget.max_cost_usd + 1e-12:
            raise BudgetExhaustedError(
                f"Cost budget would be exceeded: used={self._cost_usd_used:.4f} + next={cost:.4f} > max={self._budget.max_cost_usd:.4f} USD",
                self.snapshot().to_dict(),
            )
        if self._compute_seconds_used >= self._budget.max_compute_seconds:
            raise BudgetExhaustedError(
                f"Compute budget exhausted ({self._compute_seconds_used:.2f}s/{self._budget.max_compute_seconds:.2f}s)",
                self.snapshot().to_dict(),
            )
        self._experiments_used += 1
        self._cost_usd_used += cost

    def record_compute_and_tokens(self, compute_seconds: float, llm_tokens: int = 0) -> None:
        if self._llm_tokens_used + llm_tokens > self._budget.max_llm_tokens:
            raise BudgetExhaustedError(
                f"LLM token budget would be exceeded ({self._llm_tokens_used + llm_tokens}/{self._budget.max_llm_tokens})",
                self.snapshot().to_dict(),
            )
        self._compute_seconds_used += max(0.0, compute_seconds)
        self._llm_tokens_used += max(0, llm_tokens)

    def record_outcome(self, succeeded: bool, validation_sharpe: Optional[float] = None) -> None:
        if not succeeded:
            self._consecutive_failures += 1
            return
        self._consecutive_failures = 0
        if validation_sharpe is not None:
            if self._best_sharpe is None:
                self._best_sharpe = validation_sharpe
                self._rounds_without_improvement = 0
            elif validation_sharpe >= self._best_sharpe + self._stop.min_improvement_sharpe:
                self._best_sharpe = validation_sharpe
                self._rounds_without_improvement = 0
            else:
                self._rounds_without_improvement += 1

    def check_stop_conditions(self) -> StopDecision:
        if self._iterations_used >= self._budget.max_iterations:
            return StopDecision(True, "BUDGET_MAX_ITERATIONS_REACHED")
        if self._experiments_used >= self._budget.max_experiments:
            return StopDecision(True, "BUDGET_MAX_EXPERIMENTS_REACHED")
        if self._cost_usd_used + self._budget.cost_per_experiment_usd > self._budget.max_cost_usd + 1e-12:
            return StopDecision(True, "BUDGET_MAX_COST_REACHED")
        if self._compute_seconds_used >= self._budget.max_compute_seconds:
            return StopDecision(True, "BUDGET_MAX_COMPUTE_REACHED")
        if self._consecutive_failures >= self._stop.max_consecutive_failures:
            return StopDecision(True, "STOP_MAX_CONSECUTIVE_FAILURES")
        if self._rounds_without_improvement >= self._stop.patience_rounds:
            return StopDecision(True, "STOP_PATIENCE_PLATEAU")
        return StopDecision(False, None)
