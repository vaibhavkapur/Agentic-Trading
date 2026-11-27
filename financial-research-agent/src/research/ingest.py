"""Read operator-selected, hash-pinned local sources as one transaction."""
import json
import re
from decimal import Decimal
from pathlib import Path

from .domain import ID, METRICS, SUBJECTS, Problem, canonical, digest, period, require, timestamp
from .store import increment

FIELDS = set("id series revision supersedes subject kind published retrieved license path sha256".split())
SCALES = {"ones": 1, "thousands": 1000, "millions": 1000000}


def parse(raw, subject):
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise Problem("invalid_source", "Document must be UTF-8.") from exc
    require(lines and lines[0] == "Subject: " + subject["id"], "wrong_subject", "Source subject differs from manifest.")
    facts = []
    seen = set()
    for line_no, line in enumerate(lines[1:], 2):
        if not line.startswith("Fact|"):
            continue
        fields = line.split("|")
        require(len(fields) == 7, "invalid_fact", "Malformed observation at line %d." % line_no)
        _, metric, when, amount, scale, unit, currency = fields
        spec = METRICS.get(metric)
        require(spec and spec["kind"] == subject["kind"], "invalid_metric", "Metric incompatible with subject.")
        period(when)
        require(when.startswith("FY") == (subject["kind"] == "issuer"), "invalid_period", "Period incompatible with subject.")
        require(unit == spec["unit"] and currency == (subject["currency"] if unit == "money" else "-"),
                "unit_currency", "Observation has unexpected unit or currency.")
        require(scale in SCALES and (unit != "percent" or scale == "ones"), "invalid_scale", "Unsupported scale.")
        require(re.fullmatch(r"-?(0|[1-9][0-9]{0,14})(\.[0-9]{1,6})?", amount), "invalid_value", "Invalid decimal.")
        value = Decimal(amount) * SCALES[scale]
        require(metric != "shares_outstanding" or (value >= 0 and value == value.to_integral_value()),
                "invalid_value", "Shares must be a nonnegative whole count.")
        require((metric, when) not in seen, "duplicate_fact", "Duplicate metric and period in one document.")
        seen.add((metric, when))
        facts.append((line_no, metric, when, format(value.normalize(), "f"), unit, None if currency == "-" else currency))
    require(facts, "no_facts", "Document contains no supported observations.")
    return facts


def read_document(base, m):
    require(isinstance(m, dict) and m.keys() == FIELDS, "invalid_manifest", "Invalid document fields.")
    for key in ("id", "series", "subject"):
        require(isinstance(m[key], str) and re.fullmatch(ID, m[key]), "invalid_manifest", "Invalid " + key)
    require(type(m["revision"]) is int and 1 <= m["revision"] <= 100000, "invalid_revision", "Invalid revision number.")
    require(m["supersedes"] is None or isinstance(m["supersedes"], str), "invalid_revision", "Invalid predecessor.")
    require(m["license"] == "synthetic-project-fixture", "unentitled", "License is outside local fixture policy.")
    require(m["kind"] in ("filing", "news") and m["subject"] in SUBJECTS, "invalid_manifest", "Unknown kind or subject.")
    require(timestamp(m["published"]) <= timestamp(m["retrieved"]), "invalid_time", "Retrieval predates publication.")
    require(isinstance(m["path"], str) and isinstance(m["sha256"], str), "invalid_manifest", "Invalid source reference.")
    path = (base / m["path"]).resolve()
    require(path.is_relative_to(base) and not Path(m["path"]).is_absolute(), "invalid_path", "Source must be inside manifest directory.")
    try:
        with path.open("rb") as handle:
            raw = handle.read(1000001)
    except OSError as exc:
        raise Problem("missing_source", "Cannot open source " + m["id"]) from exc
    require(len(raw) <= 1000000, "source_size", "Source exceeds 1 MB.")
    require(digest(raw) == m["sha256"], "integrity_error", "Source digest mismatch.")
    facts = parse(raw, SUBJECTS[m["subject"]])
    for _, _, when, *_ in facts:
        ended = when[2:] + "-12-31" if when.startswith("FY") else when
        require(ended <= m["published"][:10], "future_period", "Reported period ends after publication.")
    return raw, facts


def ingest(db, path):
    path = Path(path).resolve()
    try:
        batch = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Problem("invalid_manifest", "Cannot read JSON manifest.") from exc
    require(isinstance(batch, dict) and type(batch.get("version")) is int and batch["version"] == 1
            and isinstance(batch.get("documents"), list) and batch["documents"], "invalid_manifest", "Expected nonempty v1 manifest.")
    added = 0
    with db:
        db.execute("BEGIN IMMEDIATE")
        for m in batch["documents"]:
            raw, facts = read_document(path.parent, m)
            prior = db.execute("SELECT metadata,raw FROM documents WHERE id=?", (m["id"],)).fetchone()
            if prior:
                require(prior["metadata"] == canonical(m) and prior["raw"] == raw, "immutable_document", "Document ID already assigned.")
                continue
            last = db.execute("SELECT * FROM documents WHERE series=? ORDER BY revision DESC LIMIT 1", (m["series"],)).fetchone()
            if last:
                valid = (m["supersedes"] == last["id"] and m["revision"] == last["revision"] + 1
                         and m["subject"] == last["subject"] and m["kind"] == last["kind"]
                         and m["published"] >= last["published"] and m["retrieved"] >= last["retrieved"])
            else:
                valid = m["revision"] == 1 and m["supersedes"] is None
            require(valid, "invalid_revision", "Expected next full replacement in series.")
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (m["id"], m["series"], m["revision"], m["supersedes"], m["subject"], m["kind"],
                        m["published"], m["retrieved"], canonical(m), m["sha256"], raw))
            db.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?)", [(m["id"], *f) for f in facts])
            added += 1
        increment(db, "ingest_batches")
    return {"added": added, "unchanged": len(batch["documents"]) - added}
