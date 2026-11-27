"""Bounded, permission-scoped tool gateway with strict argument validation and provenance capture."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trading_platform.agents.base import PromptInjectionGuard
from trading_platform.domain.contracts import (
    AgentPermissionScope,
    EvidenceItem,
    ToolCallRecord,
)
from trading_platform.domain.errors import ToolAccessError
from trading_platform.domain.types import canonical_hash
from trading_platform.storage.event_bus import EventBus
from trading_platform.storage.repository import StateRepository
from trading_platform.tools.market_tools import MarketDataProvider

MALICIOUS_ARG_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SQL_INJECTION_PATTERN", re.compile(r"(?i)(\bunion\b|\bselect\b|\bdrop\b|--|;\s*\w+|'\s*or\s*')")),
    ("PATH_TRAVERSAL_PATTERN", re.compile(r"(\.\./|\.\.\\|/etc/passwd|/proc/)")),
    ("SHELL_METACHAR_PATTERN", re.compile(r"([|&`$<>]|\$\()")),
    ("CONTROL_CHAR_PATTERN", re.compile(r"[\x00-\x1f\x7f]")),
]

FORBIDDEN_EXECUTION_TOOLS = frozenset(
    {"submit_order", "place_order", "cancel_order", "approve_order", "override_policy", "set_execution_mode"}
)


class SymbolOnlyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=r"^[A-Z]{1,10}$")


class NewsQueryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=r"^[A-Z]{1,10}$")
    limit: int = Field(default=5, ge=1, le=20)


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class ToolExecutionResult:
    data: Any
    evidence_items: list[EvidenceItem]
    call_record: ToolCallRecord


class BoundedToolGateway:
    """Enforces per-agent tool permissions, call budgets, argument hygiene, and evidence capture."""

    def __init__(
        self,
        *,
        market_data: MarketDataProvider,
        repository: StateRepository,
        event_bus: EventBus,
        policy_version: str,
        max_total_tool_calls: int,
        injection_guard: PromptInjectionGuard | None = None,
    ) -> None:
        self._market_data = market_data
        self._repository = repository
        self._event_bus = event_bus
        self._policy_version = policy_version
        self._max_total_tool_calls = max_total_tool_calls
        self._injection_guard = injection_guard or PromptInjectionGuard()
        self._agent_counts: dict[tuple[str, str], int] = {}
        self._run_counts: dict[str, int] = {}

    def get_run_tool_call_count(self, run_id: str) -> int:
        return self._run_counts.get(run_id, 0)

    def invoke(
        self,
        *,
        run_id: str,
        scope: AgentPermissionScope,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        args = dict(arguments or {})
        now_utc = self._market_data.now()

        # 1. Hard-block execution/privileged tools for all agents
        if tool_name in FORBIDDEN_EXECUTION_TOOLS:
            return self._deny(
                run_id=run_id,
                scope=scope,
                tool_name=tool_name,
                arguments=args,
                code="AGENT_EXECUTION_FORBIDDEN",
                message=f"Agent '{scope.agent_id}' ({scope.role}) is permanently forbidden from invoking '{tool_name}'.",
                now_utc=now_utc,
            )

        # 2. Scope allowlist check
        if tool_name not in scope.allowed_tools:
            return self._deny(
                run_id=run_id,
                scope=scope,
                tool_name=tool_name,
                arguments=args,
                code="TOOL_NOT_PERMITTED",
                message=f"Tool '{tool_name}' is outside permission scope for agent '{scope.agent_id}'.",
                now_utc=now_utc,
            )

        # 3. Tool call budget checks (per-agent and per-run)
        agent_key = (run_id, scope.agent_id)
        agent_used = self._agent_counts.get(agent_key, 0)
        run_used = self._run_counts.get(run_id, 0)
        if agent_used >= scope.max_tool_calls:
            return self._deny(
                run_id=run_id,
                scope=scope,
                tool_name=tool_name,
                arguments=args,
                code="AGENT_TOOL_BUDGET_EXCEEDED",
                message=f"Agent '{scope.agent_id}' exceeded max_tool_calls={scope.max_tool_calls}.",
                now_utc=now_utc,
            )
        if run_used >= self._max_total_tool_calls:
            return self._deny(
                run_id=run_id,
                scope=scope,
                tool_name=tool_name,
                arguments=args,
                code="RUN_TOOL_BUDGET_EXCEEDED",
                message=f"Run '{run_id}' exceeded max_total_tool_calls={self._max_total_tool_calls}.",
                now_utc=now_utc,
            )

        # 4. Malicious argument scanning before schema validation
        malicious_hits = self._scan_malicious_arguments(args)
        if malicious_hits:
            return self._deny(
                run_id=run_id,
                scope=scope,
                tool_name=tool_name,
                arguments=args,
                code="MALICIOUS_TOOL_ARGUMENTS",
                message=f"Rejected malicious arguments for tool '{tool_name}': {', '.join(malicious_hits)}.",
                now_utc=now_utc,
            )

        # 5. Strict typed argument validation and execution
        try:
            if tool_name == "get_quote":
                validated = SymbolOnlyArgs.model_validate(args)
                data, evidence = self._exec_get_quote(run_id, validated.symbol, now_utc)
            elif tool_name == "get_fundamentals":
                validated = SymbolOnlyArgs.model_validate(args)
                data, evidence = self._exec_get_fundamentals(run_id, validated.symbol, now_utc)
            elif tool_name == "get_news":
                validated = NewsQueryArgs.model_validate(args)
                data, evidence = self._exec_get_news(run_id, validated.symbol, validated.limit, now_utc)
            elif tool_name == "get_account_state":
                EmptyArgs.model_validate(args)
                data, evidence = self._exec_get_account_state(run_id, now_utc)
            else:
                return self._deny(
                    run_id=run_id,
                    scope=scope,
                    tool_name=tool_name,
                    arguments=args,
                    code="UNKNOWN_TOOL",
                    message=f"Unknown tool '{tool_name}'.",
                    now_utc=now_utc,
                )
        except ValidationError as exc:
            return self._deny(
                run_id=run_id,
                scope=scope,
                tool_name=tool_name,
                arguments=args,
                code="INVALID_TOOL_ARGUMENTS",
                message=f"Invalid arguments for tool '{tool_name}': {exc.errors()[0]['msg']}",
                now_utc=now_utc,
            )

        self._agent_counts[agent_key] = agent_used + 1
        self._run_counts[run_id] = run_used + 1

        evidence_ids = [item.evidence_id for item in evidence]
        for item in evidence:
            self._repository.save_evidence(item)

        record = ToolCallRecord(
            call_id=f"TC-{uuid4().hex[:10].upper()}",
            run_id=run_id,
            agent_id=scope.agent_id,
            tool_name=tool_name,
            arguments=args,
            allowed=True,
            timestamp_utc=now_utc,
            evidence_ids=evidence_ids,
        )
        self._repository.save_tool_call(record)
        self._repository.append_audit(
            actor_id=scope.agent_id,
            actor_role=scope.role.value,
            action=f"TOOL_CALL:{tool_name}",
            outcome="ALLOWED",
            policy_version=self._policy_version,
            run_id=run_id,
            entity_type="tool_call",
            entity_id=record.call_id,
            evidence_ids=evidence_ids,
            payload={"tool_name": tool_name, "arguments": args},
            timestamp_utc=now_utc,
        )
        self._event_bus.publish(
            event_type="tool.invoked",
            policy_version=self._policy_version,
            run_id=run_id,
            payload={
                "call_id": record.call_id,
                "agent_id": scope.agent_id,
                "tool_name": tool_name,
                "evidence_ids": evidence_ids,
            },
        )
        return ToolExecutionResult(data=data, evidence_items=evidence, call_record=record)

    def _scan_malicious_arguments(self, args: dict[str, Any]) -> list[str]:
        hits: list[str] = []
        for key, value in args.items():
            for text in (str(key), str(value)):
                for name, pattern in MALICIOUS_ARG_PATTERNS:
                    if pattern.search(text):
                        hits.append(f"{name}({key})")
        return sorted(set(hits))

    def _deny(
        self,
        *,
        run_id: str,
        scope: AgentPermissionScope,
        tool_name: str,
        arguments: dict[str, Any],
        code: str,
        message: str,
        now_utc: Any,
    ) -> ToolExecutionResult:
        record = ToolCallRecord(
            call_id=f"TC-{uuid4().hex[:10].upper()}",
            run_id=run_id,
            agent_id=scope.agent_id,
            tool_name=tool_name,
            arguments=arguments,
            allowed=False,
            error_code=code,
            timestamp_utc=now_utc,
            evidence_ids=[],
        )
        self._repository.save_tool_call(record)
        self._repository.append_audit(
            actor_id=scope.agent_id,
            actor_role=scope.role.value,
            action=f"TOOL_CALL:{tool_name}",
            outcome="DENIED",
            policy_version=self._policy_version,
            run_id=run_id,
            entity_type="tool_call",
            entity_id=record.call_id,
            payload={"tool_name": tool_name, "arguments": arguments, "error_code": code, "reason": message},
            timestamp_utc=now_utc,
        )
        self._event_bus.publish(
            event_type="tool.denied",
            policy_version=self._policy_version,
            run_id=run_id,
            payload={
                "call_id": record.call_id,
                "agent_id": scope.agent_id,
                "tool_name": tool_name,
                "error_code": code,
            },
        )
        raise ToolAccessError(code, message, details={"tool_name": tool_name, "agent_id": scope.agent_id})

    def _exec_get_quote(self, run_id: str, symbol: str, now_utc: Any) -> tuple[Any, list[EvidenceItem]]:
        quote = self._market_data.get_quote(symbol)
        if quote is None:
            raise ToolAccessError("QUOTE_NOT_FOUND", f"No quote available for symbol '{symbol}'.")
        ev = EvidenceItem(
            evidence_id=f"EV-Q-{uuid4().hex[:8].upper()}",
            run_id=run_id,
            source=quote.source,
            kind="MARKET_QUOTE",
            symbol=quote.symbol,
            available_at_utc=quote.quote_timestamp_utc,
            captured_at_utc=now_utc,
            content_hash=canonical_hash(quote.model_dump(mode="json")),
            sanitized_summary=(
                f"{quote.symbol} bid={quote.bid} ask={quote.ask} last={quote.last} "
                f"{quote.currency} ts={quote.quote_timestamp_utc.isoformat()}"
            ),
        )
        return quote, [ev]

    def _exec_get_fundamentals(self, run_id: str, symbol: str, now_utc: Any) -> tuple[Any, list[EvidenceItem]]:
        fund = self._market_data.get_fundamentals(symbol)
        if fund is None:
            raise ToolAccessError("FUNDAMENTALS_NOT_FOUND", f"No fundamentals available for symbol '{symbol}'.")
        ev = EvidenceItem(
            evidence_id=f"EV-F-{uuid4().hex[:8].upper()}",
            run_id=run_id,
            source="SYNTHETIC_FUNDAMENTALS",
            kind="FUNDAMENTALS",
            symbol=fund.symbol,
            available_at_utc=fund.available_at_utc,
            captured_at_utc=now_utc,
            content_hash=canonical_hash(fund.model_dump(mode="json")),
            sanitized_summary=(
                f"{fund.symbol} pe={fund.pe_ratio} rev_yoy={fund.revenue_growth_yoy:.3f} "
                f"mom20d={fund.momentum_20d:.3f} vol20d={fund.volatility_20d:.3f}"
            ),
        )
        return fund, [ev]

    def _exec_get_news(self, run_id: str, symbol: str, limit: int, now_utc: Any) -> tuple[Any, list[EvidenceItem]]:
        items = self._market_data.get_news(symbol, limit=limit)
        sanitized_items: list[dict[str, Any]] = []
        evidences: list[EvidenceItem] = []
        for item in items:
            scan = self._injection_guard.inspect(f"{item.headline}\n{item.body}")
            ev = EvidenceItem(
                evidence_id=f"EV-N-{uuid4().hex[:8].upper()}",
                run_id=run_id,
                source=item.source,
                kind="NEWS_ITEM",
                symbol=item.symbol,
                available_at_utc=item.available_at_utc,
                captured_at_utc=now_utc,
                content_hash=canonical_hash(item.model_dump(mode="json")),
                sanitized_summary=scan.sanitized_text[:280],
                tainted_injection_detected=scan.tainted,
                injection_signals=scan.matched_rules,
            )
            evidences.append(ev)
            if scan.tainted:
                self._repository.append_audit(
                    actor_id="PROMPT_INJECTION_GUARD",
                    actor_role="SECURITY_CONTROL",
                    action="PROMPT_INJECTION_DETECTED",
                    outcome="QUARANTINED",
                    policy_version=self._policy_version,
                    run_id=run_id,
                    entity_type="evidence",
                    entity_id=ev.evidence_id,
                    evidence_ids=[ev.evidence_id],
                    payload={
                        "news_id": item.news_id,
                        "source": item.source,
                        "matched_rules": scan.matched_rules,
                    },
                    timestamp_utc=now_utc,
                )
                self._event_bus.publish(
                    event_type="security.prompt_injection_detected",
                    policy_version=self._policy_version,
                    run_id=run_id,
                    payload={
                        "evidence_id": ev.evidence_id,
                        "news_id": item.news_id,
                        "matched_rules": scan.matched_rules,
                    },
                )
            sanitized_items.append(
                {
                    "news_id": item.news_id,
                    "evidence_id": ev.evidence_id,
                    "symbol": item.symbol,
                    "sanitized_headline": self._injection_guard.inspect(item.headline).sanitized_text,
                    "sentiment_score": 0.0 if scan.tainted else item.sentiment_score,
                    "tainted": scan.tainted,
                    "matched_rules": scan.matched_rules,
                    "source": item.source,
                    "published_at_utc": item.published_at_utc.isoformat(),
                }
            )
        return sanitized_items, evidences

    def _exec_get_account_state(self, run_id: str, now_utc: Any) -> tuple[Any, list[EvidenceItem]]:
        account = self._repository.load_account_snapshot() or self._market_data.initial_account
        ev = EvidenceItem(
            evidence_id=f"EV-A-{uuid4().hex[:8].upper()}",
            run_id=run_id,
            source="PAPER_ACCOUNT_LEDGER",
            kind="ACCOUNT_SNAPSHOT",
            symbol=None,
            available_at_utc=account.as_of_utc,
            captured_at_utc=now_utc,
            content_hash=canonical_hash(account.model_dump(mode="json")),
            sanitized_summary=(
                f"account={account.account_id} cash_usd={account.cash_usd} "
                f"positions={len(account.positions)}"
            ),
        )
        return account, [ev]
