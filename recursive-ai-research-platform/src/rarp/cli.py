"""Command-line interface for the Recursive AI Research Platform."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from rarp.data.fixtures import generate_synthetic_fixture
from rarp.governance.console import ReviewConsoleService, serve_console
from rarp.governance.review import PromotionGate
from rarp.governance.signing import ArtifactSigner
from rarp.orchestrator import ResearchLoopOrchestrator, verify_deterministic_reproducibility
from rarp.registry.store import RunRegistry


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _render_demo_summary_md(report: dict) -> str:
    lines = [
        "# Recursive AI Research Platform — Demo Run Summary",
        "",
        f"- **Session ID:** `{report['session_id']}`",
        f"- **Stop Reason:** `{report['stop_reason']}`",
        f"- **Data Manifest:** `{report['data_manifest_id']}` (`{report['data_manifest_sha256'][:16]}...`)",
        f"- **Split Fingerprint:** `{report['split_sha256'][:16]}...` (holdout blinded: `{report['holdout_metadata']['holdout_blinded']}`)",
        f"- **Registry Hash Chain Valid:** `{report['registry_hash_chain_valid']}`",
        f"- **Best Run ID:** `{report['best_run_id']}`",
        "",
        "## Budget Usage",
        "",
        f"- Iterations: `{report['budget_snapshot']['iterations_used']} / {report['budget_snapshot']['max_iterations']}`",
        f"- Experiments: `{report['budget_snapshot']['experiments_used']} / {report['budget_snapshot']['max_experiments']}`",
        f"- Cost (USD): `${report['budget_snapshot']['cost_usd_used']:.4f} / ${report['budget_snapshot']['max_cost_usd']:.4f}`",
        "",
        "## Runs Recorded in Immutable Registry",
        "",
        "| Run ID | Hypothesis | Status | Train Sharpe | Val Sharpe | Max DD | Trades | Critic Verdict |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    verdicts = {r["run_id"]: r["verdict"] for r in report["critic_reports"]}
    for r in report["runs"]:
        m = r["metrics"]
        lines.append(
            f"| `{r['run_id']}` | `{r['hypothesis_id']}` | {r['status']} | "
            f"{m.get('train_sharpe', 0.0):.3f} | {m.get('validation_sharpe', 0.0):.3f} | "
            f"{m.get('validation_max_drawdown', 0.0):.2%} | {int(m.get('validation_trade_count', 0))} | "
            f"`{verdicts.get(r['run_id'], 'N/A')}` |"
        )

    lines.extend(
        [
            "",
            "## Governance & Paper-Only Promotion Gate",
            "",
        ]
    )
    if report["review_decision"]:
        d = report["review_decision"]
        lines.append(
            f"- Decision `{d['decision_id']}` by independent reviewer `{d['reviewer_id']}`: "
            f"`{d['decision']}` (target: `{d['target_environment']}`)"
        )
    if report["paper_sandbox_package"]:
        p = report["paper_sandbox_package"]
        lines.append(
            f"- Paper Sandbox Package `{p['package_id']}` signed (`{p['signed_artifact']['artifact_id']}`), "
            f"`order_execution_enabled={p['order_execution_enabled']}`, `live_deployment_prohibited={p['live_deployment_prohibited']}`."
        )
    lines.append("")
    lines.append("> **Disclaimer:** Simulated backtest metrics on synthetic fixtures never imply live trading performance.")
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="rarp", description="Recursive AI Research Platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fix = sub.add_parser("generate-fixture", help="Generate deterministic synthetic fixture and SHA-256 manifest")
    p_fix.add_argument("--output-dir", type=Path, default=_default_root() / "data" / "fixtures")
    p_fix.add_argument("--seed", type=int, default=42)

    p_demo = sub.add_parser("demo", help="Run auditable end-to-end recursive research loop demo")
    p_demo.add_argument("--config-dir", type=Path, default=_default_root() / "config")
    p_demo.add_argument(
        "--manifest",
        type=Path,
        default=_default_root() / "data" / "fixtures" / "synthetic_multi_regime_equities_v1.manifest.json",
    )
    p_demo.add_argument("--reports-dir", type=Path, default=_default_root() / "reports")
    p_demo.add_argument("--reviewer-id", type=str, default="reviewer_independent_lead")

    p_repro = sub.add_parser("reproduce", help="Verify deterministic replay reproducibility across clean runs")
    p_repro.add_argument("--config-dir", type=Path, default=_default_root() / "config")
    p_repro.add_argument(
        "--manifest",
        type=Path,
        default=_default_root() / "data" / "fixtures" / "synthetic_multi_regime_equities_v1.manifest.json",
    )
    p_repro.add_argument("--output", type=Path, default=_default_root() / "reports" / "reproducibility_report.json")

    p_serve = sub.add_parser("serve-console", help="Start the local HTTP Review Console")
    p_serve.add_argument("--state-dir", type=Path, default=_default_root() / "reports" / "demo_state")
    p_serve.add_argument("--host", type=str, default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)

    args = parser.parse_args(argv)

    if args.command == "generate-fixture":
        csv_path, manifest_path, manifest = generate_synthetic_fixture(args.output_dir, seed=args.seed)
        print(f"Generated fixture: {csv_path}")
        print(f"Generated manifest: {manifest_path} (sha256={manifest.content_sha256})")
        return 0

    if args.command == "demo":
        args.reports_dir.mkdir(parents=True, exist_ok=True)
        state_dir = args.reports_dir / "demo_state"
        if state_dir.exists():
            shutil.rmtree(state_dir)
        orch = ResearchLoopOrchestrator(
            config_dir=args.config_dir,
            manifest_path=args.manifest,
            state_dir=state_dir,
        )
        result = orch.run_session(
            session_id="demo_session_v1",
            independent_reviewer_id=args.reviewer_id,
            approve_paper_sandbox=True,
            review_notes="Approved for PAPER_SANDBOX observation only; live execution remains prohibited.",
        )
        report_dict = result.to_dict()
        (args.reports_dir / "demo_report.json").write_text(
            json.dumps(report_dict, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (args.reports_dir / "demo_summary.md").write_text(
            _render_demo_summary_md(report_dict), encoding="utf-8"
        )
        print(
            f"Demo completed: runs={len(result.runs)}, best_run={result.best_run_id}, "
            f"stop_reason={result.stop_reason}, hash_chain_valid={result.registry_hash_chain_valid}"
        )
        return 0

    if args.command == "reproduce":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="rarp_repro_") as tmp:
            repro = verify_deterministic_reproducibility(
                config_dir=args.config_dir,
                manifest_path=args.manifest,
                work_dir=Path(tmp),
            )
        args.output.write_text(json.dumps(repro, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"Reproducibility check: reproducible={repro['reproducible']}, "
            f"max_abs_metric_diff={repro['max_abs_metric_diff']}"
        )
        return 0 if repro["reproducible"] else 1

    if args.command == "serve-console":
        registry = RunRegistry(args.state_dir)
        gate = PromotionGate(registry, ArtifactSigner())
        service = ReviewConsoleService(registry, gate)
        serve_console(service, host=args.host, port=args.port)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
