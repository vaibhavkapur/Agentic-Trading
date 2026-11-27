"""Market data fixtures, manifest integrity verification, and chronological split manifests."""

from .fixtures import (
    generate_synthetic_dataset,
    write_dataset_fixture,
    load_dataset_from_manifest,
    compute_file_sha256,
)
from .splits import (
    SplitPolicy,
    FoldSpec,
    SplitManifest,
    HoldoutGuard,
    build_split_manifest,
    verify_split_manifest,
)

__all__ = [
    "generate_synthetic_dataset",
    "write_dataset_fixture",
    "load_dataset_from_manifest",
    "compute_file_sha256",
    "SplitPolicy",
    "FoldSpec",
    "SplitManifest",
    "HoldoutGuard",
    "build_split_manifest",
    "verify_split_manifest",
]
