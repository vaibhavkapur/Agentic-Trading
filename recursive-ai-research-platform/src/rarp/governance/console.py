"""Review console service with zero-dependency WSGI/HTTP interface and optional FastAPI adapter."""

from __future__ import annotations

import html
import json
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from rarp.domain.errors import RARPError
from rarp.domain.types import PromotionTarget, utc_now_iso
from rarp.governance.review import PromotionGate
from rarp.registry.memory import ResearchMemory
from rarp.registry.store import RunRegistry


class ReviewConsoleService:
    """Backend service powering the human review console and REST API."""

    def __init__(
        self,
        registry: RunRegistry,
        promotion_gate: PromotionGate,
        memory: Optional[ResearchMemory] = None,
    ) -> None:
        self.registry = registry
        self.promotion_gate = promotion_gate
        self.memory = memory

    def health(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "timestamp_utc": utc_now_iso(),
            "registry_hash_chain_valid": self.registry.verify_hash_chain(),
            "run_count": len(self.registry.list_runs()),
            "execution_mode": "DISABLED",
            "allowed_promotion_target": PromotionTarget.PAPER_SANDBOX.value,
        }

    def list_runs(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self.registry.list_runs(status=status)]

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        rec = self.registry.get_run(run_id)
        if rec is None:
            return None
        return {
            "run": rec.to_dict(),
            "critic_report": self.registry.get_critic_report_for_run(run_id),
            "review_decisions": self.registry.list_review_decisions(run_id=run_id),
        }

    def list_hypotheses(self, failed_only: bool = False) -> List[Dict[str, Any]]:
        if self.memory is not None:
            entries = self.memory.failed_hypotheses() if failed_only else self.memory.all_entries()
            return [e.to_dict() for e in entries]
        runs = self.registry.list_runs()
        out = []
        for r in runs:
            crit = self.registry.get_critic_report_for_run(r.run_id)
            verdict = crit["verdict"] if crit else None
            is_neg = r.status in ("FAILED", "REJECTED") or verdict == "REJECT"
            if failed_only and not is_neg:
                continue
            out.append(
                {
                    "hypothesis_id": r.hypothesis_id,
                    "run_id": r.run_id,
                    "status": r.status,
                    "critic_verdict": verdict,
                    "error_code": r.error_code,
                    "failure_reason": r.error_message,
                    "metrics": r.metrics,
                }
            )
        return out

    def submit_review(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        decision, pkg = self.promotion_gate.submit_decision(
            run_id=str(payload["run_id"]),
            reviewer_id=str(payload["reviewer_id"]),
            approve=bool(payload["approve"]),
            target_environment=str(payload.get("target_environment", PromotionTarget.PAPER_SANDBOX.value)),
            notes=str(payload.get("notes", "")),
        )
        return {
            "decision": decision.to_dict(),
            "paper_sandbox_package": pkg.to_dict() if pkg else None,
        }

    def render_html(self) -> str:
        health = self.health()
        runs = self.list_runs()
        failed = self.list_hypotheses(failed_only=True)
        decisions = self.registry.list_review_decisions()

        run_rows = []
        for r in runs:
            sharpe = r["metrics"].get("validation_sharpe")
            sharpe_str = f"{sharpe:.3f}" if isinstance(sharpe, (int, float)) else "-"
            run_rows.append(
                f"<tr><td><code>{html.escape(r['run_id'])}</code></td>"
                f"<td><code>{html.escape(r['hypothesis_id'])}</code></td>"
                f"<td>{html.escape(r['status'])}</td>"
                f"<td>{sharpe_str}</td>"
                f"<td><code>{html.escape(r['data_manifest_id'])}</code></td>"
                f"<td><code>{html.escape(r['record_sha256'][:12])}</code></td></tr>"
            )

        failed_rows = []
        for f in failed:
            failed_rows.append(
                f"<li><code>{html.escape(str(f.get('hypothesis_id', '')))}</code> — "
                f"{html.escape(str(f.get('status', '')))} / {html.escape(str(f.get('critic_verdict', '')))} — "
                f"{html.escape(str(f.get('failure_reason') or f.get('error_code') or 'critic_reject'))}</li>"
            )

        dec_rows = []
        for d in decisions:
            dec_rows.append(
                f"<li><code>{html.escape(d['decision_id'])}</code> run=<code>{html.escape(d['run_id'])}</code> "
                f"reviewer=<b>{html.escape(d['reviewer_id'])}</b> decision=<b>{html.escape(d['decision'])}</b> "
                f"target={html.escape(d['target_environment'])}</li>"
            )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>RARP Review Console (Paper Sandbox Only)</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 2rem; color: #111827; }}
    .banner {{ background: #fef3c7; border: 1px solid #f59e0b; padding: 0.75rem 1rem; border-radius: 6px; margin-bottom: 1.5rem; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }}
    th, td {{ border: 1px solid #d1d5db; padding: 0.5rem; text-align: left; font-size: 0.9rem; }}
    th {{ background: #f3f4f6; }}
  </style>
</head>
<body>
  <h1>Recursive AI Research Platform — Review Console</h1>
  <div class="banner">
    <strong>Governance Notice:</strong> Order execution is <code>DISABLED</code>. Promotions require independent human review and are restricted to <code>PAPER_SANDBOX</code> only. Hash chain valid: <code>{health['registry_hash_chain_valid']}</code>.
  </div>
  <h2>Immutable Run Registry ({len(runs)} runs)</h2>
  <table>
    <thead><tr><th>Run ID</th><th>Hypothesis</th><th>Status</th><th>Val Sharpe</th><th>Data Manifest</th><th>Record Hash</th></tr></thead>
    <tbody>{''.join(run_rows) or '<tr><td colspan="6">No runs recorded</td></tr>'}</tbody>
  </table>
  <h2>Discoverable Failed / Negative Hypotheses ({len(failed)})</h2>
  <ul>{''.join(failed_rows) or '<li>None recorded</li>'}</ul>
  <h2>Human Review Decisions ({len(decisions)})</h2>
  <ul>{''.join(dec_rows) or '<li>No decisions recorded yet</li>'}</ul>
</body>
</html>
"""


def create_wsgi_app(service: ReviewConsoleService) -> Callable[..., List[bytes]]:
    """Create a standard-library WSGI app for local console serving and in-process testing."""

    def app(environ: Dict[str, Any], start_response: Callable[..., Any]) -> List[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/")
        qs = parse_qs(environ.get("QUERY_STRING", ""))

        def send_json(status_code: str, body: Any) -> List[bytes]:
            raw = json.dumps(body, indent=2, sort_keys=True).encode("utf-8")
            start_response(status_code, [("Content-Type", "application/json; charset=utf-8")])
            return [raw]

        try:
            if method == "GET" and path == "/":
                html_bytes = service.render_html().encode("utf-8")
                start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
                return [html_bytes]

            if method == "GET" and path == "/health":
                return send_json("200 OK", service.health())

            if method == "GET" and path == "/api/runs":
                status_filter = qs.get("status", [None])[0]
                return send_json("200 OK", {"runs": service.list_runs(status=status_filter)})

            if method == "GET" and path.startswith("/api/runs/"):
                run_id = path[len("/api/runs/") :].strip("/")
                data = service.get_run(run_id)
                if data is None:
                    return send_json("404 Not Found", {"error": f"Run not found: {run_id}"})
                return send_json("200 OK", data)

            if method == "GET" and path == "/api/memory/hypotheses":
                failed_only = qs.get("failed_only", ["false"])[0].lower() == "true"
                return send_json("200 OK", {"hypotheses": service.list_hypotheses(failed_only=failed_only)})

            if method == "GET" and path.startswith("/api/reports/"):
                run_id = path[len("/api/reports/") :].strip("/")
                rep = service.registry.get_critic_report_for_run(run_id)
                if rep is None:
                    return send_json("404 Not Found", {"error": f"Critic report not found for run: {run_id}"})
                return send_json("200 OK", rep)

            if method == "GET" and path == "/api/reviews":
                return send_json("200 OK", {"decisions": service.registry.list_review_decisions()})

            if method == "POST" and path == "/api/reviews/decide":
                length = int(environ.get("CONTENT_LENGTH") or 0)
                raw_body = environ["wsgi.input"].read(length).decode("utf-8") if length > 0 else "{}"
                payload = json.loads(raw_body)
                result = service.submit_review(payload)
                return send_json("200 OK", result)

            return send_json("404 Not Found", {"error": f"Route not found: {method} {path}"})
        except RARPError as exc:
            return send_json("400 Bad Request", exc.to_dict())
        except Exception as exc:
            return send_json("500 Internal Server Error", {"error": str(exc)})

    return app


def create_fastapi_app(service: ReviewConsoleService) -> Any:
    """Optional FastAPI app factory (requires `pip install .[api]`)."""
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import HTMLResponse
    except ImportError as exc:
        raise RuntimeError("FastAPI is not installed; use create_wsgi_app() or install optional extra [api]") from exc

    app = FastAPI(title="Recursive AI Research Platform Review Console", version="0.1.0")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return service.render_html()

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return service.health()

    @app.get("/api/runs")
    def runs(status: Optional[str] = None) -> Dict[str, Any]:
        return {"runs": service.list_runs(status=status)}

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str) -> Dict[str, Any]:
        data = service.get_run(run_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
        return data

    @app.get("/api/memory/hypotheses")
    def hypotheses(failed_only: bool = False) -> Dict[str, Any]:
        return {"hypotheses": service.list_hypotheses(failed_only=failed_only)}

    @app.post("/api/reviews/decide")
    def decide(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return service.submit_review(payload)
        except RARPError as exc:
            raise HTTPException(status_code=400, detail=exc.to_dict()) from exc

    return app


def serve_console(service: ReviewConsoleService, host: str = "127.0.0.1", port: int = 8080) -> None:
    wsgi_app = create_wsgi_app(service)
    with make_server(host, port, wsgi_app) as server:
        print(f"RARP Review Console listening on http://{host}:{port} (PAPER_SANDBOX review only)")
        server.serve_forever()
