"""Version 1 domain contracts and canonical encodings."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "config/catalog.v1.json").read_text())
METRICS = CATALOG["metrics"]
SUBJECTS = {s["id"]: s for s in CATALOG["subjects"]}
ID = r"[a-z][a-z0-9-]{0,63}"


class Problem(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def require(condition, code, message, status=400):
    if not condition:
        raise Problem(code, message, status)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def timestamp(value):
    require(isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value), "invalid_time", "Use UTC YYYY-MM-DDTHH:MM:SSZ.")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise Problem("invalid_time", "Invalid UTC date or time.") from exc


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve(value):
    require(isinstance(value, str), "unknown_subject", "Supply an issuer, instrument or macro identifier.")
    key = value.strip().casefold()
    matches = [s for s in SUBJECTS.values() if key in
               {v.casefold() for v in [s["id"], s["name"], *s["aliases"], *s["instruments"]]}]
    require(len(matches) == 1, "unknown_subject", "Unknown or ambiguous subject.", 404)
    return matches[0]


def period(value):
    require(isinstance(value, str) and re.fullmatch(r"FY[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2}", value),
            "invalid_period", "Use FYyyyy or an ISO event date.")
    if not value.startswith("FY"):
        timestamp(value + "T00:00:00Z")
    return value
