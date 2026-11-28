"""Role-isolated read-only mock toolkits with fixed budget and timeout enforcement."""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from .errors import (
    AgentTimeoutError,
    BudgetExceededError,
    NoExecutionCapabilityError,
    ToolAccessDeniedError,
)
from .models import (
    AgentBudget,
    AgentExecutionTrace,
    Claim,
    CommitteeProposal,
    ThesisRecord,
    ToolCallTrace,
)
from .risk_engine import audit_claims, compute_pro_forma_metrics
from .sanitization import sanitize_untrusted_text

FORBIDDEN_EXECUTION_TOOLS: FrozenSet[str] = frozenset(
    {
        "submit_order",
        "execute_order",
        "route_live_order",
        "place_trade",
        "override_risk_veto",
        "mutate_risk_policy",
        "bypass_human_approval",
    }
)

ROLE_ALLOWED_TOOLS: Dict[str, Tuple[str, ...]] = {
    "bull": ("get_candidate_position", "get_research_briefs", "search_evidence"),
    "bear": (
        "get_candidate_position",
        "get_research_briefs",
        "search_evidence",
        "inspect_thesis_claims",
    ),
    "portfolio": (
        "get_candidate_position",
        "get_portfolio_state",
        "compute_pro_forma_exposure",
    ),
    "risk": (
        "get_candidate_position",
        "get_portfolio_state",
        "get_risk_policy",
        "compute_pro_forma_exposure",
        "verify_evidence_citations",
    ),
}

_TOOL_ESTIMATES: Dict[str, Tuple[int, int, float]] = {
    # tool_name -> (latency_ms, tokens_used, cost_usd)
    "get_candidate_position": (12, 60, 0.0006),
    "get_research_briefs": (28, 180, 0.0018),
    "search_evidence": (20, 120, 0.0012),
    "inspect_thesis_claims": (15, 110, 0.0011),
    "get_portfolio_state": (18, 130, 0.0013),
    "compute_pro_forma_exposure": (22, 95, 0.0009),
    "get_risk_policy": (10, 70, 0.0007),
    "verify_evidence_citations": (25, 100, 0.0010),
}


