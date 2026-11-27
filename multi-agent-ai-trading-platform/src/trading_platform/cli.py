"""Command-line interface (`matp`) for the Multi-Agent AI Trading Platform."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn

from trading_platform.api.app import create_app
from trading_platform.domain.errors import PlatformError
from trading_platform.service import TradingPlatform, default_project_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="matp",
        description="Multi-Agent AI Trading Platform CLI (paper/sandbox prototype)",
    )
    parser.add_argument(
        "--db",
        default=str(default_project_root() / "data" / "platform.sqlite3"),
        help="Path to SQLite state database",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run-cycle", help="Run research -> portfolio -> risk -> policy cycle")
    run_p.add_argument("--symbol", required=True, help="Ticker symbol (e.g. AAPL)")

    mode_p = sub.add_parser("set-mode", help="Set execution mode (DISABLED or PAPER)")
    mode_p.add_argument("--mode", required=True, choices=["DISABLED", "PAPER"])
    mode_p.add_argument("--actor", required=True, help="Authorized operator ID")

    app_p = sub.add_parser("approve", help="Approve or reject an exact-action approval request")
    app_p.add_argument("--approval-id", required=True)
    app_p.add_argument("--actor", required=True)
    app_p.add_argument("--hash", required=True, dest="expected_hash")
    app_p.add_argument("--reject", action="store_true")
    app_p.add_argument("--reason", default="Verified via matp CLI")

    disp_p = sub.add_parser("dispatch", help="Idempotently dispatch an approved order to paper broker")
    disp_p.add_argument("--approval-id", required=True)
    disp_p.add_argument("--idempotency-key", required=True)
    disp_p.add_argument("--actor", default="OMS_DISPATCHER")

    sub.add_parser("status", help="Show platform metrics and account snapshot")
    sub.add_parser("verify-audit", help="Verify SHA-256 hash chain integrity of audit log")

    serve_p = sub.add_parser("serve", help="Start FastAPI server and Operator Console")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8080)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    platform = TradingPlatform.from_project_root(db_path=Path(args.db))
    try:
        if args.command == "serve":
            app = create_app(platform)
            uvicorn.run(app, host=args.host, port=args.port)
            return 0
        if args.command == "run-cycle":
            outcome = platform.run_cycle(symbol=args.symbol)
            print(
                json.dumps(
                    {
                        "run": outcome.run.model_dump(mode="json"),
                        "approval_request": (
                            outcome.approval_request.model_dump(mode="json")
                            if outcome.approval_request
                            else None
                        ),
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "set-mode":
            mode = platform.set_execution_mode(mode=args.mode, actor_id=args.actor)
            print(json.dumps({"execution_mode": mode.value}, indent=2))
            return 0
        if args.command == "approve":
            updated = platform.decide_approval(
                approval_id=args.approval_id,
                actor_id=args.actor,
                approve=not args.reject,
                expected_action_hash=args.expected_hash,
                reason=args.reason,
            )
            print(updated.model_dump_json(indent=2))
            return 0
        if args.command == "dispatch":
            order = platform.dispatch_order(
                approval_id=args.approval_id,
                idempotency_key=args.idempotency_key,
                actor_id=args.actor,
            )
            print(order.model_dump_json(indent=2))
            return 0
        if args.command == "status":
            print(
                json.dumps(
                    {
                        "metrics": platform.get_metrics(),
                        "account": platform.get_account_snapshot().model_dump(mode="json"),
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "verify-audit":
            valid, count, err = platform.repository.verify_audit_chain()
            print(json.dumps({"valid": valid, "entry_count": count, "error": err}, indent=2))
            return 0 if valid else 2
    except PlatformError as exc:
        print(json.dumps(exc.to_dict(), indent=2), file=sys.stderr)
        return 1
    finally:
        platform.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
