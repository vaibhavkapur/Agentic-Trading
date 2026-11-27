"""Deterministic point-in-time research and immutable review decisions."""
import json

from .domain import CATALOG, METRICS, SUBJECTS, canonical, digest, now, period, require, resolve, timestamp
from .ingest import parse
from .store import increment, one


def request_spec(payload):
    require(isinstance(payload, dict) and set(payload) <= {"subject", "period", "as_of", "question", "metrics"}
            and {"subject", "period", "as_of"} <= set(payload), "invalid_request", "Expected subject, period and as_of.")
    subject = resolve(payload["subject"])
    when = period(payload["period"])
    timestamp(payload["as_of"])
    require(("question" in payload) != ("metrics" in payload), "invalid_request", "Supply either question or metrics.")
    spec = {"subject": subject["id"], "period": when, "as_of": payload["as_of"]}
    if "question" in payload:
        q = payload["question"]
        require(isinstance(q, str) and 0 < len(q.strip()) <= 300, "invalid_question", "Question must be 1–300 characters.")
        spec["question"] = q.strip()
    else:
        metrics = payload["metrics"]
        require(isinstance(metrics, list) and 1 <= len(metrics) <= len(METRICS)
                and all(isinstance(m, str) and m in METRICS for m in metrics)
                and len(set(metrics)) == len(metrics), "invalid_metrics", "Expected a list of unique catalog metrics.")
        spec["metrics"] = metrics
    return spec


def verified_lines(doc):
    require(digest(doc["raw"]) == doc["sha"], "evidence_integrity", "Stored source failed verification.", 409)
    return doc["raw"].decode("utf-8").splitlines()


def source(db, doc_id, line):
    doc = one(db, "SELECT * FROM documents WHERE id=?", (doc_id,))
    lines = verified_lines(doc)
    require(1 <= line <= len(lines), "not_found", "No such passage.", 404)
    return {"document": doc_id, "line": line, "text": lines[line - 1], "metadata": json.loads(doc["metadata"])}


def evidence(db, spec):
    docs = db.execute("""
        SELECT * FROM (SELECT d.*, row_number() OVER (PARTITION BY series ORDER BY revision DESC) AS rank
        FROM documents d WHERE subject=? AND retrieved<=? AND published<=?) WHERE rank=1 ORDER BY id
        """, (spec["subject"], spec["as_of"], spec["as_of"]))
    by_metric = {}
    for doc in docs:
        lines = verified_lines(doc)
        expected = parse(doc["raw"], SUBJECTS[spec["subject"]])
        indexed = db.execute("SELECT line,metric,period,value,unit,currency FROM facts WHERE doc=? ORDER BY line",
                             (doc["id"],)).fetchall()
        require(expected == [tuple(row) for row in indexed], "evidence_integrity", "Indexed facts differ from source.", 409)
        for line, metric, when, value, unit, currency in expected:
            if when != spec["period"]:
                continue
            citation = {"document": doc["id"], "line": line, "passage": lines[line - 1],
                        "href": "/api/sources/%s/%d" % (doc["id"], line), "sha256": doc["sha"],
                        "published": doc["published"], "retrieved": doc["retrieved"], "revision": doc["revision"]}
            by_metric.setdefault(metric, []).append({"value": value, "unit": unit, "currency": currency, "citation": citation})
    return by_metric


def result_for(metric, rows, as_of):
    values = {(r["value"], r["unit"], r["currency"]) for r in rows}
    fresh = any((timestamp(as_of) - timestamp(r["citation"]["published"])).total_seconds()
                <= CATALOG["max_age_days"] * 86400 for r in rows)
    if not rows:
        return {"metric": metric, "status": "missing_evidence"}
    if len(values) > 1:
        return {"metric": metric, "status": "conflicting_evidence", "observations": rows}
    if not fresh:
        return {"metric": metric, "status": "stale_evidence", "observations": rows}
    value, unit, currency = values.pop()
    return {"metric": metric, "status": "supported", "value": value, "unit": unit, "currency": currency,
            "text": "%s was %s %s." % (METRICS[metric]["name"], value, currency or unit),
            "citations": [r["citation"] for r in rows]}


def evaluate(db, spec):
    metrics = spec.get("metrics")
    if metrics is None:
        question = " ".join(spec["question"].lower().split())
        metrics = [k for k, m in METRICS.items() if question == "what was %s?" % m["name"].lower()]
    base = {"version": 1, "subject": spec["subject"], "as_of": spec["as_of"], "period": spec["period"]}
    if not metrics:
        return dict(base, status="abstained", reason="unsupported_question", items=[])
    observations = evidence(db, spec)
    items = [result_for(m, observations.get(m, []), spec["as_of"]) for m in metrics]
    supported = sum(i["status"] == "supported" for i in items)
    status = "supported" if supported == len(items) else "partial" if supported else "abstained"
    return dict(base, status=status, items=items)


def research(db, payload):
    spec = request_spec(payload)
    with db:
        db.execute("BEGIN IMMEDIATE")
        result = evaluate(db, spec)
        brief_id = digest(canonical([spec, result]).encode())
        db.execute("INSERT OR IGNORE INTO briefs VALUES (?,?,?,?)", (brief_id, canonical(spec), canonical(result), now()))
        increment(db, "research_" + result["status"])
    return get_brief(db, brief_id)


def get_brief(db, brief_id):
    row = one(db, "SELECT * FROM briefs WHERE id=?", (brief_id,))
    review = db.execute("SELECT decision,actor,note,reviewed FROM reviews WHERE brief=?", (brief_id,)).fetchone()
    return {"id": brief_id, "created": row["created"], "request": json.loads(row["request"]),
            "result": json.loads(row["result"]), "review": dict(review) if review else None}


def decide(db, brief_id, decision, note, actor):
    require(decision in ("approve", "reject"), "invalid_decision", "Choose approve or reject.")
    require(isinstance(note, str) and 0 < len(note.strip()) <= 1000, "invalid_note", "A review note of 1–1000 characters is required.")
    with db:
        db.execute("BEGIN IMMEDIATE")
        brief = get_brief(db, brief_id)
        require(not brief["review"], "already_reviewed", "This brief already has a decision.", 409)
        if decision == "approve":
            require(brief["result"]["status"] == "supported", "unsupported_brief", "Only fully supported briefs can be approved.", 409)
            require(evaluate(db, brief["request"]) == brief["result"], "evidence_changed", "Evidence has changed. Run the query again.", 409)
        db.execute("INSERT INTO reviews VALUES (?,?,?,?,?)", (brief_id, decision, actor, note.strip(), now()))
        increment(db, "review_" + decision)
    return get_brief(db, brief_id)


def recent(db):
    return [dict(row, request=json.loads(row["request"])) for row in db.execute("""
        SELECT b.id,b.created,b.request,r.decision FROM briefs b LEFT JOIN reviews r ON r.brief=b.id
        ORDER BY b.created DESC,b.rowid DESC LIMIT 100""")]
