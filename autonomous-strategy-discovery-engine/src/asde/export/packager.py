"""Auditable strategy package exporter with exact config and dataset fingerprints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from asde import __version__ as ENGINE_VERSION
from asde.dsl.schema import StrategySpec
from asde.errors import ManifestIntegrityError
from asde.export.review import ReviewDecision, ReviewGate
from asde.types import sha256_canonical


class StrategyPackager:
    """Exports deterministic, cryptographically verified strategy review packages."""

    def __init__(self, review_gate: Optional[ReviewGate] = None) -> None:
        self.review_gate = review_gate or ReviewGate()

    def export_candidate(
        self,
        *,
        out_dir: Path,
        run_id: str,
        spec: StrategySpec,
        config_snapshot: Dict[str, Any],
        dataset_manifest: Dict[str, Any],
        dataset_fingerprint: str,
        split_manifest: Dict[str, Any],
        catalog_fingerprint: str,
        primary_cost_scenario: str,
        cost_scenario_hash: str,
        evaluation_evidence: Dict[str, Any],
        seed: int,
    ) -> Path:
        """Write a self-contained strategy package directory with SHA-256 provenance."""
        pkg_dir = Path(out_dir) / f"{spec.strategy_id}"
        pkg_dir.mkdir(parents=True, exist_ok=True)

        spec_dict = spec.to_dict()
        spec_hash = sha256_canonical(spec_dict)
        config_hash = sha256_canonical(config_snapshot)
        evidence_hash = sha256_canonical(evaluation_evidence)

        review_record: Dict[str, Any] = {
            "review_status": "PENDING_INDEPENDENT_REVIEW",
            "deployment_target": "research_only",
            "order_execution_enabled": False,
            "paper_execution_permitted": False,
            "live_execution_permitted": False,
            "decision": None,
            "policy_checks_passed": evaluation_evidence.get("governance_status") == "ELIGIBLE_FOR_REVIEW",
            "policy_failures": list(evaluation_evidence.get("rejection_reasons", [])),
        }

        manifest_payload: Dict[str, Any] = {
            "package_schema_version": "1.0.0",
            "engine_version": ENGINE_VERSION,
            "produced_by": "asde_engine",
            "run_id": run_id,
            "strategy_id": spec.strategy_id,
            "family": spec.family,
            "seed": seed,
            "config_fingerprint": config_hash,
            "catalog_fingerprint": catalog_fingerprint,
            "dataset_id": dataset_manifest.get("dataset_id"),
            "dataset_fingerprint": dataset_fingerprint,
            "dataset_data_sha256": dataset_manifest.get("data_sha256"),
            "split_manifest_hash": split_manifest["manifest_hash"],
            "primary_cost_scenario": primary_cost_scenario,
            "cost_scenario_hash": cost_scenario_hash,
            "strategy_spec_sha256": spec_hash,
            "evaluation_evidence_sha256": evidence_hash,
            "order_execution_enabled": False,
            "live_execution_permitted": False,
            "files": [
                "strategy_spec.json",
                "config_snapshot.json",
                "dataset_manifest.json",
                "split_manifest.json",
                "evaluation_evidence.json",
                "review_record.json",
            ],
        }
        manifest_payload["package_fingerprint"] = sha256_canonical(manifest_payload)

        (pkg_dir / "strategy_spec.json").write_text(
            json.dumps(spec_dict, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (pkg_dir / "config_snapshot.json").write_text(
            json.dumps(config_snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (pkg_dir / "dataset_manifest.json").write_text(
            json.dumps(dataset_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (pkg_dir / "split_manifest.json").write_text(
            json.dumps(split_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (pkg_dir / "evaluation_evidence.json").write_text(
            json.dumps(evaluation_evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (pkg_dir / "review_record.json").write_text(
            json.dumps(review_record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (pkg_dir / "package_manifest.json").write_text(
            json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return pkg_dir

    def apply_independent_review(
        self,
        *,
        package_dir: Path,
        decision: ReviewDecision,
    ) -> Dict[str, Any]:
        """Verify package integrity, enforce review gate, and persist review outcome."""
        pkg_dir = Path(package_dir)
        manifest = verify_package(pkg_dir)
        evidence = json.loads((pkg_dir / "evaluation_evidence.json").read_text(encoding="utf-8"))
        updated_review = self.review_gate.evaluate_review(
            package_manifest=manifest,
            evaluation_evidence=evidence,
            decision=decision,
        )
        (pkg_dir / "review_record.json").write_text(
            json.dumps(updated_review, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return updated_review


def verify_package(package_dir: Path) -> Dict[str, Any]:
    """Cryptographically verify all artifacts and fingerprints in an exported strategy package."""
    pkg_dir = Path(package_dir)
    manifest_path = pkg_dir / "package_manifest.json"
    if not manifest_path.exists():
        raise ManifestIntegrityError(f"Missing package_manifest.json in {pkg_dir}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded_fp = manifest.get("package_fingerprint")
    payload = {k: v for k, v in manifest.items() if k != "package_fingerprint"}
    actual_fp = sha256_canonical(payload)
    if recorded_fp != actual_fp:
        raise ManifestIntegrityError(
            "Package manifest fingerprint mismatch.",
            details={"expected": recorded_fp, "actual": actual_fp},
        )

    for fname in manifest.get("files", []):
        if not (pkg_dir / fname).exists():
            raise ManifestIntegrityError(f"Missing required package file: {fname}")

    spec_obj = json.loads((pkg_dir / "strategy_spec.json").read_text(encoding="utf-8"))
    if sha256_canonical(spec_obj) != manifest["strategy_spec_sha256"]:
        raise ManifestIntegrityError("strategy_spec.json hash mismatch.")

    cfg_obj = json.loads((pkg_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    if sha256_canonical(cfg_obj) != manifest["config_fingerprint"]:
        raise ManifestIntegrityError("config_snapshot.json hash mismatch.")

    ev_obj = json.loads((pkg_dir / "evaluation_evidence.json").read_text(encoding="utf-8"))
    if sha256_canonical(ev_obj) != manifest["evaluation_evidence_sha256"]:
        raise ManifestIntegrityError("evaluation_evidence.json hash mismatch.")

    return manifest
