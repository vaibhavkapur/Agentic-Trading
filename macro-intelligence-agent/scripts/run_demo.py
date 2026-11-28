#!/usr/bin/env python3
"""Reproducible end-to-end demo script for the Macro Intelligence Agent.

Runs reference (T1 initial & T2 post-revision + FOMC), integration (unit mismatch &
conflicting reports), and security (untrusted source instructions) scenarios using
synthetic offline fixtures, persisting versioned machine-readable outputs to `reports/`.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from macro_intelligence_agent.archive import ReleaseArchive
from macro_intelligence_agent.config import load_config
from macro_intelligence_agent.service import MacroIntelligenceService

FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"
REPORTS_DIR = PROJECT_ROOT / "reports"
CONFIG_PATH = PROJECT_ROOT / "config" / "default_config.json"


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    cfg = load_config(CONFIG_PATH)

    # 1. Reference scenario: T1 (initial release only) & T2 (post-revision + FOMC)
    with ReleaseArchive(":memory:") as archive:
        archive.load_fixture_file(FIXTURES_DIR / "reference_cpi_release.json")
        service = MacroIntelligenceService(archive=archive, config=cfg)

        t1 = service.generate_brief(
            series_group="US_INFLATION_POLICY",
            as_of_utc="2025-04-10T13:00:00Z",
        )
        t2 = service.generate_brief(
            series_group="US_INFLATION_POLICY",
            as_of_utc="2025-05-13T13:00:00Z",
        )
        replay_ok, replay_info = service.replay_run(t2.metadata.run_id)
        if not replay_ok:
            raise RuntimeError(f"Replay verification failed: {replay_info}")

    _write_json(REPORTS_DIR / "baseline_reference_t1.json", t1.to_dict())
    _write_json(REPORTS_DIR / "demo_brief_t2.json", t2.to_dict())

    # 2. Integration scenario: unit mismatch + conflicting reports + bps conversion
    with ReleaseArchive(":memory:") as archive:
        archive.load_fixture_file(
            FIXTURES_DIR / "integration_unit_mismatch_and_conflict.json"
        )
        service = MacroIntelligenceService(archive=archive, config=cfg)
        integ = service.generate_brief(
            series_group="INTEGRATION_EDGE_CASES",
            as_of_utc="2025-05-02T13:00:00Z",
        )
    _write_json(REPORTS_DIR / "integration_edge_cases.json", integ.to_dict())

    # 3. Security scenario: untrusted source instructions quarantined
    with ReleaseArchive(":memory:") as archive:
        archive.load_fixture_file(FIXTURES_DIR / "security_untrusted_instructions.json")
        service = MacroIntelligenceService(archive=archive, config=cfg)
        sec = service.generate_brief(
            series_group="SECURITY_BOUNDARY",
            as_of_utc="2025-04-10T13:00:00Z",
        )
    _write_json(REPORTS_DIR / "security_boundary_output.json", sec.to_dict())

    print("=== Macro Intelligence Agent Demo Complete ===")
    print(f"T1 Initial Brief   : {t1.brief.brief_id} (run_id={t1.metadata.run_id}, gated_out={t1.diagnostics.counters['releases_gated_out']})")
    print(f"T2 Revised Brief   : {t2.brief.brief_id} (run_id={t2.metadata.run_id}, revisions={len(t2.brief.revisions)}, policy_signals={len(t2.brief.policy_signals)}, replay_ok={replay_ok})")
    print(f"Integration Brief  : {integ.brief.brief_id} (conflicts={len(integ.brief.conflicts)}, abstentions={len(integ.brief.abstentions)})")
    print(f"Security Brief     : {sec.brief.brief_id} (security_findings={len(sec.brief.security_findings)}, verification_passed={sec.brief.verification_passed})")
    print(f"Summary (T2)       : {t2.brief.executive_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