class RoleToolSandbox:
    """Per-agent isolated tool execution sandbox enforcing permissions and fixed budgets."""

    def __init__(
        self,
        *,
        role: str,
        proposal: CommitteeProposal,
        budget: AgentBudget,
        thesis: Optional[ThesisRecord] = None,
        claims_for_audit: Optional[Sequence[Claim]] = None,
        extra_latency_ms: int = 0,
    ) -> None:
        if role not in ROLE_ALLOWED_TOOLS:
            raise ToolAccessDeniedError(f"Unknown agent role '{role}'")
        self.role = role
        self.proposal = proposal
        self.budget = budget
        self.allowed_tools = ROLE_ALLOWED_TOOLS[role]
        self._thesis = thesis
        self._claims_for_audit = tuple(claims_for_audit or ())
        self._extra_latency_ms = max(0, int(extra_latency_ms))

        self._tool_calls_used = 0
        self._tokens_used = 0
        self._latency_ms = 0
        self._cost_usd = 0.0
        self._traces: List[ToolCallTrace] = []
        self._injection_flags: List[str] = []

    def charge_reasoning_budget(self, *, tokens: int, latency_ms: int, cost_usd: float) -> None:
        """Account for model/reasoning token, latency, and cost usage within fixed budgets."""
        total_latency = latency_ms + self._extra_latency_ms
        if self._latency_ms + total_latency > self.budget.max_latency_ms:
            raise AgentTimeoutError(
                f"Agent '{self.role}' timed out: latency {self._latency_ms + total_latency}ms > limit {self.budget.max_latency_ms}ms",
                details={
                    "role": self.role,
                    "latency_ms": self._latency_ms + total_latency,
                    "max_latency_ms": self.budget.max_latency_ms,
                },
            )
        if self._tokens_used + tokens > self.budget.max_tokens:
            raise BudgetExceededError(
                f"Agent '{self.role}' exceeded token budget ({self._tokens_used + tokens} > {self.budget.max_tokens})",
                details={
                    "role": self.role,
                    "tokens_used": self._tokens_used + tokens,
                    "max_tokens": self.budget.max_tokens,
                },
            )
        if round(self._cost_usd + cost_usd, 6) > self.budget.max_cost_usd:
            raise BudgetExceededError(
                f"Agent '{self.role}' exceeded USD budget ({self._cost_usd + cost_usd:.6f} > {self.budget.max_cost_usd:.6f})",
                details={
                    "role": self.role,
                    "cost_usd": round(self._cost_usd + cost_usd, 6),
                    "max_cost_usd": self.budget.max_cost_usd,
                },
            )
        self._tokens_used += tokens
        self._latency_ms += total_latency
        self._cost_usd = round(self._cost_usd + cost_usd, 6)

    def invoke(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Invoke an isolated read-only tool, enforcing permissions and budget bounds."""
        args = dict(arguments or {})
        if tool_name in FORBIDDEN_EXECUTION_TOOLS:
            raise NoExecutionCapabilityError(
                f"Agent '{self.role}' attempted forbidden capability '{tool_name}'. No execution or policy override capability exists.",
                details={"role": self.role, "tool_name": tool_name},
            )
        if tool_name not in self.allowed_tools:
            raise ToolAccessDeniedError(
                f"Agent '{self.role}' is not permitted to invoke tool '{tool_name}' (allowed: {list(self.allowed_tools)})",
                details={
                    "role": self.role,
                    "tool_name": tool_name,
                    "allowed_tools": list(self.allowed_tools),
                },
            )

        if self._tool_calls_used + 1 > self.budget.max_tool_calls:
            raise BudgetExceededError(
                f"Agent '{self.role}' exceeded max_tool_calls ({self.budget.max_tool_calls})",
                details={"role": self.role, "max_tool_calls": self.budget.max_tool_calls},
            )

        est_latency, est_tokens, est_cost = _TOOL_ESTIMATES[tool_name]
        if self._latency_ms + est_latency > self.budget.max_latency_ms:
            raise AgentTimeoutError(
                f"Agent '{self.role}' timed out calling '{tool_name}' ({self._latency_ms + est_latency}ms > {self.budget.max_latency_ms}ms)",
                details={
                    "role": self.role,
                    "tool_name": tool_name,
                    "latency_ms": self._latency_ms + est_latency,
                    "max_latency_ms": self.budget.max_latency_ms,
                },
            )
        if self._tokens_used + est_tokens > self.budget.max_tokens:
            raise BudgetExceededError(
                f"Agent '{self.role}' exceeded max_tokens calling '{tool_name}'",
                details={"role": self.role, "max_tokens": self.budget.max_tokens},
            )
        if round(self._cost_usd + est_cost, 6) > self.budget.max_cost_usd:
            raise BudgetExceededError(
                f"Agent '{self.role}' exceeded max_cost_usd calling '{tool_name}'",
                details={"role": self.role, "max_cost_usd": self.budget.max_cost_usd},
            )

        result = self._dispatch(tool_name, args)

        self._tool_calls_used += 1
        self._tokens_used += est_tokens
        self._latency_ms += est_latency
        self._cost_usd = round(self._cost_usd + est_cost, 6)
        self._traces.append(
            ToolCallTrace(
                role=self.role,
                tool_name=tool_name,
                arguments=args,
                status="OK",
                latency_ms=est_latency,
                tokens_used=est_tokens,
                cost_usd=est_cost,
            )
        )
        return result

    def _dispatch(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "get_candidate_position":
            return {"candidate_position": self.proposal.candidate_position.model_dump()}

        if tool_name == "get_research_briefs":
            stance_filter = args.get("stance")
            briefs_payload: List[Dict[str, Any]] = []
            for brief in self.proposal.research_briefs:
                if stance_filter and brief.stance_hint != stance_filter:
                    continue
                sanitized_snippets = []
                for snip in brief.snippets:
                    san = sanitize_untrusted_text(snip.text)
                    if san.injection_detected:
                        for rule in san.matched_rules:
                            flag = f"{snip.evidence_id}:{rule}"
                            if flag not in self._injection_flags:
                                self._injection_flags.append(flag)
                    sanitized_snippets.append(
                        {
                            "evidence_id": snip.evidence_id,
                            "untrusted_data": True,
                            "text": san.sanitized_text,
                            "injection_detected": san.injection_detected,
                            "matched_rules": list(san.matched_rules),
                            "metric_name": snip.metric_name,
                            "metric_value": snip.metric_value,
                            "unit": snip.unit,
                        }
                    )
                briefs_payload.append(
                    {
                        "brief_id": brief.brief_id,
                        "title": brief.title,
                        "source": brief.source,
                        "published_at": brief.published_at,
                        "stance_hint": brief.stance_hint,
                        "untrusted_data": True,
                        "snippets": sanitized_snippets,
                    }
                )
            return {"briefs": briefs_payload, "injection_flags": list(self._injection_flags)}

        if tool_name == "search_evidence":
            query = str(args.get("query", "")).lower().strip()
            matches = []
            for brief in self.proposal.research_briefs:
                for snip in brief.snippets:
                    san = sanitize_untrusted_text(snip.text)
                    if san.injection_detected:
                        for rule in san.matched_rules:
                            flag = f"{snip.evidence_id}:{rule}"
                            if flag not in self._injection_flags:
                                self._injection_flags.append(flag)
                    if not query or query in san.sanitized_text.lower() or query in brief.stance_hint:
                        matches.append(
                            {
                                "brief_id": brief.brief_id,
                                "stance_hint": brief.stance_hint,
                                "evidence_id": snip.evidence_id,
                                "untrusted_data": True,
                                "text": san.sanitized_text,
                                "injection_detected": san.injection_detected,
                            }
                        )
            return {"matches": matches}

        if tool_name == "inspect_thesis_claims":
            if self._thesis is None:
                return {"thesis_claims": []}
            return {
                "thesis_summary": self._thesis.summary,
                "thesis_claims": [c.model_dump() for c in self._thesis.claims],
            }

        if tool_name == "get_portfolio_state":
            return {"portfolio_state": self.proposal.portfolio_state.model_dump()}

        if tool_name == "compute_pro_forma_exposure":
            return {"pro_forma_metrics": compute_pro_forma_metrics(self.proposal)}

        if tool_name == "get_risk_policy":
            return {"risk_policy": self.proposal.risk_policy.model_dump()}

        if tool_name == "verify_evidence_citations":
            audited, summary = audit_claims(self.proposal, self._claims_for_audit)
            return {
                "audited_claims": [c.model_dump() for c in audited],
                "audit_summary": summary,
            }

        raise ToolAccessDeniedError(f"Unhandled tool '{tool_name}'")

    def build_trace(self) -> AgentExecutionTrace:
        return AgentExecutionTrace(
            role=self.role,
            allowed_tools=self.allowed_tools,
            budget=self.budget,
            tool_calls_used=self._tool_calls_used,
            tokens_used=self._tokens_used,
            latency_ms=self._latency_ms,
            cost_usd=self._cost_usd,
            tool_calls=tuple(self._traces),
            injection_attempts_flagged=tuple(self._injection_flags),
        )
