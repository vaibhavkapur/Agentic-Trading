"""Gold-fixture evaluation benchmark for extraction F1, citation validity, and abstention."""

from __future__ import annotations

import json
import platform
import sys
from typing import Any, Dict, List, Optional, Tuple

from .contracts import AgentConfig, ExtractedClaim
from .pipeline import PACKAGE_VERSION, analyze_transcript, report_logical_digest


def _approx_equal(actual: float, expected: float, rel_tol: float, abs_tol: float) -> bool:
    diff = abs(actual - expected)
    if diff <= abs_tol:
        return True
    return diff <= rel_tol * max(abs(actual), abs(expected), 1e-9)


def _claim_matches_gold(
    claim: ExtractedClaim,
    gold: Dict[str, Any],
    rel_tol: float,
    abs_tol: float,
) -> bool:
    if claim.metric_name != gold["metric_name"]:
        return False
    if claim.fiscal_period != gold["fiscal_period"]:
        return False
    if claim.claim_type.value != gold["claim_type"]:
        return False
    if gold.get("accounting_basis") and claim.accounting_basis.value != gold["accounting_basis"]:
        return False
    if claim.normalized_unit.value != gold["normalized_unit"]:
        return False
    if not _approx_equal(claim.normalized_low, float(gold["normalized_low"]), rel_tol, abs_tol):
        return False
    if not _approx_equal(claim.normalized_high, float(gold["normalized_high"]), rel_tol, abs_tol):
        return False
    if gold.get("segment_id") and claim.evidence.segment_id != gold["segment_id"]:
        return False
    if gold.get("expected_quote_substring") and gold["expected_quote_substring"] not in claim.evidence.exact_quote:
        return False
    return True


