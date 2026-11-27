"""Prompt injection scanner/sanitizer and shared agent base utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("IGNORE_INSTRUCTIONS", re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions")),
    ("SYSTEM_OVERRIDE", re.compile(r"(?i)(system\s+override|you\s+are\s+now\s+authorized|role:\s*system)")),
    ("BYPASS_APPROVAL", re.compile(r"(?i)(bypass\s+(human\s+)?approval|skip\s+approval|auto[- ]?approve)")),
    ("OVERRIDE_RISK", re.compile(r"(?i)(override\s+risk|disable\s+risk|ignore\s+risk\s+limits)")),
    ("DIRECT_ORDER_EXECUTION", re.compile(r"(?i)(submit_order\s*\(|place_order\s*\(|execution_mode\s*=\s*live)")),
    ("PRIVILEGE_ESCALATION", re.compile(r"(?i)(system_admin|grant\s+admin|elevate\s+privileges)")),
]


@dataclass(frozen=True)
class InjectionScanResult:
    tainted: bool
    matched_rules: list[str]
    sanitized_text: str


class PromptInjectionGuard:
    """Deterministic untrusted-data scanner that quarantines adversarial instructions in external feeds."""

    def inspect(self, text: str) -> InjectionScanResult:
        matched: list[str] = []
        sanitized = text
        for rule_name, pattern in INJECTION_PATTERNS:
            if pattern.search(text):
                matched.append(rule_name)
                sanitized = pattern.sub(f"[REDACTED:{rule_name}]", sanitized)
        cleaned = " ".join(sanitized.split())
        if matched:
            cleaned = f"[UNTRUSTED_DATA_QUARANTINED:{','.join(matched)}] {cleaned}"
        return InjectionScanResult(
            tainted=bool(matched),
            matched_rules=matched,
            sanitized_text=cleaned,
        )
