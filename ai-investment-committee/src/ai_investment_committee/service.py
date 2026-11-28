"""High-level typed service interface with SQLite storage, structured logs, and counters."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .agents import LLMAdapter
from .errors import CommitteeError, MissingConfigurationError
from .models import (
    CommitteeConfig,
    CommitteeProposal,
    DeliberationReplayTrace,
    EvaluationMetrics,
    HumanApprovalRecord,
)
from .replay import evaluate_deliberation, replay_deliberation
from .state_machine import apply_human_approval, run_deliberation
from .storage import DeliberationStore

logger = logging.getLogger("ai_investment_committee")


def load_json_file(path: Union[str, Path], *, label: str) -> Dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise MissingConfigurationError(
            f"Required {label} file not found: {file_path}",
            details={"path": str(file_path), "label": label},
        )
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MissingConfigurationError(
            f"Invalid JSON in {label} file '{file_path}': {exc}",
            details={"path": str(file_path), "label": label},
        ) from exc
    if not isinstance(data, dict):
        raise MissingConfigurationError(
            f"Expected JSON object in {label} file '{file_path}'",
            details={"path": str(file_path), "label": label},
        )
    return data


class InvestmentCommitteeService:
    """Typed service facade coordinating deliberation, risk veto, human approval, and replay."""

    def __init__(
        self,
        *,
        config: CommitteeConfig,
        store: DeliberationStore,
        adapter: Optional[LLMAdapter] = None,
    ) -> None:
        self.config = config
        self.store = store
        self.adapter = adapter
        self.counters: Dict[str, int] = {
            "deliberations_run": 0,
            "risk_vetoes": 0,
            "risk_passes": 0,
            "human_approvals_recorded": 0,
            "human_rejections_recorded": 0,
            "replays_executed": 0,
            "errors_raised": 0,
            "prompt_injections_flagged": 0,
            "fabricated_citations_caught": 0,
        }

    @classmethod
    def from_config_path(
        cls,
        *,
        config_path: Union[str, Path],
        db_path: Union[str, Path],
        adapter: Optional[LLMAdapter] = None,
    ) -> "InvestmentCommitteeService":
        raw_cfg = load_json_file(config_path, label="committee configuration")
        config = CommitteeConfig.model_validate(raw_cfg)
        store = DeliberationStore(db_path)
        return cls(config=config, store=store, adapter=adapter)

    def deliberate(
        self,
        proposal_input: Union[CommitteeProposal, Dict[str, Any]],
        *,
        simulated_role_delay_ms: Optional[Dict[str, int]] = None,
        created_at_override: Optional[str] = None,
    ) -> DeliberationReplayTrace:
        try:
            proposal = (
                proposal_input
                if isinstance(proposal_input, CommitteeProposal)
                else CommitteeProposal.model_validate(proposal_input)
            )
            trace = run_deliberation(
                proposal=proposal,
                config=self.config,
                adapter=self.adapter,
                simulated_role_delay_ms=simulated_role_delay_ms,
                created_at_override=created_at_override,
            )
            self.store.save_deliberation(
                trace=trace,
                proposal_dict=proposal.model_dump(),
                config_dict=self.config.model_dump(),
            )
            metrics = evaluate_deliberation(trace)
            self.store.save_evaluation(
                decision_id=trace.decision_id,
                evaluated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                metrics=metrics.model_dump(),
            )
            self.counters["deliberations_run"] += 1
            if trace.decision.risk_verdict.verdict == "VETO":
                self.counters["risk_vetoes"] += 1
            else:
                self.counters["risk_passes"] += 1
            self.counters["prompt_injections_flagged"] += metrics.prompt_injection_attempts_detected
            self.counters["fabricated_citations_caught"] += metrics.fabricated_citations

            logger.info(
                json.dumps(
                    {
                        "event": "deliberation_completed",
                        "decision_id": trace.decision_id,
                        "proposal_id": trace.proposal_id,
                        "proposal_hash": trace.proposal_hash,
                        "verdict": trace.decision.risk_verdict.verdict,
                        "status": trace.decision.status,
                        "total_cost_usd": trace.total_cost_usd,
                    },
                    sort_keys=True,
                )
            )
            return trace
        except CommitteeError:
            self.counters["errors_raised"] += 1
            raise

    def submit_human_approval(
        self,
        *,
        decision_id: str,
        approval_input: Union[HumanApprovalRecord, Dict[str, Any]],
    ) -> DeliberationReplayTrace:
        try:
            approval = (
                approval_input
                if isinstance(approval_input, HumanApprovalRecord)
                else HumanApprovalRecord.model_validate(approval_input)
            )
            found = self.store.get_deliberation(decision_id)
            if found is None:
                raise MissingConfigurationError(
                    f"Deliberation '{decision_id}' not found in SQLite store.",
                    details={"decision_id": decision_id},
                )
            trace, _, _ = found
            seen_ids = self.store.seen_approval_ids()
            updated_decision = apply_human_approval(
                decision=trace.decision,
                approval=approval,
                seen_approval_ids=seen_ids,
            )
            updated_trace = replace(trace, decision=updated_decision)
            self.store.record_human_approval(updated_trace=updated_trace, approval=approval)

            if updated_decision.status == "APPROVED_FOR_PAPER_ONLY":
                self.counters["human_approvals_recorded"] += 1
            else:
                self.counters["human_rejections_recorded"] += 1

            logger.info(
                json.dumps(
                    {
                        "event": "human_approval_recorded",
                        "decision_id": decision_id,
                        "approval_id": approval.approval_id,
                        "status": updated_decision.status,
                    },
                    sort_keys=True,
                )
            )
            return updated_trace
        except CommitteeError:
            self.counters["errors_raised"] += 1
            raise

    def replay(self, decision_id: str) -> Dict[str, Any]:
        found = self.store.get_deliberation(decision_id)
        if found is None:
            self.counters["errors_raised"] += 1
            raise MissingConfigurationError(
                f"Cannot replay missing deliberation '{decision_id}'.",
                details={"decision_id": decision_id},
            )
        trace, proposal_dict, config_dict = found
        result = replay_deliberation(
            recorded_trace=trace,
            proposal_dict=proposal_dict,
            config_dict=config_dict,
            adapter=self.adapter,
        )
        self.counters["replays_executed"] += 1
        return result

    def evaluate(self, decision_id: str) -> EvaluationMetrics:
        found = self.store.get_deliberation(decision_id)
        if found is None:
            self.counters["errors_raised"] += 1
            raise MissingConfigurationError(
                f"Cannot evaluate missing deliberation '{decision_id}'.",
                details={"decision_id": decision_id},
            )
        trace, _, _ = found
        return evaluate_deliberation(trace)
