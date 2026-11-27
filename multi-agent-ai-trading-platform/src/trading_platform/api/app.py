"""FastAPI application exposing REST endpoints and zero-CDN Operator Console UI."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from trading_platform.domain.errors import PlatformError
from trading_platform.domain.types import ApprovalStatus
from trading_platform.service import TradingPlatform


class RunCycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(pattern=r"^[A-Za-z]{1,10}$")
    override_quantity: int | None = Field(default=None, gt=0, le=1_000_000)
    override_limit_price: Decimal | None = Field(default=None, gt=Decimal("0"))


class DecideApprovalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1, max_length=64)
    approve: bool
    expected_action_hash: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


class DispatchOrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=8, max_length=128)
    actor_id: str = Field(default="OMS_DISPATCHER", min_length=1, max_length=64)


class ExecutionModeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = Field(min_length=1, max_length=32)
    actor_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="Operator mode change", min_length=3, max_length=300)


class KillSwitchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    actor_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(default="Operator kill switch toggle", min_length=3, max_length=300)


def create_app(platform: TradingPlatform | None = None) -> FastAPI:
    svc = platform or TradingPlatform.from_project_root()
    app = FastAPI(
        title="Multi-Agent AI Trading Platform — Operator Console & API",
        version="0.1.0",
        description=(
            "Coordinates research, portfolio, risk, and execution services through typed proposals "
            "while deterministic policy remains the final authority."
        ),
    )
    app.state.platform = svc

    @app.exception_handler(PlatformError)
    async def handle_platform_error(_request: Request, exc: PlatformError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    web_index = Path(__file__).resolve().parent.parent / "web" / "index.html"

    @app.get("/", response_class=HTMLResponse)
    def console_ui() -> HTMLResponse:
        return HTMLResponse(content=web_index.read_text(encoding="utf-8"))

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        chain_valid, count, err = svc.repository.verify_audit_chain()
        return {
            "status": "ok" if chain_valid else "degraded",
            "policy_version": svc.config.policy.policy_version,
            "execution_mode": svc.repository.get_execution_mode().value,
            "kill_switch_active": svc.repository.get_kill_switch(),
            "audit_chain_valid": chain_valid,
            "audit_entries": count,
            "audit_error": err,
        }

    @app.get("/api/metrics")
    def metrics() -> dict[str, Any]:
        return svc.get_metrics()

    @app.get("/api/account")
    def get_account() -> dict[str, Any]:
        return svc.get_account_snapshot().model_dump(mode="json")

    @app.get("/api/quotes")
    def get_quotes() -> dict[str, Any]:
        return {
            sym: q.model_dump(mode="json")
            for sym, q in svc.market_data.get_all_quotes().items()
        }

    @app.post("/api/controls/execution-mode")
    def update_execution_mode(body: ExecutionModeBody) -> dict[str, Any]:
        mode = svc.set_execution_mode(mode=body.mode, actor_id=body.actor_id, reason=body.reason)
        return {"execution_mode": mode.value}

    @app.post("/api/controls/kill-switch")
    def update_kill_switch(body: KillSwitchBody) -> dict[str, Any]:
        active = svc.set_kill_switch(active=body.active, actor_id=body.actor_id, reason=body.reason)
        return {"kill_switch_active": active}

    @app.post("/api/runs")
    def create_run(body: RunCycleRequest) -> dict[str, Any]:
        outcome = svc.run_cycle(
            symbol=body.symbol.upper(),
            override_quantity=body.override_quantity,
            override_limit_price=body.override_limit_price,
        )
        return {
            "run": outcome.run.model_dump(mode="json"),
            "proposal": outcome.proposal.model_dump(mode="json") if outcome.proposal else None,
            "risk_assessment": (
                outcome.risk_assessment.model_dump(mode="json") if outcome.risk_assessment else None
            ),
            "approval_request": (
                outcome.approval_request.model_dump(mode="json")
                if outcome.approval_request
                else None
            ),
            "conflicts": [c.model_dump(mode="json") for c in outcome.conflicts],
        }

    @app.get("/api/runs")
    def list_runs(limit: int = 50) -> list[dict[str, Any]]:
        return [r.model_dump(mode="json") for r in svc.repository.list_runs(limit=limit)]

    @app.get("/api/runs/{run_id}/provenance")
    def get_run_provenance(run_id: str) -> dict[str, Any]:
        prov = svc.get_run_provenance(run_id)
        if prov is None:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        return prov

    @app.get("/api/approvals")
    def list_approvals(status: str | None = None) -> list[dict[str, Any]]:
        parsed_status = ApprovalStatus(status.upper()) if status else None
        return [a.model_dump(mode="json") for a in svc.repository.list_approvals(status=parsed_status)]

    @app.post("/api/approvals/{approval_id}/decide")
    def decide_approval(approval_id: str, body: DecideApprovalBody) -> dict[str, Any]:
        updated = svc.decide_approval(
            approval_id=approval_id,
            actor_id=body.actor_id,
            approve=body.approve,
            expected_action_hash=body.expected_action_hash,
            reason=body.reason,
        )
        return updated.model_dump(mode="json")

    @app.post("/api/oms/dispatch")
    def dispatch_order(body: DispatchOrderBody) -> dict[str, Any]:
        order = svc.dispatch_order(
            approval_id=body.approval_id,
            idempotency_key=body.idempotency_key,
            actor_id=body.actor_id,
        )
        return order.model_dump(mode="json")

    @app.get("/api/oms/orders")
    def list_orders(limit: int = 100) -> list[dict[str, Any]]:
        return [o.model_dump(mode="json") for o in svc.repository.list_orders(limit=limit)]

    @app.get("/api/oms/fills")
    def list_fills(limit: int = 200) -> list[dict[str, Any]]:
        return [f.model_dump(mode="json") for f in svc.repository.list_fills(limit=limit)]

    @app.get("/api/audit")
    def list_audit(limit: int = 200) -> list[dict[str, Any]]:
        return [e.model_dump(mode="json") for e in svc.repository.list_audit_entries(limit=limit)]

    @app.get("/api/audit/verify")
    def verify_audit() -> dict[str, Any]:
        valid, count, err = svc.repository.verify_audit_chain()
        return {"valid": valid, "entry_count": count, "error": err}

    return app
