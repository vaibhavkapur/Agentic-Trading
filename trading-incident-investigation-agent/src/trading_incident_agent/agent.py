"""Orchestrator for read-only incident investigation, report rendering, and approval-gated remediation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from trading_incident_agent.config import build_runtime_metadata, compute_sha256, validate_incident_bundle
from trading_incident_agent.errors import BudgetExceededError
from trading_incident_agent.hypotheses import evaluate_hypotheses
from trading_incident_agent.llm_adapter import (
    NarrativeAdvisor,
    OfflineTemplateAdvisor,
    build_sanitized_advisor_prompt,
)
from trading_incident_agent.models import (
    AgentConfig,
    DiagnosticLogEntry,
    IncidentBundle,
    IncidentReport,
    OperatorApproval,
    RemediationProposal,
    RemediationReceipt,
    VerdictStatus,
)
from trading_incident_agent.remediation import SimulatedTradingEnvironment, propose_remediations
from trading_incident_agent.runbooks import retrieve_runbooks
from trading_incident_agent.timeline import build_incident_timeline


class TradingIncidentAgent:
    """Deterministic, read-only-by-default trading incident investigation agent."""

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        advisor: Optional[NarrativeAdvisor] = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.advisor: NarrativeAdvisor = advisor or OfflineTemplateAdvisor()

    def investigate(self, bundle_input: IncidentBundle | dict[str, Any]) -> IncidentReport:
        """Run a strictly read-only, reproducible investigation on a synthetic incident bundle."""
        bundle = validate_incident_bundle(bundle_input)
        runtime_meta = build_runtime_metadata(self.config, bundle)

        step = 0
        tool_calls = 0
        diag_log: list[DiagnosticLogEntry] = []

        def record_step(component: str, event: str, details: dict[str, Any], *, is_tool: bool = True) -> None:
            nonlocal step, tool_calls
            step += 1
            if step > self.config.budgets.max_steps:
                raise BudgetExceededError(
                    f"Investigation step budget exceeded (max_steps={self.config.budgets.max_steps})"
                )
            if is_tool:
                tool_calls += 1
                if tool_calls > self.config.budgets.max_tool_calls:
                    raise BudgetExceededError(
                        f"Investigation tool-call budget exceeded (max_tool_calls={self.config.budgets.max_tool_calls})"
                    )
            diag_log.append(
                DiagnosticLogEntry(step=step, component=component, event=event, details=details)
            )

        # Step 1: Normalize timeline & sanitize untrusted telemetry
        timeline, security_findings = build_incident_timeline(bundle)
        injection_count = sum(1 for f in security_findings if f.category == "prompt_injection")
        redaction_count = sum(1 for f in security_findings if f.category == "secret_redaction")
        record_step(
            "timeline",
            "normalized_timeline",
            {
                "event_count": timeline.event_count,
                "anomalous_events": timeline.anomalous_event_count,
                "trace_gaps": len(timeline.trace_gaps),
                "prompt_injections_quarantined": injection_count,
                "secrets_redacted": redaction_count,
            },
        )

        # Step 2: Retrieve relevant runbooks
        retrieved_runbooks = retrieve_runbooks(
            bundle,
            timeline,
            max_results=self.config.max_retrieved_runbooks,
        )
        record_step(
            "runbooks",
            "retrieved_runbooks",
            {
                "count": len(retrieved_runbooks),
                "top_runbooks": [r.runbook_id for r in retrieved_runbooks],
            },
        )

        # Step 3: Test candidate hypotheses deterministically
        verdict_status, primary, hypotheses, uncertainty_notes = evaluate_hypotheses(
            bundle, timeline, retrieved_runbooks, self.config
        )
        if injection_count > 0:
            uncertainty_notes.append(
                f"Detected and quarantined {injection_count} prompt-injection attempt(s) inside "
                "untrusted telemetry; policy and verdict remained isolated from injected text."
            )
        record_step(
            "hypotheses",
            "evaluated_hypotheses",
            {
                "verdict": verdict_status.value,
                "hypothesis_count": len(hypotheses),
                "primary": primary.failure_mode if primary else None,
                "top_confidence": hypotheses[0].confidence if hypotheses else 0.0,
            },
        )

        # Step 4: Draft approval-gated remediation proposals (never executed automatically)
        runbook_actions = {rb.runbook_id: rb.recommended_actions for rb in bundle.runbooks}
        proposals = propose_remediations(
            incident_id=bundle.incident_id,
            verdict_status=verdict_status,
            primary=primary,
            hypotheses=hypotheses,
            runbook_actions_by_id=runbook_actions,
        )
        record_step(
            "remediation_planner",
            "proposed_remediations",
            {
                "proposal_count": len(proposals),
                "auto_executed": False,
                "actions": [p.action_id for p in proposals],
            },
        )

        # Step 5: Generate narrative summary behind strict untrusted-data boundary
        advisor_prompt = build_sanitized_advisor_prompt(
            incident_id=bundle.incident_id,
            incident_title=bundle.title,
            verdict_status=verdict_status,
            primary=primary,
            hypotheses=hypotheses,
            uncertainty_notes=uncertainty_notes,
            timeline=timeline,
            proposals=proposals,
            security_findings=security_findings,
            max_prompt_chars=self.config.budgets.max_prompt_chars,
        )
        narrative_summary = self.advisor.summarize(advisor_prompt, max_chars=1200)
        record_step(
            "advisor",
            "generated_narrative",
            {
                "advisor_mode": self.config.advisor_mode,
                "prompt_chars": len(advisor_prompt),
                "summary_chars": len(narrative_summary),
            },
        )

        top_confidence = (
            primary.confidence
            if primary is not None
            else (hypotheses[0].confidence if hypotheses else 0.0)
        )

        report_id = (
            f"RPT-{bundle.incident_id}-"
            f"{compute_sha256({'input': runtime_meta.input_digest, 'cfg': runtime_meta.config_digest})[:12]}"
        )

        counters = {
            "steps_executed": step,
            "tool_calls_executed": tool_calls,
            "timeline_events": timeline.event_count,
            "anomalous_events": timeline.anomalous_event_count,
            "trace_gaps": len(timeline.trace_gaps),
            "runbooks_retrieved": len(retrieved_runbooks),
            "hypotheses_evaluated": len(hypotheses),
            "proposals_generated": len(proposals),
            "prompt_injections_quarantined": injection_count,
            "secrets_redacted": redaction_count,
            "operational_changes_applied": 0,
        }

        return IncidentReport(
            report_id=report_id,
            schema_version=bundle.schema_version,
            incident_id=bundle.incident_id,
            incident_title=bundle.title,
            verdict_status=verdict_status,
            primary_root_cause=primary,
            hypotheses=hypotheses,
            confidence=top_confidence,
            uncertainty_notes=uncertainty_notes,
            timeline=timeline,
            retrieved_runbooks=retrieved_runbooks,
            proposed_remediations=proposals,
            security_findings=security_findings,
            narrative_summary=narrative_summary,
            read_only_enforced=True,
            operational_changes_applied=0,
            diagnostics_counters=counters,
            diagnostic_log=diag_log,
            runtime_metadata=runtime_meta,
        )

    def execute_remediation(
        self,
        *,
        report: IncidentReport,
        proposal: RemediationProposal,
        approval: Optional[OperatorApproval],
        environment: Optional[SimulatedTradingEnvironment] = None,
        now_utc: Optional[datetime] = None,
    ) -> RemediationReceipt:
        """Execute an approved simulated remediation and verify deterministic recovery."""
        env = environment or SimulatedTradingEnvironment(seed=self.config.seed)
        return env.execute_and_verify(
            report=report,
            proposal=proposal,
            approval=approval,
            config=self.config,
            now_utc=now_utc,
        )


def render_report_markdown(report: IncidentReport) -> str:
    """Render a human-readable cited incident report in Markdown."""
    lines = [
        f"# Incident Investigation Report: {report.incident_id}",
        "",
        f"- **Report ID:** `{report.report_id}`",
        f"- **Title:** {report.incident_title}",
        f"- **Verdict:** `{report.verdict_status.value}`",
        f"- **Top Confidence:** `{report.confidence:.4f}`",
        f"- **Read-Only Enforced:** `{report.read_only_enforced}` (Operational changes applied: `{report.operational_changes_applied}`)",
        f"- **Input Digest:** `{report.runtime_metadata.input_digest[:16]}` | **Config Digest:** `{report.runtime_metadata.config_digest[:16]}`",
        "",
        "## Executive Summary",
        "",
        report.narrative_summary,
        "",
        "## Root-Cause Hypotheses",
        "",
    ]

    for hyp in report.hypotheses:
        marker = " (PRIMARY)" if report.primary_root_cause and hyp.hypothesis_id == report.primary_root_cause.hypothesis_id else ""
        lines.append(f"### {hyp.hypothesis_id}{marker}: {hyp.title}")
        lines.append(
            f"- **Failure Mode:** `{hyp.failure_mode}` | **Service:** `{hyp.service}` | "
            f"**Confidence:** `{hyp.confidence:.4f}` | **Modalities:** `{', '.join(hyp.modalities_supporting)}`"
        )
        lines.append("- **Supporting Evidence:**")
        for ev in hyp.supporting_evidence:
            lines.append(
                f"  - `{ev.evidence_id}` (`{ev.source_type.value}`, weight={ev.weight:.2f}): {ev.summary} — _{ev.rationale}_"
            )
        if hyp.counterevidence:
            lines.append("- **Counterevidence:**")
            for ce in hyp.counterevidence:
                lines.append(
                    f"  - `{ce.evidence_id}` (`{ce.source_type.value}`, penalty={ce.weight:.2f}): {ce.summary} — _{ce.rationale}_"
                )
        if hyp.uncertainty_factors:
            lines.append("- **Uncertainty Factors:**")
            for u in hyp.uncertainty_factors:
                lines.append(f"  - {u}")
        if hyp.discriminating_checks:
            lines.append("- **Recommended Diagnostic Checks:**")
            for chk in hyp.discriminating_checks:
                lines.append(f"  - {chk}")
        lines.append("")

    if report.uncertainty_notes:
        lines.append("## Surfaced Uncertainty & Caveats")
        lines.append("")
        for note in report.uncertainty_notes:
            lines.append(f"- {note}")
        lines.append("")

    if report.timeline.trace_gaps:
        lines.append("## Distributed Trace Gaps")
        lines.append("")
        for gap in report.timeline.trace_gaps:
            lines.append(f"- `{gap.gap_type}` in trace `{gap.trace_id}`: {gap.description}")
        lines.append("")

    if report.security_findings:
        lines.append("## Security & Sanitization Findings")
        lines.append("")
        for f in report.security_findings:
            lines.append(
                f"- `{f.finding_id}` (`{f.category}` on `{f.source_id}`): pattern `{f.pattern_name}` — {f.action_taken}"
            )
        lines.append("")

    lines.append("## Normalized Incident Timeline (UTC)")
    lines.append("")
    lines.append("| Evidence ID | Timestamp (UTC) | Source | Service | Severity | Anomalous | Summary |")
    lines.append("|---|---|---|---|---|---|---|")
    for ev in report.timeline.events:
        safe_summary = ev.summary.replace("|", "\\|")
        lines.append(
            f"| `{ev.evidence_id}` | `{ev.timestamp_utc.isoformat()}` | `{ev.source_type.value}` | "
            f"`{ev.service}` | `{ev.severity.value}` | `{ev.is_anomalous}` | {safe_summary} |"
        )
    lines.append("")

    lines.append("## Proposed Simulated Remediations (Explicit Approval Required)")
    lines.append("")
    if not report.proposed_remediations:
        lines.append("_No automated or simulated remediation proposed._")
    else:
        for prop in report.proposed_remediations:
            lines.append(
                f"- `{prop.remediation_id}`: action=`{prop.action_id}`, target=`{prop.target_service}`, "
                f"risk=`{prop.risk_level.value}`, plan_digest=`{prop.plan_digest[:16]}...`, auto_executed=`{prop.auto_executed}`"
            )
            if prop.blocked_reason:
                lines.append(f"  - **Gate:** {prop.blocked_reason}")
    lines.append("")
    return "\n".join(lines)
