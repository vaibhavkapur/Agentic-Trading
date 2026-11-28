"""Prompt-injection defense and untrusted-text quarantine for earnings transcripts.

All transcript text is treated strictly as untrusted data. Any sentence matching
instruction-override, tool-spoofing, exfiltration, or trade-action patterns is
quarantined by replacing its characters with spaces of identical length so that
legitimate surrounding text preserves exact character offsets against the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .contracts import (
    InjectionSeverity,
    PromptInjectionEvent,
    TranscriptSegment,
    stable_id,
)

_INJECTION_RULES: Tuple[Tuple[str, InjectionSeverity, re.Pattern], ...] = (
    (
        "IGNORE_PREVIOUS_INSTRUCTIONS",
        InjectionSeverity.CRITICAL,
        re.compile(
            r"\b(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+"
            r"(?:instructions?|prompts?|rules?|directives?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "SYSTEM_PROMPT_OVERRIDE",
        InjectionSeverity.CRITICAL,
        re.compile(
            r"(?:\[\s*system\s*\]|<\s*system\s*>|\bsystem\s+prompt\s*:|\byou\s+are\s+now\s+(?:a|an)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "TRADE_ACTION_INJECTION",
        InjectionSeverity.CRITICAL,
        re.compile(
            r"\b(?:execute|place|submit|trigger|send)\s+(?:a\s+|an\s+|immediate\s+)?"
            r"(?:buy|sell|market|limit|short|long)\s+(?:order|trade|position)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "POLICY_OR_ABSTENTION_OVERRIDE",
        InjectionSeverity.HIGH,
        re.compile(
            r"\b(?:override|bypass|disable)\s+(?:the\s+)?(?:abstention|verification|policy|guardrails?|safety)\b"
            r"|\bdo\s+not\s+abstain\b",
            re.IGNORECASE,
        ),
    ),
    (
        "FORCED_OUTPUT_DIRECTIVE",
        InjectionSeverity.HIGH,
        re.compile(
            r"\b(?:assistant|agent|model|ai)\s*[:,]?\s*(?:must\s+)?(?:output|report|return|set|emit|declare)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "TOOL_CALL_SPOOFING",
        InjectionSeverity.HIGH,
        re.compile(
            r"(?:<\s*tool_use\s*>|\b(?:call_tool|invoke_tool|function_call)\s*\(|\{\s*\"tool\"\s*:)",
            re.IGNORECASE,
        ),
    ),
    (
        "CREDENTIAL_OR_PROMPT_EXFILTRATION",
        InjectionSeverity.CRITICAL,
        re.compile(
            r"\b(?:reveal|print|dump|exfiltrate|leak)\s+(?:your\s+|the\s+)?"
            r"(?:system\s+prompt|credentials?|api\s+keys?|secrets?|tokens?)\b",
            re.IGNORECASE,
        ),
    ),
)

_SENTENCE_SPLIT_RE = re.compile(
    r"(?<!\bMr)(?<!\bMs)(?<!\bDr)(?<!\bInc)(?<!\bCorp)(?<!\bvs)(?<!\bapprox)(?<!\bNo)"
    r"(?<=[\.\!\?])\s+(?=[A-Z0-9\[\<\"])"
)


def split_sentence_spans(text: str) -> List[Tuple[int, int]]:
    """Split text into (start, end) character spans preserving exact offsets."""
    if not text:
        return []
    spans: List[Tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_SPLIT_RE.finditer(text):
        end = match.start()
        if end > start:
            spans.append((start, end))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


@dataclass(frozen=True)
class SanitizedSegment:
    segment: TranscriptSegment
    sanitized_text: str
    quarantined_spans: Tuple[Tuple[int, int], ...]
    quarantined_text_snippets: Tuple[str, ...]
    fully_quarantined: bool


def scan_and_quarantine_segment(
    segment: TranscriptSegment,
) -> Tuple[SanitizedSegment, List[PromptInjectionEvent]]:
    """Detect prompt injections in a segment and mask offending sentences in place."""
    text = segment.text
    sentence_spans = split_sentence_spans(text)
    if not sentence_spans:
        sentence_spans = [(0, len(text))]

    events: List[PromptInjectionEvent] = []
    quarantined_indices = set()

    for idx, (s_start, s_end) in enumerate(sentence_spans):
        sentence = text[s_start:s_end]
        matched_here: List[Tuple[str, InjectionSeverity, int, int, str]] = []
        for pattern_name, severity, regex in _INJECTION_RULES:
            for m in regex.finditer(sentence):
                abs_start = s_start + m.start()
                abs_end = s_start + m.end()
                matched_here.append(
                    (pattern_name, severity, abs_start, abs_end, text[abs_start:abs_end])
                )
        if matched_here:
            quarantined_indices.add(idx)
            for pattern_name, severity, abs_start, abs_end, snippet in matched_here:
                events.append(
                    PromptInjectionEvent(
                        event_id=stable_id(
                            "inj",
                            [segment.segment_id, pattern_name, abs_start, abs_end],
                        ),
                        segment_id=segment.segment_id,
                        pattern_name=pattern_name,
                        severity=severity,
                        char_start=abs_start,
                        char_end=abs_end,
                        matched_snippet=snippet,
                        action_taken="QUARANTINED_SPAN",
                    )
                )

    if not quarantined_indices:
        return (
            SanitizedSegment(
                segment=segment,
                sanitized_text=text,
                quarantined_spans=(),
                quarantined_text_snippets=(),
                fully_quarantined=False,
            ),
            [],
        )

    chars = list(text)
    q_spans: List[Tuple[int, int]] = []
    q_snippets: List[str] = []
    for idx in sorted(quarantined_indices):
        s_start, s_end = sentence_spans[idx]
        q_spans.append((s_start, s_end))
        q_snippets.append(text[s_start:s_end])
        for pos in range(s_start, s_end):
            chars[pos] = " "

    sanitized_text = "".join(chars)
    fully_quarantined = not sanitized_text.strip()
    if fully_quarantined:
        events = [
            PromptInjectionEvent(
                event_id=e.event_id,
                segment_id=e.segment_id,
                pattern_name=e.pattern_name,
                severity=e.severity,
                char_start=e.char_start,
                char_end=e.char_end,
                matched_snippet=e.matched_snippet,
                action_taken="QUARANTINED_SEGMENT",
            )
            for e in events
        ]

    return (
        SanitizedSegment(
            segment=segment,
            sanitized_text=sanitized_text,
            quarantined_spans=tuple(q_spans),
            quarantined_text_snippets=tuple(q_snippets),
            fully_quarantined=fully_quarantined,
        ),
        events,
    )


def scan_and_quarantine(
    segments: Sequence[TranscriptSegment],
) -> Tuple[Tuple[SanitizedSegment, ...], Tuple[PromptInjectionEvent, ...]]:
    """Scan all segments in order and return sanitized wrappers plus audit events."""
    sanitized_list: List[SanitizedSegment] = []
    all_events: List[PromptInjectionEvent] = []
    for seg in segments:
        san_seg, seg_events = scan_and_quarantine_segment(seg)
        sanitized_list.append(san_seg)
        all_events.extend(seg_events)
    return tuple(sanitized_list), tuple(all_events)
