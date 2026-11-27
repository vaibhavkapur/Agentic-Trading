"""Immutable run registry, object storage adapter, and research memory with trial accounting."""

from __future__ import annotations

from rarp.registry.memory import (
    HypothesisMemoryEntry,
    NoveltyCheckResult,
    ResearchMemory,
    TrialAccountingStats,
    compute_trial_adjusted_stats,
)
from rarp.registry.store import (
    LocalObjectStore,
    ObjectStore,
    RunRecord,
    RunRegistry,
)

__all__ = [
    "HypothesisMemoryEntry",
    "LocalObjectStore",
    "NoveltyCheckResult",
    "ObjectStore",
    "ResearchMemory",
    "RunRecord",
    "RunRegistry",
    "TrialAccountingStats",
    "compute_trial_adjusted_stats",
]
