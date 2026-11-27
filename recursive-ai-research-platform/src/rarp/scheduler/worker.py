"""Idempotent experiment worker with checkpointed crash recovery and replay deduplication."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from rarp.data.fixtures import MarketBar
from rarp.domain.dsl import ExperimentSpec
from rarp.domain.errors import LeakageError, WorkerCrashError
from rarp.domain.types import RunStatus, utc_now_iso
from rarp.registry.store import RunRecord, RunRegistry
from rarp.scheduler.backtester import BacktesterAdapter, BacktestResult
from rarp.scheduler.budget import BudgetTracker


@dataclass(frozen=True)
class WorkerExecutionResult:
    run_record: RunRecord
    replayed_from_registry: bool
    attempts: int
    backtest_result: Optional[BacktestResult] = None


class ExperimentWorker:
    """Executes bounded experiments idempotently with deterministic crash/retry semantics."""

    def __init__(
        self,
        backtester: BacktesterAdapter,
        registry: RunRegistry,
        budget: BudgetTracker,
        max_retries: int = 2,
        fault_injector: Optional[Callable[[ExperimentSpec, int], None]] = None,
    ) -> None:
        self._backtester = backtester
        self._registry = registry
        self._budget = budget
        self._max_retries = max_retries
        self._fault_injector = fault_injector

    def execute(
        self,
        spec: ExperimentSpec,
        train_bars: Dict[str, List[MarketBar]],
        validation_bars: Dict[str, List[MarketBar]],
        split_sha256: str,
        charge_budget: bool = True,
    ) -> WorkerExecutionResult:
        """Execute an experiment idempotently.

        If an identical idempotency key has already SUCCEEDED in the immutable registry,
        returns the persisted RunRecord directly without re-charging experiment budget.
        If a worker crash occurs mid-flight, checkpoints the attempt and retries up to
        max_retries times while preserving a single finalized RunRecord.
        """
        idem_key = spec.idempotency_key()
        existing = self._registry.find_succeeded_by_idempotency_key(idem_key)
        if existing is not None:
            self._registry.record_audit_event(
                event_type="WORKER_IDEMPOTENT_REPLAY",
                actor_id="experiment_worker",
                details={"idempotency_key": idem_key, "run_id": existing.run_id},
            )
            return WorkerExecutionResult(
                run_record=existing,
                replayed_from_registry=True,
                attempts=existing.attempts,
                backtest_result=None,
            )

        # Charge budget once per logical experiment (not per retry).
        if charge_budget:
            self._budget.reserve_experiment()

        attempt = 0
        last_error: Optional[Exception] = None
        started_at = utc_now_iso()
        wall_start = time.monotonic()

        while attempt <= self._max_retries:
            attempt += 1
            self._registry.record_audit_event(
                event_type="WORKER_ATTEMPT_STARTED",
                actor_id="experiment_worker",
                details={
                    "experiment_id": spec.experiment_id,
                    "idempotency_key": idem_key,
                    "attempt": attempt,
                },
            )
            try:
                if self._fault_injector is not None:
                    self._fault_injector(spec, attempt)

                bt_result = self._backtester.evaluate(spec, train_bars, validation_bars)
                elapsed = time.monotonic() - wall_start
                self._budget.record_compute_and_tokens(compute_seconds=elapsed, llm_tokens=0)

                artifact_payload = {
                    "experiment_spec": spec.to_dict(),
                    "split_sha256": split_sha256,
                    "backtest": bt_result.to_dict(),
                }
                artifact_uri, artifact_sha256 = self._registry.put_artifact(
                    f"runs/{spec.experiment_id}_backtest.json", artifact_payload
                )

                run_record = self._registry.record_run(
                    spec=spec,
                    status=RunStatus.SUCCEEDED,
                    metrics=bt_result.flat_metrics,
                    artifact_uri=artifact_uri,
                    artifact_sha256=artifact_sha256,
                    split_sha256=split_sha256,
                    attempts=attempt,
                    started_at_utc=started_at,
                    completed_at_utc=utc_now_iso(),
                    error_code=None,
                    error_message=None,
                )
                self._budget.record_outcome(
                    succeeded=True,
                    validation_sharpe=bt_result.validation_metrics.sharpe,
                )
                return WorkerExecutionResult(
                    run_record=run_record,
                    replayed_from_registry=False,
                    attempts=attempt,
                    backtest_result=bt_result,
                )
            except WorkerCrashError as exc:
                last_error = exc
                self._registry.record_audit_event(
                    event_type="WORKER_CRASH_CHECKPOINTED",
                    actor_id="experiment_worker",
                    details={
                        "experiment_id": spec.experiment_id,
                        "idempotency_key": idem_key,
                        "attempt": attempt,
                        "error": exc.to_dict(),
                        "will_retry": attempt <= self._max_retries,
                    },
                )
                if attempt > self._max_retries:
                    break
            except LeakageError as exc:
                # Leakage errors are deterministic policy failures — never retry.
                elapsed = time.monotonic() - wall_start
                self._budget.record_compute_and_tokens(compute_seconds=elapsed, llm_tokens=0)
                run_record = self._registry.record_run(
                    spec=spec,
                    status=RunStatus.REJECTED,
                    metrics={},
                    artifact_uri="",
                    artifact_sha256="",
                    split_sha256=split_sha256,
                    attempts=attempt,
                    started_at_utc=started_at,
                    completed_at_utc=utc_now_iso(),
                    error_code=exc.code,
                    error_message=exc.message,
                )
                self._budget.record_outcome(succeeded=False)
                raise exc
            except Exception as exc:
                last_error = exc
                break

        # Finalize failed run in immutable registry so failed attempts are preserved.
        elapsed = time.monotonic() - wall_start
        self._budget.record_compute_and_tokens(compute_seconds=elapsed, llm_tokens=0)
        err_code = getattr(last_error, "code", "EXECUTION_ERROR")
        err_msg = str(last_error) if last_error else "Unknown worker failure"
        run_record = self._registry.record_run(
            spec=spec,
            status=RunStatus.FAILED,
            metrics={},
            artifact_uri="",
            artifact_sha256="",
            split_sha256=split_sha256,
            attempts=attempt,
            started_at_utc=started_at,
            completed_at_utc=utc_now_iso(),
            error_code=err_code,
            error_message=err_msg,
        )
        self._budget.record_outcome(succeeded=False)
        return WorkerExecutionResult(
            run_record=run_record,
            replayed_from_registry=False,
            attempts=attempt,
            backtest_result=None,
        )
