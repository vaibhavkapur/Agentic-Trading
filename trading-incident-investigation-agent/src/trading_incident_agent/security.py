"""Untrusted telemetry sanitization: secret redaction and prompt-injection quarantine."""

from __future__ import annotations

import re
from typing import Any

from trading_incident_agent.models import EventSource, SanitizationFinding

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE)),
    ("api_key_assignment", re.compile(r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{8,}['\"]?")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_instructions",
        re.compile(r"(?i)ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions[^.\n]*\.?"),
    ),
    (
        "system_override",
        re.compile(
            r"(?i)(?:system\s+override|you\s+are\s+now\s+an?\s+autonomous|reveal\s+system\s+prompt)[^.\n]*\.?"
        ),
    ),
    (
        "policy_bypass",
        re.compile(
            r"(?i)(?:auto_approve\s*=\s*true|bypass\s+approval(?:\s+policy)?|disable_risk_(?:checks|limits))[^.\n]*\.?"
        ),
    ),
    (
        "unauthorized_tool_directive",
        re.compile(
            r"(?i)(?:immediately\s+execute|call\s+disable_risk|cancel_all_orders)[^.\n]*\.?"
        ),
    ),
]


def _mask_excerpt(raw: str, max_len: int = 48) -> str:
    compact = " ".join(raw.split())
    if len(compact) <= max_len:
        return compact[:12] + "...[MASKED]" if len(compact) > 12 else "[MASKED]"
    return compact[:16] + "...[MASKED]"


def sanitize_text(
    text: str,
    *,
    source_type: EventSource,
    source_id: str,
    finding_counter: list[int],
) -> tuple[str, list[SanitizationFinding], bool, bool]:
    """Redact secrets and quarantine prompt-injection directives in untrusted telemetry text.

    Returns:
        (sanitized_text, findings, injection_detected, redacted)
    """
    sanitized = text
    findings: list[SanitizationFinding] = []
    redacted = False
    injection_detected = False

    # 1. Secret redaction first so secrets never appear in injection findings or logs.
    for pattern_name, regex in SECRET_PATTERNS:
        matches = list(regex.finditer(sanitized))
        for m in matches:
            finding_counter[0] += 1
            redacted = True
            findings.append(
                SanitizationFinding(
                    finding_id=f"SEC-{finding_counter[0]:04d}",
                    source_type=source_type,
                    source_id=source_id,
                    category="secret_redaction",
                    pattern_name=pattern_name,
                    matched_excerpt_redacted=_mask_excerpt(m.group(0)),
                    action_taken=f"Replaced secret matching '{pattern_name}' with [REDACTED:{pattern_name}]",
                )
            )
        if matches:
            sanitized = regex.sub(f"[REDACTED:{pattern_name}]", sanitized)

    # 2. Prompt injection detection & directive quarantine.
    matched_injection_patterns: list[str] = []
    matched_snippets: list[str] = []
    for pattern_name, regex in INJECTION_PATTERNS:
        matches = list(regex.finditer(sanitized))
        if matches:
            injection_detected = True
            matched_injection_patterns.append(pattern_name)
            matched_snippets.append(matches[0].group(0))
            sanitized = regex.sub("[QUARANTINED_UNTRUSTED_DIRECTIVE]", sanitized)

    if injection_detected:
        finding_counter[0] += 1
        findings.append(
            SanitizationFinding(
                finding_id=f"SEC-{finding_counter[0]:04d}",
                source_type=source_type,
                source_id=source_id,
                category="prompt_injection",
                pattern_name=",".join(matched_injection_patterns),
                matched_excerpt_redacted=_mask_excerpt(matched_snippets[0]),
                action_taken="Quarantined untrusted instruction directive; preserved technical telemetry only",
            )
        )

    # Collapse repeated quarantine markers cleanly.
    sanitized = re.sub(
        r"(?:\[QUARANTINED_UNTRUSTED_DIRECTIVE\]\s*){2,}",
        "[QUARANTINED_UNTRUSTED_DIRECTIVE] ",
        sanitized,
    ).strip()
    return sanitized, findings, injection_detected, redacted


def sanitize_attributes(
    attributes: dict[str, Any],
    *,
    source_type: EventSource,
    source_id: str,
    finding_counter: list[int],
) -> tuple[dict[str, Any], list[SanitizationFinding], bool, bool]:
    """Sanitize string values inside telemetry attribute dictionaries."""
    clean: dict[str, Any] = {}
    findings: list[SanitizationFinding] = []
    any_injection = False
    any_redacted = False

    for key, val in attributes.items():
        if isinstance(val, str):
            sanitized_val, val_findings, inj, red = sanitize_text(
                val,
                source_type=source_type,
                source_id=source_id,
                finding_counter=finding_counter,
            )
            clean[key] = sanitized_val
            findings.extend(val_findings)
            any_injection = any_injection or inj
            any_redacted = any_redacted or red
        elif isinstance(val, dict):
            nested_clean, nested_findings, inj, red = sanitize_attributes(
                val,
                source_type=source_type,
                source_id=source_id,
                finding_counter=finding_counter,
            )
            clean[key] = nested_clean
            findings.extend(nested_findings)
            any_injection = any_injection or inj
            any_redacted = any_redacted or red
        else:
            clean[key] = val

    return clean, findings, any_injection, any_redacted
