#!/usr/bin/env python3
"""Reproducible end-to-end demo script for the Earnings Call Intelligence Agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from earnings_call_agent.adapters import export_research_note_envelope
from earnings_call_agent.contracts import AgentConfig
from earnings_call_agent.ingestion import load_transcript_file
from earnings_call_agent.pipeline import analyze_transcript, replay_and_verify, report_logical_digest


def main() -> int:
    config = AgentConfig.from_file(str(PROJECT_ROOT / "config" / "default.json"))
    fixtures = PROJECT_ROOT / "data" / "fixtures"
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    as_of = "2026-02-15T12:00:00Z"

    # 1. Reference baseline demo
    ref_raw = load_transcript_file(str(fixtures / "reference_valid.json"))
    ref_report = analyze_transcript(ref_raw, config, as_of_timestamp=as_of)
    ref_digest = report_logical_digest(ref_report)
    replay_check = replay_and_verify(
        ref_raw, config, expected_digest=ref_digest, as_of_timestamp=as_of
    )
    if not replay_check["reproducible_match"]:
        raise RuntimeError("Replay verification failed on reference fixture!")

    baseline_path = reports_dir / "baseline_reference.json"
    baseline_path.write_text(json.dumps(ref_report.to_dict(), indent=2) + "\n", encoding="utf-8")

    # 2. Prompt injection integration scenario report
    inj_raw = load_transcript_file(str(fixtures / "prompt_injection.json"))
    inj_report = analyze_transcript(inj_raw, config, as_of_timestamp=as_of)
    inj_path = reports_dir / "integration_prompt_injection.json"
    inj_path.write_text(json.dumps(inj_report.to_dict(), indent=2) + "\n", encoding="utf-8")

    # 3. Consolidated demo output with research-note adapter envelope
    demo_payload = {
        "demo_version": "1.0.0",
        "as_of_timestamp": as_of,
        "data_provenance": "synthetic_educational_fixtures",
        "reference_run_id": ref_report.run_id,
        "reference_logical_digest": ref_digest,
        "replay_reproducible_match": replay_check["reproducible_match"],
        "reference_research_note": export_research_note_envelope(ref_report),
        "prompt_injection_summary": {
            "run_id": inj_report.run_id,
            "injection_events_detected": len(inj_report.prompt_injection_events),
            "segments_quarantined": inj_report.diagnostics.segments_quarantined,
            "verified_claims_preserved": inj_report.diagnostics.claims_verified,
            "abstained_questions": inj_report.diagnostics.questions_abstained,
            "trade_action_permitted": inj_report.trade_action_permitted,
        },
    }
    demo_path = reports_dir / "demo_output.json"
    demo_path.write_text(json.dumps(demo_payload, indent=2) + "\n", encoding="utf-8")

    print(f"Demo complete. Run ID: {ref_report.run_id}")
    print(f"Logical digest (replay verified): {ref_digest}")
    print(f"Verified claims: {ref_report.diagnostics.claims_verified}")
    print(f"Guidance comparisons: {ref_report.diagnostics.guidance_comparisons_count}")
    print(f"Prompt injections caught (integration fixture): {len(inj_report.prompt_injection_events)}")
    print(f"Reports written to: {reports_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
