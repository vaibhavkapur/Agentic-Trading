"""Untrusted-data screening and dataset safety verification.

Treats all dataset text/metadata fields (e.g. description, bar notes) as untrusted
data and rejects datasets containing prompt-injection directives, embedded code
execution payloads, or suspicious control/bidi Unicode characters.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .contracts import CheckResult, DatasetManifest
from .errors import DatasetSafetyError

_SUSPICIOUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "prompt_injection_override",
        re.compile(
            r"\b(ignore|disregard|forget|override)\s+(all\s+)?(previous|prior|system|above)\s+(instructions|rules|prompts?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_injection_role",
        re.compile(
            r"\b(system\s*prompt|you\s+are\s+now|act\s+as\s+root|bypass\s+sandbox|disable\s+security)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "code_execution_payload",
        re.compile(
            r"(__import__|eval\s*\(|exec\s*\(|os\.system|subprocess\.|socket\.|curl\s+http|wget\s+http|rm\s+-rf)",
            re.IGNORECASE,
        ),
    ),
    (
        "credential_exfiltration_directive",
        re.compile(
            r"\b(exfiltrate|send\s+secrets|dump\s+env|broker_api_key|api_secret|private_key)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "delimiter_injection",
        re.compile(r"(</?system>|<\|im_start\|>|<\|endoftext\|>|```python)", re.IGNORECASE),
    ),
]

_BIDI_AND_INVISIBLE_CATEGORIES = {"Cf", "Cc"}


@dataclass(frozen=True)
class DatasetFinding:
    location: str
    rule: str
    snippet: str


def _scan_text(text: str, location: str) -> list[DatasetFinding]:
    findings: list[DatasetFinding] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in _BIDI_AND_INVISIBLE_CATEGORIES and ch not in ("\n", "\r", "\t"):
            findings.append(
                DatasetFinding(
                    location=location,
                    rule="suspicious_control_or_bidi_char",
                    snippet=f"U+{ord(ch):04X}",
                )
            )
            break

    for rule_name, pattern in _SUSPICIOUS_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(
                DatasetFinding(
                    location=location,
                    rule=rule_name,
                    snippet=match.group(0)[:80],
                )
            )
    return findings


def scan_dataset_safety(dataset: DatasetManifest) -> CheckResult:
    """Inspect a validated DatasetManifest for malicious instructions or unsafe metadata."""
    findings: list[DatasetFinding] = []

    if dataset.description:
        findings.extend(_scan_text(dataset.description, "dataset.description"))

    for idx, bar in enumerate(dataset.bars):
        if bar.note:
            findings.extend(_scan_text(bar.note, f"bars[{idx}].note"))

    if findings:
        return CheckResult(
            name="dataset_safety",
            passed=False,
            code="MALICIOUS_INSTRUCTIONS_DETECTED",
            message=f"Rejected dataset '{dataset.dataset_id}': detected {len(findings)} unsafe instruction/payload pattern(s).",
            details={
                "dataset_id": dataset.dataset_id,
                "finding_count": len(findings),
                "findings": [
                    {"location": f.location, "rule": f.rule, "snippet": f.snippet}
                    for f in findings[:10]
                ],
            },
        )

    return CheckResult(
        name="dataset_safety",
        passed=True,
        code="OK",
        message=f"Dataset '{dataset.dataset_id}' ({len(dataset.bars)} bars) passed integrity and untrusted-text screening.",
        details={
            "dataset_id": dataset.dataset_id,
            "bar_count": len(dataset.bars),
            "sha256": dataset.sha256,
        },
    )


def assert_dataset_safe(dataset: DatasetManifest) -> CheckResult:
    """Scan dataset and raise DatasetSafetyError if any malicious pattern is found."""
    result = scan_dataset_safety(dataset)
    if not result.passed:
        raise DatasetSafetyError(result.message, details=result.details)
    return result
