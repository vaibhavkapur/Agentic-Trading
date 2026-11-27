"""Integration tests for FastAPI REST endpoints and Operator Console HTML."""

from __future__ import annotations

from fastapi.testclient import TestClient

from trading_platform.api.app import create_app
from trading_platform.service import TradingPlatform


def test_fastapi_operator_console_and_end_to_end_api(platform: TradingPlatform) -> None:
    app = create_app(platform)
    client = TestClient(app)

    # Operator console HTML loads with zero external CDN dependencies
    ui_resp = client.get("/")
    assert ui_resp.status_code == 200
    assert "Multi-Agent AI Trading Platform" in ui_resp.text
    assert "cdn.jsdelivr" not in ui_resp.text

    # Health check shows DISABLED by default and valid audit chain
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["execution_mode"] == "DISABLED"
    assert health["audit_chain_valid"] is True

    # Enable PAPER mode via API
    mode_resp = client.post(
        "/api/controls/execution-mode",
        json={"mode": "PAPER", "actor_id": "ops_approver_1", "reason": "API paper test"},
    )
    assert mode_resp.status_code == 200
    assert mode_resp.json()["execution_mode"] == "PAPER"

    # Attempt LIVE mode -> rejected with 403 structured error
    live_resp = client.post(
        "/api/controls/execution-mode",
        json={"mode": "LIVE", "actor_id": "ops_approver_1", "reason": "Forbidden live"},
    )
    assert live_resp.status_code == 403
    assert live_resp.json()["error_code"] == "LIVE_TRADING_FORBIDDEN"

    # Run cycle
    run_resp = client.post("/api/runs", json={"symbol": "NVDA"})
    assert run_resp.status_code == 200
    payload = run_resp.json()
    run_id = payload["run"]["run_id"]
    apr = payload["approval_request"]
    assert apr is not None

    # Approve via API
    dec_resp = client.post(
        f"/api/approvals/{apr['approval_id']}/decide",
        json={
            "actor_id": "ops_approver_2",
            "approve": True,
            "expected_action_hash": apr["exact_action_hash"],
            "reason": "API approval verified",
        },
    )
    assert dec_resp.status_code == 200
    assert dec_resp.json()["status"] == "APPROVED"

    # Dispatch via API
    disp_resp = client.post(
        "/api/oms/dispatch",
        json={
            "approval_id": apr["approval_id"],
            "idempotency_key": "IDEMP-API-NVDA-1",
            "actor_id": "ops_approver_2",
        },
    )
    assert disp_resp.status_code == 200
    assert disp_resp.json()["status"] == "FILLED"

    # Provenance and audit verification endpoints
    prov_resp = client.get(f"/api/runs/{run_id}/provenance")
    assert prov_resp.status_code == 200
    assert prov_resp.json()["order"]["order_id"] == disp_resp.json()["order_id"]

    audit_resp = client.get("/api/audit/verify")
    assert audit_resp.status_code == 200
    assert audit_resp.json()["valid"] is True
