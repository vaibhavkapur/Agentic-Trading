"""Integration tests: unit mismatch handling, compatible conversions, and conflicting reports."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from macro_intelligence_agent.archive import ReleaseArchive
from macro_intelligence_agent.config import AgentConfig
from macro_intelligence_agent.errors import UnitMismatchError
from macro_intelligence_agent.models import MacroRelease, Unit, convert_unit
from macro_intelligence_agent.service import MacroIntelligenceService

FIXTURES_DIR = PROJECT_ROOT / "data" / "fixtures"


class TestIntegrationUnitMismatchAndConflicts(unittest.TestCase):
    def test_unit_conversion_rules(self) -> None:
        self.assertEqual(
            convert_unit(Decimal("450"), Unit.BPS, Unit.PERCENT_RATE),
            Decimal("4.50"),
        )
        self.assertEqual(
            convert_unit(Decimal("1.5"), Unit.MILLIONS, Unit.THOUSANDS),
            Decimal("1500.0"),
        )
        with self.assertRaises(UnitMismatchError):
            convert_unit(Decimal("0.4"), Unit.PERCENT_MOM, Unit.PERCENT_YOY)
        with self.assertRaises(UnitMismatchError):
            convert_unit(Decimal("2.5"), Unit.PERCENT_QOQ_SAAR, Unit.PERCENT_YOY)

    def test_integration_unit_mismatch_and_conflicting_reports_fixture(self) -> None:
        with ReleaseArchive(":memory:") as archive:
            archive.load_fixture_file(
                FIXTURES_DIR / "integration_unit_mismatch_and_conflict.json"
            )
            service = MacroIntelligenceService(archive=archive, config=AgentConfig())
            result = service.generate_brief(
                series_group="INTEGRATION_EDGE_CASES",
                as_of_utc="2025-05-02T13:00:00Z",
            )

        brief = result.brief
        self.assertTrue(brief.verification_passed)

        # 1. Compatible conversion: ECB 2.50% vs 225 bps consensus -> +0.25% surprise
        surprises = {s.series_id: s for s in brief.surprises}
        self.assertIn("ECB_DEPOSIT_RATE", surprises)
        self.assertEqual(surprises["ECB_DEPOSIT_RATE"].surprise_value, Decimal("0.25"))
        self.assertEqual(surprises["ECB_DEPOSIT_RATE"].converted_from_unit, Unit.BPS)
        self.assertEqual(surprises["ECB_DEPOSIT_RATE"].direction, "above_consensus")

        # 2. Incompatible unit mismatch: EU_HICP MoM actual vs YoY consensus -> conflict + abstention, NO surprise
        self.assertNotIn("EU_HICP_HEADLINE", surprises)
        conflicts_by_series = {c.series_id: c for c in brief.conflicts}
        self.assertIn("EU_HICP_HEADLINE", conflicts_by_series)
        self.assertEqual(conflicts_by_series["EU_HICP_HEADLINE"].conflict_type, "unit_mismatch")

        # 3. Conflicting reports: US_NFP Wire A (185k) vs Wire B (245k) -> conflict + abstention, excluded from canonical figures & surprises
        figures_by_series = {f.series_id: f for f in brief.figures}
        self.assertNotIn("US_NFP", figures_by_series)
        self.assertNotIn("US_NFP", surprises)
        self.assertIn("US_NFP", conflicts_by_series)
        self.assertEqual(conflicts_by_series["US_NFP"].conflict_type, "conflicting_reports")

        abstention_scopes = {a.scope: a for a in brief.abstentions}
        self.assertIn("surprise:EU_HICP_HEADLINE:2025-04", abstention_scopes)
        self.assertEqual(
            abstention_scopes["surprise:EU_HICP_HEADLINE:2025-04"].reason_code,
            "UNIT_MISMATCH",
        )
        self.assertIn("metric:US_NFP:2025-04", abstention_scopes)
        self.assertEqual(
            abstention_scopes["metric:US_NFP:2025-04"].reason_code,
            "CONFLICTING_REPORTS",
        )

        # Pending Data Reconciliation hypothesis generated citing conflicts
        hyp_labels = {h.label for h in brief.scenarios}
        self.assertIn("Pending Data Reconciliation Hypothesis", hyp_labels)

    def test_agreeing_multi_source_reports_reconcile_without_conflict(self) -> None:
        r1 = MacroRelease.from_dict(
            {
                "release_id": "NFP_SRC_1",
                "vintage_id": "v1",
                "vintage_sequence": 1,
                "series_group": "AGREE_TEST",
                "reference_period": "2025-04",
                "document_type": "press_report",
                "source_id": "WIRE_1",
                "source_name": "Wire 1",
                "title": "NFP 1",
                "published_at": "2025-05-02T12:30:01Z",
                "raw_text": "US Nonfarm Payrolls rose 200 thousand.",
                "reported_metrics": [
                    {
                        "series_id": "US_NFP",
                        "reference_period": "2025-04",
                        "value": "200",
                        "unit": "thousands",
                        "quote": "US Nonfarm Payrolls rose 200 thousand",
                    }
                ],
            }
        )
        r2 = MacroRelease.from_dict(
            {
                "release_id": "NFP_SRC_2",
                "vintage_id": "v1",
                "vintage_sequence": 1,
                "series_group": "AGREE_TEST",
                "reference_period": "2025-04",
                "document_type": "press_report",
                "source_id": "WIRE_2",
                "source_name": "Wire 2",
                "title": "NFP 2",
                "published_at": "2025-05-02T12:30:05Z",
                "raw_text": "US Nonfarm Payrolls gained 0.200 million jobs.",
                "reported_metrics": [
                    {
                        "series_id": "US_NFP",
                        "reference_period": "2025-04",
                        "value": "0.200",
                        "unit": "millions",
                        "quote": "0.200 million jobs",
                    }
                ],
            }
        )
        with ReleaseArchive(":memory:") as archive:
            archive.add_release(r1)
            archive.add_release(r2)
            service = MacroIntelligenceService(archive=archive, config=AgentConfig())
            res = service.generate_brief(
                series_group="AGREE_TEST", as_of_utc="2025-05-02T13:00:00Z"
            )
            self.assertEqual(len(res.brief.conflicts), 0)
            self.assertEqual(len(res.brief.figures), 1)
            self.assertTrue(res.brief.verification_passed)


if __name__ == "__main__":
    unittest.main()
