"""Gold-set numerical, citation, revision, security, and abstention evaluator."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import platform
from typing import Any, Dict, List, Optional, Union

from .archive import ReleaseArchive
from .config import AgentConfig
from .models import parse_decimal
from .service import MacroIntelligenceService


def _within_tol(a: Decimal, b: Decimal, tol: Decimal) -> bool:
    return abs(a - b) <= tol


def evaluate_gold_set(
    gold_set_path: Union[str, Path],
    *,
    fixtures_dir: Optional[Union[str, Path]] = None,
    config: Optional[AgentConfig] = None,
) -> Dict[str, Any]:
    """Run all curated gold-set cases and compute exact-match, citation, and abstention metrics."""
    cfg = config or AgentConfig()
    gpath = Path(gold_set_path)
    fdir = Path(fixtures_dir) if fixtures_dir is not None else gpath.parent
    gold = json.loads(gpath.read_text(encoding="utf-8"))

    tol = cfg.numeric_tolerance

    total_expected_figures = 0
    matched_figures = 0
    total_emitted_figures = 0
    traceable_figures = 0

    total_expected_surprises = 0
    matched_surprises = 0

    total_expected_revisions = 0
    matched_revisions = 0

    abstention_tp = 0
    abstention_fp = 0
    abstention_fn = 0

    embargo_leakages = 0
    false_fabrications = 0
    security_checks_total = 0
    security_checks_passed = 0

    case_reports: List[Dict[str, Any]] = []

    for case in gold["cases"]:
        archive = ReleaseArchive(":memory:")
        try:
            archive.load_fixture_file(fdir / case["fixture_file"])
            service = MacroIntelligenceService(archive=archive, config=cfg)
            result = service.generate_brief(
                series_group=case["series_group"],
                as_of_utc=case["as_of_utc"],
                persist_run=False,
            )
        finally:
            archive.close()

        brief = result.brief
        expected = case["expected"]

        # 1. Embargo / publication-gate leakage check
        serialized_brief = json.dumps(brief.to_dict())
        case_leaks: List[str] = []
        for forbidden_id in expected.get("must_not_contain_release_ids", []):
            if forbidden_id in serialized_brief:
                case_leaks.append(forbidden_id)
                embargo_leakages += 1

        # 2. Figure exact-match + citation traceability check
        emitted_figs_by_key = {
            (f.series_id, f.reference_period): f for f in brief.figures
        }
        expected_figs_keys = set()
        case_fig_matches = 0
        for exp_fig in expected.get("figures", []):
            total_expected_figures += 1
            key = (exp_fig["series_id"], exp_fig["reference_period"])
            expected_figs_keys.add(key)
            actual = emitted_figs_by_key.get(key)
            if actual is not None:
                val_ok = _within_tol(
                    actual.value, parse_decimal(exp_fig["value"], "expected.value"), tol
                )
                unit_ok = actual.unit.value == exp_fig["unit"]
                quote_ok = exp_fig["quote_substring"] in actual.citation.quote
                if val_ok and unit_ok and quote_ok:
                    matched_figures += 1
                    case_fig_matches += 1

        for fig in brief.figures:
            total_emitted_figures += 1
            if fig.citation.citation_id in brief.citations_index and brief.verification_passed:
                traceable_figures += 1
            if (fig.series_id, fig.reference_period) not in expected_figs_keys:
                false_fabrications += 1

        # 3. Surprise exact-match check
        emitted_srp_by_key = {
            (s.series_id, s.reference_period): s for s in brief.surprises
        }
        expected_srp_keys = set()
        case_srp_matches = 0
        for exp_srp in expected.get("surprises", []):
            total_expected_surprises += 1
            key = (exp_srp["series_id"], exp_srp["reference_period"])
            expected_srp_keys.add(key)
            actual_s = emitted_srp_by_key.get(key)
            if actual_s is not None:
                val_ok = _within_tol(
                    actual_s.surprise_value,
                    parse_decimal(exp_srp["surprise_value"], "expected.surprise_value"),
                    tol,
                )
                dir_ok = actual_s.direction == exp_srp["direction"]
                if val_ok and dir_ok:
                    matched_surprises += 1
                    case_srp_matches += 1

        for srp in brief.surprises:
            if (srp.series_id, srp.reference_period) not in expected_srp_keys:
                false_fabrications += 1

        # 4. Revision exact-match check
        emitted_rev_by_key = {
            (r.series_id, r.reference_period): r for r in brief.revisions
        }
        case_rev_matches = 0
        for exp_rev in expected.get("revisions", []):
            total_expected_revisions += 1
            key = (exp_rev["series_id"], exp_rev["reference_period"])
            actual_r = emitted_rev_by_key.get(key)
            if actual_r is not None:
                val_ok = _within_tol(
                    actual_r.delta,
                    parse_decimal(exp_rev["delta"], "expected.delta"),
                    tol,
                )
                dir_ok = actual_r.direction == exp_rev["direction"]
                if val_ok and dir_ok:
                    matched_revisions += 1
                    case_rev_matches += 1

        # 5. Abstention precision / recall
        expected_abs = set(expected.get("must_abstain_scopes", []))
        actual_abs = {a.scope for a in brief.abstentions}
        tp = len(expected_abs & actual_abs)
        fp = len(actual_abs - expected_abs)
        fn = len(expected_abs - actual_abs)
        abstention_tp += tp
        abstention_fp += fp
        abstention_fn += fn

        # 6. Security finding check
        min_sec = int(expected.get("min_security_findings", 0))
        sec_ok = len(brief.security_findings) >= min_sec
        if min_sec > 0:
            security_checks_total += 1
            if sec_ok:
                security_checks_passed += 1

        case_passed = (
            not case_leaks
            and case_fig_matches == len(expected.get("figures", []))
            and case_srp_matches == len(expected.get("surprises", []))
            and case_rev_matches == len(expected.get("revisions", []))
            and fp == 0
            and fn == 0
            and sec_ok
            and brief.verification_passed
        )

        case_reports.append(
            {
                "case_id": case["case_id"],
                "run_id": result.metadata.run_id,
                "brief_id": brief.brief_id,
                "passed": case_passed,
                "verification_passed": brief.verification_passed,
                "figures_matched": f"{case_fig_matches}/{len(expected.get('figures', []))}",
                "surprises_matched": f"{case_srp_matches}/{len(expected.get('surprises', []))}",
                "revisions_matched": f"{case_rev_matches}/{len(expected.get('revisions', []))}",
                "expected_abstentions": sorted(expected_abs),
                "actual_abstentions": sorted(actual_abs),
                "embargo_leaks": case_leaks,
                "security_findings_count": len(brief.security_findings),
            }
        )

    def _safe_ratio(num: int, den: int) -> float:
        return round(num / den, 6) if den > 0 else 1.0

    abs_precision = _safe_ratio(abstention_tp, abstention_tp + abstention_fp)
    abs_recall = _safe_ratio(abstention_tp, abstention_tp + abstention_fn)
    abs_f1 = (
        round((2 * abs_precision * abs_recall) / (abs_precision + abs_recall), 6)
        if (abs_precision + abs_recall) > 0
        else 1.0
    )

    return {
        "gold_set_id": gold["gold_set_id"],
        "schema_version": cfg.schema_version,
        "runtime": {
            "python_version": platform.python_version(),
            "config_sha256": cfg.config_sha256,
            "seed": cfg.seed,
            "numeric_tolerance": format(tol, "f"),
            "data_origin": "synthetic_curated_gold_fixtures",
        },
        "metrics": {
            "cases_total": len(case_reports),
            "cases_passed": sum(1 for c in case_reports if c["passed"]),
            "figure_exact_match_rate": _safe_ratio(matched_figures, total_expected_figures),
            "figure_exact_matches": f"{matched_figures}/{total_expected_figures}",
            "surprise_exact_match_rate": _safe_ratio(matched_surprises, total_expected_surprises),
            "surprise_exact_matches": f"{matched_surprises}/{total_expected_surprises}",
            "revision_exact_match_rate": _safe_ratio(matched_revisions, total_expected_revisions),
            "revision_exact_matches": f"{matched_revisions}/{total_expected_revisions}",
            "citation_traceability_rate": _safe_ratio(traceable_figures, total_emitted_figures),
            "abstention_precision": abs_precision,
            "abstention_recall": abs_recall,
            "abstention_f1": abs_f1,
            "abstention_counts": {
                "tp": abstention_tp,
                "fp": abstention_fp,
                "fn": abstention_fn,
            },
            "embargo_leakage_count": embargo_leakages,
            "false_fabrication_count": false_fabrications,
            "security_guardrail_pass_rate": _safe_ratio(
                security_checks_passed, security_checks_total
            ),
        },
        "cases": case_reports,
    }
