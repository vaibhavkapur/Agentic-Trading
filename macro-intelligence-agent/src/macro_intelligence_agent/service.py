"""Typed service facade orchestrating archive, guardrails, domain logic, verification, and replay."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import platform
from typing import Any, Dict, List, Optional, Tuple, Union

from .archive import ReleaseArchive
from .briefs import DeterministicMockSummarizer, SummarizerAdapter, build_scenario_brief
from .config import AgentConfig
from .extractor import extract_figures_from_release, extract_policy_language
from .models import (
    AbstentionRecord,
    AgentRunResult,
    ExtractedFigure,
    PolicyLanguageSignal,
    RunMetadata,
    UntrustedInstructionFinding,
    canonical_json,
    format_utc_timestamp,
    parse_utc_timestamp,
    sha256_text,
    stable_id,
)
from .revisions import reconcile_figures_and_surprises
from .security import sanitize_untrusted_release_text
from .telemetry import TelemetryCollector
from .verification import verify_brief


class MacroIntelligenceService:
    """High-level typed service for generating verified, revision-aware macro briefs."""

    def __init__(
        self,
        archive: ReleaseArchive,
        config: Optional[AgentConfig] = None,
        summarizer: Optional[SummarizerAdapter] = None,
    ) -> None:
        self.archive = archive
        self.config = config or AgentConfig()
        self._custom_summarizer = summarizer

    def _make_summarizer(self) -> SummarizerAdapter:
        if self._custom_summarizer is not None:
            return self._custom_summarizer
        return DeterministicMockSummarizer(
            max_calls=self.config.model_adapter.max_calls_per_run,
            max_output_tokens=self.config.model_adapter.max_output_tokens,
            seed=self.config.seed,
        )

    def generate_brief(
        self,
        *,
        series_group: str,
        as_of_utc: Union[datetime, str],
        persist_run: bool = True,
    ) -> AgentRunResult:
        """Execute an end-to-end, publication-gated, verified macro intelligence run."""
        cutoff = parse_utc_timestamp(as_of_utc, "as_of_utc")
        telemetry = TelemetryCollector()
        telemetry.record(
            "run_started",
            series_group=series_group,
            as_of_utc=format_utc_timestamp(cutoff),
            config_sha256=self.config.config_sha256,
        )

        visible_releases = self.archive.query_releases_as_of(
            cutoff, series_group=series_group
        )
        gated_out = self.archive.count_gated_out_releases(
            cutoff, series_group=series_group
        )
        visible_consensus = self.archive.query_consensus_as_of(cutoff)

        telemetry.increment("releases_visible", len(visible_releases))
        telemetry.increment("releases_gated_out", gated_out)
        telemetry.increment("consensus_visible", len(visible_consensus))
        telemetry.record(
            "publication_gate_applied",
            visible_count=len(visible_releases),
            gated_out_count=gated_out,
        )

        # Deterministic input hash based strictly on visible inputs at cutoff
        input_fingerprint = sha256_text(
            canonical_json(
                {
                    "series_group": series_group,
                    "as_of_utc": format_utc_timestamp(cutoff),
                    "releases": [
                        (r.release_id, r.vintage_id, r.document_sha256)
                        for r in visible_releases
                    ],
                    "consensus": [c.to_dict() for c in visible_consensus],
                }
            )
        )

        all_figures: List[ExtractedFigure] = []
        all_policy_signals: List[PolicyLanguageSignal] = []
        all_security_findings: List[UntrustedInstructionFinding] = []

        for release in visible_releases:
            sanitized_text, sec_findings = sanitize_untrusted_release_text(
                release,
                mode=self.config.strict_untrusted_instruction_mode,
            )
            if sec_findings:
                all_security_findings.extend(sec_findings)
                telemetry.increment("security_findings", len(sec_findings))
                telemetry.record(
                    "untrusted_source_instructions_detected",
                    level="WARNING",
                    release_id=release.release_id,
                    vintage_id=release.vintage_id,
                    count=len(sec_findings),
                    action=self.config.strict_untrusted_instruction_mode,
                )

            figs = extract_figures_from_release(release, sanitized_text)
            all_figures.extend(figs)
            telemetry.increment("figures_extracted_raw", len(figs))

            signals = extract_policy_language(release, sanitized_text)
            all_policy_signals.extend(signals)
            telemetry.increment("policy_signals_extracted", len(signals))

        reconciled = reconcile_figures_and_surprises(
            releases=visible_releases,
            extracted_figures=all_figures,
            consensus_estimates=visible_consensus,
            config=self.config,
        )

        abstentions: List[AbstentionRecord] = list(reconciled.abstentions)
        if not visible_releases:
            abstentions.append(
                AbstentionRecord(
                    abstention_id=stable_id(
                        "abs",
                        {
                            "scope": f"series_group:{series_group}",
                            "as_of_utc": format_utc_timestamp(cutoff),
                            "reason": "NO_PUBLISHED_RELEASES",
                        },
                    ),
                    scope=f"series_group:{series_group}",
                    reason_code="NO_PUBLISHED_RELEASES",
                    explanation=(
                        f"No releases for '{series_group}' were published or past embargo "
                        f"as of {format_utc_timestamp(cutoff)}."
                    ),
                )
            )

        telemetry.increment("figures_canonical", len(reconciled.latest_figures))
        telemetry.increment("surprises_computed", len(reconciled.surprises))
        telemetry.increment("revisions_computed", len(reconciled.revisions))
        telemetry.increment("conflicts_detected", len(reconciled.conflicts))
        telemetry.increment("abstentions_recorded", len(abstentions))

        summarizer = self._make_summarizer()
        brief = build_scenario_brief(
            as_of_utc=cutoff,
            series_group=series_group,
            figures=reconciled.latest_figures,
            surprises=reconciled.surprises,
            revisions=reconciled.revisions,
            policy_signals=all_policy_signals,
            conflicts=reconciled.conflicts,
            abstentions=abstentions,
            security_findings=all_security_findings,
            config=self.config,
            summarizer=summarizer,
        )

        # Deterministic post-generation citation & policy verification gate
        verified = verify_brief(brief, visible_releases, cutoff)
        brief = replace(brief, verification_passed=verified)
        telemetry.increment("verification_passed", 1 if verified else 0)
        telemetry.record("verification_completed", passed=verified, brief_id=brief.brief_id)

        run_id = stable_id(
            "run",
            {
                "series_group": series_group,
                "as_of_utc": format_utc_timestamp(cutoff),
                "config_sha256": self.config.config_sha256,
                "input_sha256": input_fingerprint,
                "seed": self.config.seed,
            },
        )

        metadata = RunMetadata(
            run_id=run_id,
            schema_version=self.config.schema_version,
            config_version=self.config.config_version,
            config_sha256=self.config.config_sha256,
            input_sha256=input_fingerprint,
            seed=self.config.seed,
            as_of_utc=cutoff,
            python_version=platform.python_version(),
            model_provider=self.config.model_adapter.provider,
            model_calls_used=summarizer.calls_used,
        )

        result = AgentRunResult(
            metadata=metadata,
            brief=brief,
            diagnostics=telemetry.snapshot(),
        )

        if persist_run and self.config.storage.enable_run_replay_log:
            self.archive.save_run_result(result)

        return result

    def replay_run(self, run_id: str) -> Tuple[bool, Dict[str, Any]]:
        """Re-execute a stored run_id against the archive and verify exact logical reproducibility."""
        stored = self.archive.load_run_result(run_id)
        if stored is None:
            return False, {"error": f"Run ID not found in replay log: {run_id}"}
        as_of_utc = stored["metadata"]["as_of_utc"]
        series_group = stored["brief"]["series_group"]
        replayed = self.generate_brief(
            series_group=series_group,
            as_of_utc=as_of_utc,
            persist_run=False,
        )
        replayed_dict = replayed.to_dict()
        matches = canonical_json(stored["brief"]) == canonical_json(replayed_dict["brief"]) and (
            stored["metadata"]["run_id"] == replayed_dict["metadata"]["run_id"]
        )
        return matches, {
            "run_id": run_id,
            "replayed_run_id": replayed_dict["metadata"]["run_id"],
            "logical_match": matches,
            "stored_brief_id": stored["brief"]["brief_id"],
            "replayed_brief_id": replayed_dict["brief"]["brief_id"],
        }
