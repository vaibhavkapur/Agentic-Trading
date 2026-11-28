"""Domain correctness tests: schema validation, embargoed releases, revised data, and oracle match."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from macro_intelligence_agent.archive import ReleaseArchive
from macro_intelligence_agent.config import AgentConfig
from macro_intelligence_agent.errors import (
    CitationVerificationError,
    EmbargoViolationError,
    SchemaValidationError,
    UnsupportedInputError,
)
from macro_intelligence_agent.models import DocumentType, MacroRelease, Unit, parse_decimal
from macro_intelligence_agent.service import MacroIntelligenceService
from macro_intelligence_agent.verification import verify_brief

FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"


class TestDomainAndEmbargo(unittest.TestCase):
    def setUp(self) -> None:
        self.oracle = json.loads(
            (FIXTURES_DIR / "reference_expected_oracle.json").read_text(encoding="utf-8")
        )
        self.config = AgentConfig()

    def test_schema_rejects_naive_timestamps_and_invalid_inputs(self) -> None:
        base_payload = {
            "release_id": "TEST_1",
            "vintage_id": "v1",
            "vintage_sequence": 1,
            "series_group": "TEST",
            "reference_period": "2025-03",
            "document_type": "economic_release",
            "source_id": "SRC",
            "source_name": "Source",
            "title": "Test Release",
            "published_at": "2025-04-10T12:30:00",  # naive!
            "raw_text": "US Headline CPI rose 2.8% YoY.",
        }
        with self.assertRaises(SchemaValidationError):
            MacroRelease.from_dict(base_payload)

        bad_doc = dict(base_payload, published_at="2025-04-10T12:30:00Z", document_type="tweet")
        with self.assertRaises(UnsupportedInputError):
            MacroRelease.from_dict(bad_doc)

        with self.assertRaises(UnsupportedInputError):
            Unit.parse("lightyears")

        with self.assertRaises(SchemaValidationError):
            parse_decimal("NaN", "value")

        with self.assertRaises(SchemaValidationError):
            parse_decimal(True, "value")

    def test_embargoed_release_invisible_and_checked_access_blocked(self) -> None:
        with ReleaseArchive(":memory:") as archive:
            archive.load_fixture_file(FIXTURES_DIR / "reference_cpi_release.json")
            service = MacroIntelligenceService(archive=archive, config=self.config)

            t1 = self.oracle["cutoffs"]["T1_initial_only"]
            result = service.generate_brief(
                series_group=t1["series_group"],
                as_of_utc=t1["as_of_utc"],
            )

            # Future / embargoed releases must not appear anywhere in the output
            serialized = json.dumps(result.to_dict())
            self.assertNotIn("US_CPI_2025_05_EMBARGOED", serialized)
            self.assertNotIn("v2_revised", serialized)
            self.assertNotIn("FOMC_STMT_2025_05", serialized)
            self.assertEqual(
                result.diagnostics.counters["releases_gated_out"],
                t1["expected_gated_out_count"],
            )

            # Explicit checked access before embargo raises EmbargoViolationError
            with self.assertRaises(EmbargoViolationError):
                archive.get_release_checked(
                    "US_CPI_2025_05_EMBARGOED",
                    "v1_embargoed",
                    t1["as_of_utc"],
                )

            # Matches hand-calculated T1 oracle
            figs = {f"{f.series_id}:{f.reference_period}": f for f in result.brief.figures}
            for key, exp in t1["expected_figures"].items():
                self.assertIn(key, figs)
                self.assertEqual(figs[key].value, Decimal(exp["value"]))
                self.assertEqual(figs[key].unit.value, exp["unit"])
                self.assertEqual(figs[key].vintage_id, exp["vintage_id"])

            surprises = {f"{s.series_id}:{s.reference_period}": s for s in result.brief.surprises}
            for key, exp in t1["expected_surprises"].items():
                self.assertIn(key, surprises)
                self.assertEqual(surprises[key].surprise_value, Decimal(exp["surprise"]))
                self.assertEqual(surprises[key].direction, exp["direction"])

            self.assertEqual(len(result.brief.revisions), 0)
            self.assertTrue(result.brief.verification_passed)

    def test_revised_data_and_fomc_policy_match_oracle_t2(self) -> None:
        with ReleaseArchive(":memory:") as archive:
            archive.load_fixture_file(FIXTURES_DIR / "reference_cpi_release.json")
            service = MacroIntelligenceService(archive=archive, config=self.config)

            t2 = self.oracle["cutoffs"]["T2_post_revision_and_fomc"]
            result = service.generate_brief(
                series_group=t2["series_group"],
                as_of_utc=t2["as_of_utc"],
            )

            # Embargoed May CPI still hidden at T2
            self.assertNotIn("US_CPI_2025_05_EMBARGOED", json.dumps(result.to_dict()))
            self.assertEqual(
                result.diagnostics.counters["releases_gated_out"],
                t2["expected_gated_out_count"],
            )

            # Latest figures use v2_revised for CPI and v1_statement for FOMC
            figs = {f"{f.series_id}:{f.reference_period}": f for f in result.brief.figures}
            for key, exp in t2["expected_latest_figures"].items():
                self.assertIn(key, figs)
                self.assertEqual(figs[key].value, Decimal(exp["value"]))
                self.assertEqual(figs[key].vintage_id, exp["vintage_id"])

            # Surprises match hand-calculated oracle including bps->percent_rate conversion
            surprises = {f"{s.series_id}:{s.reference_period}": s for s in result.brief.surprises}
            for key, exp in t2["expected_surprises"].items():
                self.assertIn(key, surprises)
                self.assertEqual(surprises[key].surprise_value, Decimal(exp["surprise"]))
                self.assertEqual(surprises[key].direction, exp["direction"])
                if "converted_from_unit" in exp:
                    self.assertEqual(
                        surprises[key].converted_from_unit.value, exp["converted_from_unit"]
                    )

            # Revision diffs match hand-calculated oracle
            revs = {f"{r.series_id}:{r.reference_period}": r for r in result.brief.revisions}
            self.assertEqual(len(revs), len(t2["expected_revisions"]))
            for exp_rev in t2["expected_revisions"]:
                key = f"{exp_rev['series_id']}:{exp_rev['reference_period']}"
                self.assertIn(key, revs)
                self.assertEqual(revs[key].prior_value, Decimal(exp_rev["prior_value"]))
                self.assertEqual(revs[key].current_value, Decimal(exp_rev["current_value"]))
                self.assertEqual(revs[key].delta, Decimal(exp_rev["delta"]))
                self.assertEqual(revs[key].direction, exp_rev["direction"])
                # Both prior and current citations must be indexed
                self.assertIn(revs[key].prior_citation.citation_id, result.brief.citations_index)
                self.assertIn(revs[key].current_citation.citation_id, result.brief.citations_index)

            # Policy language stances extracted with citations
            stances = {p.stance.value for p in result.brief.policy_signals}
            for exp_stance in t2["expected_policy_stances"]:
                self.assertIn(exp_stance, stances)

            self.assertTrue(result.brief.verification_passed)

    def test_raw_text_regex_extraction_without_structured_metrics(self) -> None:
        release = MacroRelease.from_dict(
            {
                "release_id": "RAW_ONLY_CPI",
                "vintage_id": "v1",
                "vintage_sequence": 1,
                "series_group": "RAW_GROUP",
                "reference_period": "2025-04",
                "document_type": DocumentType.ECONOMIC_RELEASE.value,
                "source_id": "SYNTH_BLS",
                "source_name": "Synthetic BLS",
                "title": "Raw Text CPI",
                "published_at": "2025-05-10T12:30:00Z",
                "raw_text": "Bulletin: US Headline CPI slowed to 2.5% YoY and US Core CPI eased to 2.9% YoY.",
            }
        )
        with ReleaseArchive(":memory:") as archive:
            archive.add_release(release)
            service = MacroIntelligenceService(archive=archive, config=self.config)
            res = service.generate_brief(
                series_group="RAW_GROUP", as_of_utc="2025-05-10T13:00:00Z"
            )
            by_series = {f.series_id: f for f in res.brief.figures}
            self.assertEqual(by_series["US_CPI_HEADLINE"].value, Decimal("2.5"))
            self.assertEqual(by_series["US_CPI_CORE"].value, Decimal("2.9"))
            self.assertEqual(
                by_series["US_CPI_HEADLINE"].extraction_method, "deterministic_text_regex"
            )
            # Missing consensus yields explicit abstention rather than fabricated consensus
            abs_scopes = {a.scope for a in res.brief.abstentions}
            self.assertIn("surprise:US_CPI_HEADLINE:2025-04", abs_scopes)
            self.assertTrue(res.brief.verification_passed)

    def test_verifier_catches_tampered_citation_quote(self) -> None:
        with ReleaseArchive(":memory:") as archive:
            archive.load_fixture_file(FIXTURES_DIR / "reference_cpi_release.json")
            service = MacroIntelligenceService(archive=archive, config=self.config)
            res = service.generate_brief(
                series_group="US_INFLATION_POLICY",
                as_of_utc="2025-04-10T13:00:00Z",
            )
            visible = archive.query_releases_as_of(
                "2025-04-10T13:00:00Z", series_group="US_INFLATION_POLICY"
            )
            bad_fig = res.brief.figures[0]
            tampered_cit = replace(bad_fig.citation, quote="FABRICATED QUOTE 99.9%")
            tampered_index = dict(res.brief.citations_index)
            tampered_index[tampered_cit.citation_id] = tampered_cit
            tampered_brief = replace(res.brief, citations_index=tampered_index)
            with self.assertRaises(CitationVerificationError):
                verify_brief(tampered_brief, visible, res.metadata.as_of_utc)


if __name__ == "__main__":
    unittest.main()
