"""Untrusted-text guardrails for prompt injection and instruction-override detection.

All retrieved macro releases, wire reports, and central bank texts are treated as
untrusted data. Any instruction-like directive embedded in source text is detected,
logged as a typed `UntrustedInstructionFinding`, and either quarantined (masked
with equal-length spaces so character offsets of legitimate citations never drift)
or rejected outright with `UntrustedInstructionError`.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from .errors import UntrustedInstructionError
from .models import MacroRelease, UntrustedInstructionFinding, stable_id

# Ordered security detection rules (rule_id, compiled regex).
_INJECTION_RULES: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    (
        "BRACKETED_SYSTEM_DIRECTIVE",
        re.compile(r"\[(?:SYSTEM|ADMIN|INSTRUCTION|OVERRIDE)[^\]]*\]", re.IGNORECASE),
    ),
    (
        "IGNORE_PREVIOUS_INSTRUCTIONS",
        re.compile(
            r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above|system)\s+instructions[^.\n]*\.?",
            re.IGNORECASE,
        ),
    ),
    (
        "FABRICATE_OR_OVERRIDE_DATA",
        re.compile(
            r"(?:override|fabricate|falsify|spoof)\s+(?:headline|core|cpi|nfp|gdp|consensus|rate|figures?)[^.\n]*\.?",
            re.IGNORECASE,
        ),
    ),
    (
        "UNAUTHORIZED_TRADE_EXECUTION",
        re.compile(
            r"(?:execute|submit|place|send)\s+(?:a\s+)?(?:live\s+)?(?:buy|sell|market|limit|trade)\s+order?[^.\n]*\.?",
            re.IGNORECASE,
        ),
    ),
    (
        "UNAUTHORIZED_BUY_SELL_COMMAND",
        re.compile(
            r"\bexecute\s+(?:BUY|SELL)\s+\d+[^.\n]*\.?",
            re.IGNORECASE,
        ),
    ),
    (
        "PROMPT_LEAK_ATTEMPT",
        re.compile(
            r"(?:reveal|print|dump|exfiltrate)\s+(?:the\s+)?(?:system\s+prompt|credentials|api\s+key)[^.\n]*\.?",
            re.IGNORECASE,
        ),
    ),
)


def _merge_spans(
    matches: List[Tuple[int, int, str, str]],
) -> List[Tuple[int, int, str, str]]:
    """Merge overlapping matched spans deterministically so one bracketed injection isn't double-masked."""
    if not matches:
        return []
    ordered = sorted(matches, key=lambda m: (m[0], -(m[1] - m[0]), m[2]))
    merged: List[Tuple[int, int, str, str]] = [ordered[0]]
    for start, end, rule_id, snippet in ordered[1:]:
        prev_start, prev_end, prev_rule, prev_snippet = merged[-1]
        if start < prev_end:
            # Overlap: extend end if needed, keep primary rule_id
            if end > prev_end:
                merged[-1] = (prev_start, end, prev_rule, prev_snippet)
        else:
            merged.append((start, end, rule_id, snippet))
    return merged


def sanitize_untrusted_release_text(
    release: MacroRelease,
    *,
    mode: str = "quarantine",
) -> Tuple[str, Tuple[UntrustedInstructionFinding, ...]]:
    """Scan release.raw_text for untrusted directives.

    Args:
        release: Archived macro release containing untrusted raw_text.
        mode: "quarantine" (mask spans with spaces preserving offsets) or "reject" (raise).

    Returns:
        Tuple of (sanitized_text, findings).
    """
    raw = release.raw_text
    raw_matches: List[Tuple[int, int, str, str]] = []
    for rule_id, pattern in _INJECTION_RULES:
        for match in pattern.finditer(raw):
            raw_matches.append((match.start(), match.end(), rule_id, match.group(0)))

    merged = _merge_spans(raw_matches)
    if not merged:
        return raw, ()

    action = "rejected" if mode == "reject" else "quarantined"
    findings: List[UntrustedInstructionFinding] = []
    chars = list(raw)
    for start, end, rule_id, _ in merged:
        matched_text = raw[start:end]
        finding = UntrustedInstructionFinding(
            finding_id=stable_id(
                "sec",
                {
                    "release_id": release.release_id,
                    "vintage_id": release.vintage_id,
                    "rule_id": rule_id,
                    "char_start": start,
                    "char_end": end,
                },
            ),
            release_id=release.release_id,
            vintage_id=release.vintage_id,
            rule_id=rule_id,
            matched_text=matched_text,
            char_start=start,
            char_end=end,
            action_taken=action,
        )
        findings.append(finding)
        # Mask with spaces of identical length so all legitimate character offsets remain exact.
        for idx in range(start, end):
            chars[idx] = " "

    if mode == "reject":
        raise UntrustedInstructionError(
            f"Untrusted source instructions detected in release ({release.release_id}, {release.vintage_id})",
            details={
                "release_id": release.release_id,
                "vintage_id": release.vintage_id,
                "findings": [f.to_dict() for f in findings],
            },
        )

    return "".join(chars), tuple(findings)