def evaluate_gold_suite(
    suite_data: Dict[str, Any],
    agent_config: AgentConfig,
    eval_config: Dict[str, Any],
) -> Dict[str, Any]:
    """Run all gold fixtures and compute precision, recall, F1, citation validity, and policy metrics."""
    rel_tol = float(eval_config.get("numeric_relative_tolerance", 0.005))
    abs_tol = float(eval_config.get("numeric_absolute_tolerance", 0.01))
    default_as_of = eval_config.get("as_of_timestamp")

    total_tp = 0
    total_fp = 0
    total_fn = 0
    total_citations = 0
    valid_citations = 0
    total_guidance_checks = 0
    passed_guidance_checks = 0
    total_qa_checks = 0
    passed_qa_checks = 0
    total_injection_cases = 0
    passed_injection_cases = 0

    case_results: List[Dict[str, Any]] = []

    for case in suite_data.get("cases", []):
        case_id = case["case_id"]
        transcript_raw = case["transcript"]
        as_of = case.get("as_of_timestamp", default_as_of)

        report = analyze_transcript(transcript_raw, agent_config, as_of_timestamp=as_of)
        segment_map = {s["segment_id"]: s["text"] for s in transcript_raw["segments"]}

        # 1. Citation validity check (strict verbatim verification against source)
        case_citations = len(report.claims)
        case_valid_citations = 0
        for claim in report.claims:
            ev = claim.evidence
            seg_text = segment_map.get(ev.segment_id, "")
            if (
                ev.verified
                and 0 <= ev.char_start < ev.char_end <= len(seg_text)
                and seg_text[ev.char_start : ev.char_end] == ev.exact_quote
            ):
                case_valid_citations += 1
        total_citations += case_citations
        valid_citations += case_valid_citations

        # 2. Extraction TP / FP / FN matching
        gold_claims = case.get("gold_claims", [])
        matched_claim_indices = set()
        case_tp = 0
        unmatched_gold: List[Dict[str, Any]] = []
        for g in gold_claims:
            found_idx: Optional[int] = None
            for idx, c in enumerate(report.claims):
                if idx in matched_claim_indices:
                    continue
                if _claim_matches_gold(c, g, rel_tol, abs_tol):
                    found_idx = idx
                    break
            if found_idx is not None:
                matched_claim_indices.add(found_idx)
                case_tp += 1
            else:
                unmatched_gold.append(g)

        case_fn = len(gold_claims) - case_tp
        case_fp = len(report.claims) - case_tp
        total_tp += case_tp
        total_fp += case_fp
        total_fn += case_fn

        # 3. Guidance comparison accuracy
        case_guidance_passed = 0
        gold_guidance = case.get("gold_guidance_comparisons", [])
        for gg in gold_guidance:
            total_guidance_checks += 1
            hit = any(
                comp.metric_name == gg["metric_name"]
                and comp.fiscal_period == gg["fiscal_period"]
                and comp.direction.value == gg["direction"]
                and comp.contradiction_detected == bool(gg.get("contradiction_detected", False))
                for comp in report.guidance_comparisons
            )
            if hit:
                case_guidance_passed += 1
                passed_guidance_checks += 1

        # 4. QA & abstention checks
        case_qa_passed = 0
        gold_questions = case.get("gold_questions", [])
        qa_by_id = {a.question_id: a for a in report.question_answers}
        for gq in gold_questions:
            total_qa_checks += 1
            ans = qa_by_id.get(gq["question_id"])
            if ans is None:
                continue
            ok = ans.abstained == bool(gq["should_abstain"])
            if ok and gq.get("expected_abstention_reason"):
                ok = (
                    ans.abstention_reason is not None
                    and ans.abstention_reason.value == gq["expected_abstention_reason"]
                )
            if ok and gq.get("must_cite_segment_id"):
                ok = any(
                    sp.segment_id == gq["must_cite_segment_id"] for sp in ans.evidence_spans
                )
            if ok:
                case_qa_passed += 1
                passed_qa_checks += 1

        # 5. Prompt injection detection & non-leakage
        gold_inj = case.get("gold_injections")
        inj_ok: Optional[bool] = None
        if gold_inj is not None:
            total_injection_cases += 1
            min_events = int(gold_inj.get("min_events", 0))
            forbidden_values = gold_inj.get("forbidden_claim_values", [])
            detected_ok = len(report.prompt_injection_events) >= min_events
            leaked = any(
                any(_approx_equal(c.normalized_point, float(fv), rel_tol, abs_tol) for fv in forbidden_values)
                for c in report.claims
            )
            inj_ok = detected_ok and (not leaked)
            if inj_ok:
                passed_injection_cases += 1

        case_p = case_tp / (case_tp + case_fp) if (case_tp + case_fp) > 0 else 1.0
        case_r = case_tp / (case_tp + case_fn) if (case_tp + case_fn) > 0 else 1.0
        case_f1 = (2 * case_p * case_r / (case_p + case_r)) if (case_p + case_r) > 0 else 0.0

        case_results.append(
            {
                "case_id": case_id,
                "run_id": report.run_id,
                "logical_digest": report_logical_digest(report),
                "extraction": {
                    "tp": case_tp,
                    "fp": case_fp,
                    "fn": case_fn,
                    "precision": round(case_p, 4),
                    "recall": round(case_r, 4),
                    "f1": round(case_f1, 4),
                    "unmatched_gold_count": len(unmatched_gold),
                },
                "citation_validity": {
                    "valid": case_valid_citations,
                    "total": case_citations,
                    "rate": round(case_valid_citations / case_citations, 4) if case_citations > 0 else 1.0,
                },
                "guidance_checks": {
                    "passed": case_guidance_passed,
                    "total": len(gold_guidance),
                },
                "qa_checks": {
                    "passed": case_qa_passed,
                    "total": len(gold_questions),
                },
                "injection_check_passed": inj_ok,
                "warnings": list(report.warnings),
            }
        )

    precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 1.0
    recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    citation_rate = valid_citations / total_citations if total_citations > 0 else 1.0
    guidance_acc = (
        passed_guidance_checks / total_guidance_checks if total_guidance_checks > 0 else 1.0
    )
    qa_acc = passed_qa_checks / total_qa_checks if total_qa_checks > 0 else 1.0
    inj_acc = (
        passed_injection_cases / total_injection_cases if total_injection_cases > 0 else 1.0
    )

    targets = {
        "min_extraction_f1_target": float(eval_config.get("min_extraction_f1_target", 0.85)),
        "min_citation_validity_target": float(eval_config.get("min_citation_validity_target", 1.0)),
        "min_abstention_accuracy_target": float(eval_config.get("min_abstention_accuracy_target", 1.0)),
        "min_injection_detection_target": float(eval_config.get("min_injection_detection_target", 1.0)),
    }
    target_checks = {
        "extraction_f1_met": f1 >= targets["min_extraction_f1_target"],
        "citation_validity_met": citation_rate >= targets["min_citation_validity_target"],
        "qa_and_abstention_met": qa_acc >= targets["min_abstention_accuracy_target"],
        "injection_detection_met": inj_acc >= targets["min_injection_detection_target"],
    }

    return {
        "schema_version": "1.0.0",
        "suite_name": suite_data.get("suite_name", "gold_eval_suite"),
        "suite_version": suite_data.get("suite_version", "1.0.0"),
        "data_provenance": "synthetic_gold_fixtures",
        "summary_metrics": {
            "extraction_tp": total_tp,
            "extraction_fp": total_fp,
            "extraction_fn": total_fn,
            "extraction_precision": round(precision, 4),
            "extraction_recall": round(recall, 4),
            "extraction_f1": round(f1, 4),
            "citation_valid": valid_citations,
            "citation_total": total_citations,
            "citation_validity_rate": round(citation_rate, 4),
            "guidance_accuracy": round(guidance_acc, 4),
            "qa_and_abstention_accuracy": round(qa_acc, 4),
            "injection_detection_accuracy": round(inj_acc, 4),
        },
        "targets": targets,
        "target_checks": target_checks,
        "all_targets_met": all(target_checks.values()),
        "case_results": case_results,
        "runtime_metadata": {
            "package_version": PACKAGE_VERSION,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "config_digest": agent_config.digest(),
            "eval_config": eval_config,
        },
    }


def load_json_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
