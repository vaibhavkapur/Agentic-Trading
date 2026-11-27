"""Synthetic fixture generation, point-in-time validation, splits, and blinded holdout guard."""

from __future__ import annotations

from rarp.data.fixtures import (
    MarketBar,
    generate_synthetic_fixture,
    load_dataset_with_manifest,
    verify_point_in_time_integrity,
)
from rarp.data.splits import (
    ChronologicalSplit,
    HoldoutAccessEvent,
    HoldoutGuard,
    HoldoutReleaseToken,
    build_chronological_splits,
)

__all__ = [
    "ChronologicalSplit",
    "HoldoutAccessEvent",
    "HoldoutGuard",
    "HoldoutReleaseToken",
    "MarketBar",
    "build_chronological_splits",
    "generate_synthetic_fixture",
    "load_dataset_with_manifest",
    "verify_point_in_time_integrity",
]
