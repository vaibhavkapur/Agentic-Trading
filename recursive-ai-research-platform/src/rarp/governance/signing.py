"""Cryptographic HMAC-SHA256 signing and tamper verification for research artifacts."""

from __future__ import annotations

import hmac
import hashlib
import os
import secrets
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from rarp.domain.errors import ArtifactSignatureError
from rarp.domain.types import canonical_json, sha256_json, utc_now_iso


@dataclass(frozen=True)
class SignedResearchArtifact:
    artifact_id: str
    artifact_type: str
    key_id: str
    signed_at_utc: str
    payload: Dict[str, Any]
    payload_sha256: str
    signature_hmac_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SignedResearchArtifact":
        return cls(
            artifact_id=data["artifact_id"],
            artifact_type=data["artifact_type"],
            key_id=data["key_id"],
            signed_at_utc=data["signed_at_utc"],
            payload=dict(data["payload"]),
            payload_sha256=data["payload_sha256"],
            signature_hmac_sha256=data["signature_hmac_sha256"],
        )


class ArtifactSigner:
    """Signs research packages using externally supplied or ephemeral secret keys (never hardcoded)."""

    def __init__(self, secret_key: Optional[str] = None, key_id: str = "ephemeral_local_key") -> None:
        env_key = os.environ.get("RARP_SIGNING_KEY")
        resolved = secret_key or env_key
        if resolved is None:
            resolved = secrets.token_hex(32)
        self._key_bytes = resolved.encode("utf-8")
        self.key_id = key_id

    def _compute_hmac(self, payload_sha256: str, artifact_type: str, key_id: str, signed_at_utc: str) -> str:
        envelope = canonical_json(
            {
                "artifact_type": artifact_type,
                "key_id": key_id,
                "payload_sha256": payload_sha256,
                "signed_at_utc": signed_at_utc,
            }
        ).encode("utf-8")
        return hmac.new(self._key_bytes, envelope, hashlib.sha256).hexdigest()

    def sign(self, artifact_type: str, payload: Dict[str, Any]) -> SignedResearchArtifact:
        payload_hash = sha256_json(payload)
        signed_at = utc_now_iso()
        sig = self._compute_hmac(payload_hash, artifact_type, self.key_id, signed_at)
        artifact_id = f"art_{payload_hash[:12]}"
        return SignedResearchArtifact(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            key_id=self.key_id,
            signed_at_utc=signed_at,
            payload=payload,
            payload_sha256=payload_hash,
            signature_hmac_sha256=sig,
        )

    def verify(self, artifact: SignedResearchArtifact) -> bool:
        expected_hash = sha256_json(artifact.payload)
        if not hmac.compare_digest(expected_hash, artifact.payload_sha256):
            raise ArtifactSignatureError(
                "Artifact payload SHA-256 mismatch (payload has been modified)",
                {"artifact_id": artifact.artifact_id},
            )
        expected_sig = self._compute_hmac(
            artifact.payload_sha256,
            artifact.artifact_type,
            artifact.key_id,
            artifact.signed_at_utc,
        )
        if not hmac.compare_digest(expected_sig, artifact.signature_hmac_sha256):
            raise ArtifactSignatureError(
                "Artifact HMAC-SHA256 signature verification failed",
                {"artifact_id": artifact.artifact_id, "key_id": artifact.key_id},
            )
        return True
