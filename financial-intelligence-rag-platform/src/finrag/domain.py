"""Validation at the corpus and reader boundaries."""
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone


class Fault(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(ok, message, code="invalid_input"):
    if not ok:
        raise Fault(code, message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value),
            "Expected a short identifier")
    return value


def utc(value):
    require(isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value),
        "Timestamp requires an explicit UTC offset")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise Fault("invalid_input", "Invalid timestamp")
    return stamp.isoformat(timespec="microseconds").replace("+00:00", "Z")


def fields(data, required, optional=()):
    require(isinstance(data, dict) and set(required) <= data.keys() <= set(required) | set(optional),
            "Unexpected or missing fields")


@dataclass(frozen=True)
class Principal:
    tenant: str
    groups: tuple

    @classmethod
    def parse(cls, data):
        fields(data, ("tenant", "groups"))
        require(isinstance(data["groups"], list), "Expected list of groups")
        return cls(identifier(data["tenant"]), tuple(identifier(g) for g in data["groups"]))


KINDS = ("filing", "research", "internal")
FILTERS = ("issuer", "kind", "period", "doc_id")
