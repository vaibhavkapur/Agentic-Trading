"""Integration tests for full recursive research loop, deterministic replay, and review console."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Tuple

from rarp.data.fixtures import generate_synthetic_fixture
from rarp.governance.console import ReviewConsoleService, create_wsgi_app
from rarp.orchestrator import ResearchLoopOrchestrator, verify_deterministic_reproducibility

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


def _wsgi_request(app, method: str, path: str, query: str = "", body: dict | None = None) -> Tuple[str, bytes]:
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    captured = {}

    def start_response(status: str, headers):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
    }
    chunks = app(environ, start_response)
    return captured["status"], b"".join(chunks)


class TestEndToEndResearchLoopAndConsole(unittest.TestCase):
    def test_full_loop_reproducibility_and_review_console(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _, manifest_path, manifest = generate_synthetic_fixture(tmp_path / "fixtures", seed=42)

            # 1. Full loop execution without auto-approval.
            orch = ResearchLoopOrchestrator(
                config_dir=CONFIG_DIR,
                manifest_path=manifest_path,
                state_dir=tmp_path / "state",
                signing_key="integration-test-key",
            )
            res = orch.run_session(session_id="int_session_1")

            self.assertGreaterEqual(len(res.runs), 3)
            self.assertTrue(res.registry_hash_chain_valid)
            self.assertEqual(res.data_manifest_id, manifest.manifest_id)
            self.assertIsNotNone(res.best_run_id)
            self.assertIsNotNone(res.signed_research_artifact)
            self.assertIsNone(res.review_decision)  # Never auto-approved!
            self.assertTrue(res.holdout_metadata["holdout_blinded"])

            # Budget invariants strictly respected.
            self.assertLessEqual(res.budget_snapshot["iterations_used"], res.budget_snapshot["max_iterations"])
            self.assertLessEqual(res.budget_snapshot["experiments_used"], res.budget_snapshot["max_experiments"])
            self.assertLessEqual(res.budget_snapshot["cost_usd_used"], res.budget_snapshot["max_cost_usd"])

            # Every run resolves to versioned manifest & verified critic report.
            for run in res.runs:
                self.assertEqual(run["data_manifest_id"], manifest.manifest_id)
                self.assertEqual(run["data_manifest_sha256"], manifest.content_sha256)
            for report in res.critic_reports:
                self.assertTrue(report["verified"])
                self.assertGreater(len(report["claims"]), 0)

            # 2. Review Console WSGI integration.
            service = ReviewConsoleService(orch.registry, orch.promotion_gate, orch.memory)
            app = create_wsgi_app(service)

            status, html_body = _wsgi_request(app, "GET", "/")
            self.assertEqual(status, "200 OK")
            self.assertIn(b"PAPER_SANDBOX", html_body)

            status, health_raw = _wsgi_request(app, "GET", "/health")
            self.assertEqual(status, "200 OK")
            health = json.loads(health_raw.decode("utf-8"))
            self.assertTrue(health["registry_hash_chain_valid"])
            self.assertEqual(health["execution_mode"], "DISABLED")

            # Self-approval through API must fail with 400.
            status, err_raw = _wsgi_request(
                app,
                "POST",
                "/api/reviews/decide",
                body={
                    "run_id": res.best_run_id,
                    "reviewer_id": orch.proposer_id,
                    "approve": True,
                    "target_environment": "PAPER_SANDBOX",
                },
            )
            self.assertEqual(status, "400 Bad Request")
            self.assertEqual(json.loads(err_raw.decode("utf-8"))["error_code"], "REVIEW_GATE_DENIED")

            # Independent reviewer approval for PAPER_SANDBOX succeeds.
            status, ok_raw = _wsgi_request(
                app,
                "POST",
                "/api/reviews/decide",
                body={
                    "run_id": res.best_run_id,
                    "reviewer_id": "human_reviewer_maya",
                    "approve": True,
                    "target_environment": "PAPER_SANDBOX",
                    "notes": "Verified evidence and DSR penalty",
                },
            )
            self.assertEqual(status, "200 OK")
            ok_payload = json.loads(ok_raw.decode("utf-8"))
            self.assertEqual(ok_payload["decision"]["decision"], "APPROVED_PAPER_ONLY")
            self.assertFalse(ok_payload["paper_sandbox_package"]["order_execution_enabled"])

            # 3. Deterministic reproducibility check across clean runs.
            repro = verify_deterministic_reproducibility(
                config_dir=CONFIG_DIR,
                manifest_path=manifest_path,
                work_dir=tmp_path / "repro",
                tolerance=1e-12,
            )
            self.assertTrue(repro["reproducible"])
            self.assertLessEqual(repro["max_abs_metric_diff"], 1e-12)


if __name__ == "__main__":
    unittest.main()
