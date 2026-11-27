"""Chronological train/validation/holdout splits with embargo gaps and blinded HoldoutGuard."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from rarp.data.fixtures import MarketBar
from rarp.domain.dsl import SplitSpec
from rarp.domain.errors import HoldoutAccessError, RARPValidationError
from rarp.domain.types import sha256_json, utc_now_iso


@dataclass(frozen=True)
class ChronologicalSplit:
    train: Dict[str, List[MarketBar]]
    validation: Dict[str, List[MarketBar]]
    holdout: Dict[str, List[MarketBar]]
    embargo_bars: int
    train_range_utc: tuple[str, str]
    validation_range_utc: tuple[str, str]
    holdout_range_utc: tuple[str, str]
    split_sha256: str


@dataclass(frozen=True)
class HoldoutReleaseToken:
    token_id: str
    hypothesis_id: str
    proposer_id: str
    reviewer_id: str
    issued_at_utc: str
    reason: str
    signature: str


@dataclass(frozen=True)
class HoldoutAccessEvent:
    timestamp_utc: str
    caller_id: str
    purpose: str
    granted: bool
    reason: str
    token_id: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def build_chronological_splits(
    bars_by_symbol: Dict[str, List[MarketBar]],
    spec: SplitSpec,
) -> ChronologicalSplit:
    """Create strict chronological train / embargo / validation / embargo / holdout splits."""
    spec.validate()
    if not bars_by_symbol:
        raise RARPValidationError("Cannot split empty dataset")

    lengths = {sym: len(bars) for sym, bars in bars_by_symbol.items()}
    min_len = min(lengths.values())
    if min_len < 30 + 2 * spec.embargo_bars:
        raise RARPValidationError(
            f"Insufficient bars ({min_len}) for chronological split with embargo={spec.embargo_bars}"
        )

    usable = min_len - 2 * spec.embargo_bars
    n_train = max(10, int(usable * spec.train_ratio))
    n_val = max(10, int(usable * spec.validation_ratio))
    n_hold = usable - n_train - n_val
    if n_hold < 10:
        raise RARPValidationError(f"Holdout split too small ({n_hold} bars)")

    train_start, train_end = 0, n_train
    val_start = train_end + spec.embargo_bars
    val_end = val_start + n_val
    hold_start = val_end + spec.embargo_bars
    hold_end = hold_start + n_hold

    train: Dict[str, List[MarketBar]] = {}
    val: Dict[str, List[MarketBar]] = {}
    hold: Dict[str, List[MarketBar]] = {}
    for sym, bars in sorted(bars_by_symbol.items()):
        train[sym] = list(bars[train_start:train_end])
        val[sym] = list(bars[val_start:val_end])
        hold[sym] = list(bars[hold_start:hold_end])

    ref_sym = sorted(bars_by_symbol.keys())[0]
    train_range = (train[ref_sym][0].event_time_utc, train[ref_sym][-1].event_time_utc)
    val_range = (val[ref_sym][0].event_time_utc, val[ref_sym][-1].event_time_utc)
    hold_range = (hold[ref_sym][0].event_time_utc, hold[ref_sym][-1].event_time_utc)

    split_hash = sha256_json(
        {
            "embargo_bars": spec.embargo_bars,
            "train_range": list(train_range),
            "validation_range": list(val_range),
            "holdout_range": list(hold_range),
            "symbols": sorted(bars_by_symbol.keys()),
            "counts": {"train": n_train, "validation": n_val, "holdout": n_hold},
        }
    )

    return ChronologicalSplit(
        train=train,
        validation=val,
        holdout=hold,
        embargo_bars=spec.embargo_bars,
        train_range_utc=train_range,
        validation_range_utc=val_range,
        holdout_range_utc=hold_range,
        split_sha256=split_hash,
    )


class HoldoutGuard:
    """Blinded holdout boundary preventing automated search loops from peeking at holdout data."""

    def __init__(self, split: ChronologicalSplit) -> None:
        self._split = split
        self._issued_tokens: Dict[str, HoldoutReleaseToken] = {}
        self._consumed_tokens: set[str] = set()
        self._audit_log: List[HoldoutAccessEvent] = []

    @property
    def split_sha256(self) -> str:
        return self._split.split_sha256

    def get_train(self) -> Dict[str, List[MarketBar]]:
        return self._split.train

    def get_validation(self) -> Dict[str, List[MarketBar]]:
        return self._split.validation

    def get_metadata(self) -> Dict[str, object]:
        return {
            "split_sha256": self._split.split_sha256,
            "embargo_bars": self._split.embargo_bars,
            "train_range_utc": list(self._split.train_range_utc),
            "validation_range_utc": list(self._split.validation_range_utc),
            "holdout_blinded": True,
            "holdout_access_attempts": len(self._audit_log),
        }

    def issue_release_token(
        self,
        hypothesis_id: str,
        proposer_id: str,
        reviewer_id: str,
        reason: str,
    ) -> HoldoutReleaseToken:
        """Issue a single-use blinded holdout release token strictly by an independent reviewer."""
        if not reviewer_id or reviewer_id == proposer_id:
            event = HoldoutAccessEvent(
                timestamp_utc=utc_now_iso(),
                caller_id=reviewer_id or "unknown",
                purpose="issue_release_token",
                granted=False,
                reason="Independent reviewer required; proposer cannot unlock holdout",
            )
            self._audit_log.append(event)
            raise HoldoutAccessError(
                "Holdout release requires an independent reviewer distinct from proposer",
                {"hypothesis_id": hypothesis_id, "proposer_id": proposer_id, "reviewer_id": reviewer_id},
            )

        issued_at = utc_now_iso()
        token_body = {
            "hypothesis_id": hypothesis_id,
            "proposer_id": proposer_id,
            "reviewer_id": reviewer_id,
            "issued_at_utc": issued_at,
            "reason": reason,
            "split_sha256": self._split.split_sha256,
        }
        sig = sha256_json(token_body)
        token_id = f"holdout_tok_{sig[:12]}"
        token = HoldoutReleaseToken(
            token_id=token_id,
            hypothesis_id=hypothesis_id,
            proposer_id=proposer_id,
            reviewer_id=reviewer_id,
            issued_at_utc=issued_at,
            reason=reason,
            signature=sig,
        )
        self._issued_tokens[token_id] = token
        return token

    def access_holdout(
        self,
        caller_id: str,
        purpose: str,
        token: Optional[HoldoutReleaseToken] = None,
    ) -> Dict[str, List[MarketBar]]:
        """Deny all holdout reads unless presented with a valid, unconsumed independent release token."""
        if token is None:
            self._audit_log.append(
                HoldoutAccessEvent(
                    timestamp_utc=utc_now_iso(),
                    caller_id=caller_id,
                    purpose=purpose,
                    granted=False,
                    reason="Missing independent reviewer release token",
                )
            )
            raise HoldoutAccessError(
                "Blinded holdout access denied: no independent reviewer release token provided",
                {"caller_id": caller_id, "purpose": purpose},
            )

        stored = self._issued_tokens.get(token.token_id)
        if stored is None or stored.signature != token.signature:
            self._audit_log.append(
                HoldoutAccessEvent(
                    timestamp_utc=utc_now_iso(),
                    caller_id=caller_id,
                    purpose=purpose,
                    granted=False,
                    reason="Invalid or forged holdout release token",
                    token_id=token.token_id,
                )
            )
            raise HoldoutAccessError(
                "Blinded holdout access denied: invalid release token",
                {"caller_id": caller_id, "token_id": token.token_id},
            )

        if token.token_id in self._consumed_tokens:
            self._audit_log.append(
                HoldoutAccessEvent(
                    timestamp_utc=utc_now_iso(),
                    caller_id=caller_id,
                    purpose=purpose,
                    granted=False,
                    reason="Single-use holdout release token already consumed",
                    token_id=token.token_id,
                )
            )
            raise HoldoutAccessError(
                "Blinded holdout access denied: release token already consumed",
                {"caller_id": caller_id, "token_id": token.token_id},
            )

        self._consumed_tokens.add(token.token_id)
        self._audit_log.append(
            HoldoutAccessEvent(
                timestamp_utc=utc_now_iso(),
                caller_id=caller_id,
                purpose=purpose,
                granted=True,
                reason=f"Authorized by independent reviewer {token.reviewer_id}",
                token_id=token.token_id,
            )
        )
        return self._split.holdout

    def audit_log(self) -> List[HoldoutAccessEvent]:
        return list(self._audit_log)
