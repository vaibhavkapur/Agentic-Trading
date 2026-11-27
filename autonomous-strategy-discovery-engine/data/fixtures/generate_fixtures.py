#!/usr/bin/env python3
"""Deterministically regenerate the permitted synthetic dataset fixtures."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from asde.data.fixtures import generate_synthetic_dataset, write_dataset_fixture


def main() -> None:
    out_dir = ROOT / "data" / "fixtures"
    dataset = generate_synthetic_dataset(seed=20260401, num_bars=1800, regime="multi_regime")
    manifest_path = write_dataset_fixture(dataset, out_dir)
    print(f"Wrote synthetic fixture manifest: {manifest_path}")


if __name__ == "__main__":
    main()
