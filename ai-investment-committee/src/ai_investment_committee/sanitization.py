"""Untrusted retrieved text quarantine and prompt-injection detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

_INJECTION_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    (
        "IGNORE_INSTRUCTIONS",
        re.compile(r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b", re.IGNORECASE),
    ),
    (
        "SYSTEM_OVERRIDE",
        re.compile(r"\b(system\s+override|override\s+system|jailbreak|developer\s+mode)\b", re.IGNORECASE),
    ),
    (
        "RISK_VETO_BYPASS",
        re.compile(
            r"\b(disable|bypass|ignore|override)\s+(the\s+)?(risk\s+)?(veto|policy|limits?|guardrails?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "FORCED_VERDICT_OR_APPROVAL",
        re.compile(
            r"\b(verdict\s*=\s*pass|auto[- ]?approve|bypass\s+human\s+approval|force\s+approval)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "POLICY_MUTATION",
        re.compile(
            r"\bset\s+(max_|min_|allow_live_execution)[a-z0-9_]*\s*=",
            re.IGNORECASE,
        ),
    ),
    (
        "LIVE_ORDER_EXECUTION",
        re.compile(
            r"\b(execute|submit|place|route)\s+(a\s+)?(live|real|production)\s+(order|trade)\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class SanitizedTextResult:
    """Result of inspecting and quarantining an untrusted text snippet."""

    original_text: str
    sanitized_text: str
    injection_detected: bool
    matched_rules: Tuple[str, ...]

    def model_dump(self) -> dict:
        return {
            "sanitized_text": self.sanitized_text,
            "injection_detected": self.injection_detected,
            "matched_rules": list(self.matched_rules),
        }


def sanitize_untrusted_text(raw_text: str) -> SanitizedTextResult:
    """Treat retrieved research text as untrusted data and neutralize instruction-like payloads.

    Matched directive clauses are replaced with an explicit redaction marker while retaining
    inert analytical text as quoted data.
    """
    matched: List[str] = []
    sanitized = raw_text
    for rule_name, pattern in _INJECTION_PATTERNS:
        if pattern.search(sanitized):
            matched.append(rule_name)
            sanitized = pattern.sub(f"[REDACTED_UNTRUSTED_DIRECTIVE:{rule_name}]", sanitized)
    return SanitizedTextResult(
        original_text=raw_text,
        sanitized_text=sanitized,
        injection_detected=bool(matched),
        matched_rules=tuple(matched),
    )
