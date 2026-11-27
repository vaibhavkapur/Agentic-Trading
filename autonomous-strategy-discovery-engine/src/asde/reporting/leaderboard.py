"""Research leaderboard showing uncertainty, benchmarks, and rejected/failed candidates."""

from __future__ import annotations

from typing import Any, Dict, List

from asde.reporting.multiple_testing import MultipleTestingStats


def build_research_leaderboard(
    *,
    run_id: str,
    dataset_fingerprint: str,
    split_manifest_hash: str,
    primary_cost_scenario: str,
    cost_scenario_hash: str,
    trial_accounting: Dict[str, int],
    baseline_rows: List[Dict[str, Any]],
    candidate_rows: List[Dict[str, Any]],
    failed_rows: List[Dict[str, Any]],
    mt_stats: Dict[str, MultipleTestingStats],
    holdout_summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble a complete research leaderboard including uncertainty and all failed/rejected runs."""
    enriched_candidates: List[Dict[str, Any]] = []
    for row in candidate_rows:
        sid = row["strategy_id"]
        mt = mt_stats.get(sid)
        entry = dict(row)
        if mt is not None:
            entry["multiple_testing"] = mt.to_dict()
        enriched_candidates.append(entry)

    # Sort eligible first, then by DSR probability and Sharpe ratio descending
    status_order = {"ELIGIBLE_FOR_REVIEW": 0, "REJECTED": 1, "FAILED": 2}
    enriched_candidates.sort(
        key=lambda r: (
            status_order.get(r["governance_status"], 9),
            -(r.get("multiple_testing", {}).get("dsr_probability", 0.0)),
            -(r.get("metrics", {}).get("sharpe_ratio", -99.0)),
            r["strategy_id"],
        )
    )

    return {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "dataset_fingerprint": dataset_fingerprint,
        "split_manifest_hash": split_manifest_hash,
        "primary_cost_scenario": primary_cost_scenario,
        "cost_scenario_hash": cost_scenario_hash,
        "trial_accounting": trial_accounting,
        "holdout_audit": holdout_summary,
        "governance_notice": (
            "Simulated walk-forward results do NOT imply live trading performance. "
            "Order execution is disabled; independent review is mandatory before paper/sandbox promotion."
        ),
        "baselines": baseline_rows,
        "candidates": enriched_candidates,
        "failed_candidates": failed_rows,
    }


def render_leaderboard_markdown(leaderboard: Dict[str, Any]) -> str:
    """Render the research leaderboard as a GitHub-flavored Markdown report."""
    ta = leaderboard["trial_accounting"]
    ha = leaderboard["holdout_audit"]
    lines: List[str] = [
        f"# Research Leaderboard — Run `{leaderboard['run_id']}`",
        "",
        f"> **Governance Notice:** {leaderboard['governance_notice']}",
        "",
        "## Provenance & Trial Accounting",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Dataset Fingerprint | `{leaderboard['dataset_fingerprint'][:16]}...` |",
        f"| Split Manifest Hash | `{leaderboard['split_manifest_hash'][:16]}...` |",
        f"| Cost Scenario | `{leaderboard['primary_cost_scenario']}` (`{leaderboard['cost_scenario_hash'][:12]}...`) |",
        f"| Total Trials Accounted (incl. inner & failures) | {ta['total_trials_recorded']} |",
        f"| Candidate Trials / Baseline Trials | {ta['candidate_trials_total']} / {ta['baseline_trials_total']} |",
        f"| Passed / Rejected / Failed Trials | {ta['passed_trials']} / {ta['rejected_trials']} / {ta['failed_trials']} |",
        f"| Holdout Reads During Selection | {ha['holdout_reads_during_selection']} (Blocked: {ha['blocked_attempts']}) |",
        "",
        "## Baselines (Identical Data & Costs)",
        "",
        "| Baseline | Sharpe (95% CI) | CAGR | Max DD | Ann. Turnover | Cost Drag |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for b in leaderboard["baselines"]:
        m = b["metrics"]
        lines.append(
            f"| `{b['strategy_id']}` | {m['sharpe_ratio']:.3f} [{m['sharpe_ci_low']:.2f}, {m['sharpe_ci_high']:.2f}] "
            f"| {m['cagr']*100:.2f}% | {m['max_drawdown']*100:.2f}% | {m['annualized_turnover']:.2f}x | {m['total_cost_drag']*100:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## Candidate Strategies (All Evaluated Candidates Including Rejected)",
            "",
            "| Strategy | Family | Status | Sharpe (95% CI) | DSR Prob | BH q-val | CAGR | Max DD | Turnover | Pos Folds | Rejection Reasons |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for c in leaderboard["candidates"]:
        m = c["metrics"]
        mt = c.get("multiple_testing", {})
        reasons = ", ".join(c.get("rejection_reasons", [])) or "none"
        lines.append(
            f"| `{c['strategy_id']}` | `{c['family']}` | **{c['governance_status']}** "
            f"| {m['sharpe_ratio']:.3f} [{m['sharpe_ci_low']:.2f}, {m['sharpe_ci_high']:.2f}] "
            f"| {mt.get('dsr_probability', 0.0):.3f} | {mt.get('bh_fdr_q_value', 1.0):.3f} "
            f"| {m['cagr']*100:.2f}% | {m['max_drawdown']*100:.2f}% | {m['annualized_turnover']:.2f}x "
            f"| {c.get('positive_fold_fraction', 0.0)*100:.0f}% | {reasons} |"
        )

    lines.extend(
        [
            "",
            "## Failed / Invalid Candidates",
            "",
        ]
    )
    if not leaderboard["failed_candidates"]:
        lines.append("_No failed/errored outer candidates in this run (all inner/outer failures remain tracked in trial ledger)._")
    else:
        lines.append("| Strategy | Family | Error Code | Message |")
        lines.append("|---|---|---|---|")
        for fc in leaderboard["failed_candidates"]:
            err = fc.get("error") or {}
            lines.append(
                f"| `{fc['strategy_id']}` | `{fc['family']}` | `{err.get('error_code', 'ERROR')}` | {err.get('message', '')} |"
            )

    lines.append("")
    return "\n".join(lines)
