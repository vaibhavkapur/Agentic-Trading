"""Reader contract shared by local tools and the authenticated HTTP interface."""
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .domain import FILTERS, KINDS, Fault, fields, require, utc
from .index import rank

METRICS = ("revenue", "operating income", "net income", "capital expenditure", "operating cash flow")
METRIC_PATTERN = "|".join(METRICS)
SUBJECT = rf"(?P<issuer>[a-z0-9][a-z0-9 &.-]{{0,79}}?)['’]s (?P<metric>{METRIC_PATTERN}) in (?P<period>FY[0-9]{{4}})"
QUESTION = re.compile(rf"What was {SUBJECT}\?", re.I)
COMPARISON = re.compile(rf"Compare {SUBJECT} across sources[.?]?", re.I)
AMOUNT = r"(?:USD|EUR|GBP) -?(?:0|[1-9]\d*)(?:\.\d+)? (?:million|billion|thousand)"


def evidence(row):
    return {k: row[k] for k in ("chunk_id", "doc_id", "version", "sha256", "start", "end", "passage",
                                "issuer", "kind", "period", "event_at", "available_at", "provenance", "license")}


def eligible(conn, principal, as_of, filters, chunk_id=None):
    where = ["tenant = ?", "event_at <= ?", "available_at <= ?"]
    bind = [principal.tenant, as_of, as_of]
    if not principal.groups:
        return []
    where.append("audience IN (" + ",".join("?" for _ in principal.groups) + ")")
    bind.extend(principal.groups)
    for key, value in filters.items():
        collation = " COLLATE NOCASE" if key == "issuer" else ""
        where.append(key + " = ?" + collation)
        bind.append(value)
    # ACL and metadata are immutable for the life of a document.
    sql = """WITH visible AS (
        SELECT *, row_number() OVER (PARTITION BY tenant,doc_id ORDER BY version DESC) AS priority
        FROM versions WHERE """ + " AND ".join(where) + """)
        SELECT v.*, c.chunk_id, c.start, c.end, c.terms, c.vector FROM visible v
        JOIN chunks c USING (tenant,doc_id,version) WHERE priority=1"""
    if chunk_id is not None:
        sql += " AND c.chunk_id=?"
        bind.append(chunk_id)
    rows = []
    for result in conn.execute(sql, bind):
        row = dict(result)
        body = row.pop("body")
        start, end = row["start"], row["end"]
        row["passage"] = body[start:end]
        left = body.rfind("\n", 0, start) + 1
        right = body.find("\n", end)
        row["standalone"] = not (body[left:start].strip() or body[end:right if right >= 0 else None].strip())
        for name in ("terms", "vector"):
            row[name] = json.loads(row[name])
        rows.append(row)
    return rows


def answer(question, hits):
    compare = COMPARISON.fullmatch(question)
    intent = compare or QUESTION.fullmatch(question)
    claims = []
    if intent:
        issuer, metric, period = (intent[name] for name in ("issuer", "metric", "period"))
        fact = re.compile(rf"{re.escape(issuer)} reported {re.escape(period)} {re.escape(metric)} of ({AMOUNT})\.", re.I)
        for hit in hits:
            match = fact.fullmatch(hit["passage"])
            if (match and hit["standalone"] and hit["issuer"].casefold() == issuer.casefold()
                    and hit["period"].casefold() == period.casefold()):
                claims.append({"text": hit["passage"], "value": match[1], "citation": evidence(hit)})
    reason = None
    if not intent:
        reason = "unsupported_question"
    elif not claims:
        reason = "missing_evidence"
    elif compare and len({c["citation"]["doc_id"] for c in claims}) < 2:
        reason = "insufficient_sources"
    if reason:
        return {"status": "abstained", "reason": reason, "claims": []}
    result = {"status": "answered", "claims": claims}
    if compare:
        result["comparison"] = ("identical_reported_values" if len({c["value"] for c in claims}) == 1
                                else "different_reported_values")
    return result


def dispatch(db_path, principal, operation, request):
    require(operation in ("search", "answer", "resolve"), "Unknown operation", "not_found")
    if operation == "resolve":
        fields(request, ("as_of", "chunk_id"))
        require(isinstance(request["chunk_id"], str) and re.fullmatch("[0-9a-f]{64}", request["chunk_id"]),
                "Invalid citation identifier")
    else:
        fields(request, ("as_of", "query"), ("filters", "k"))
        query = request["query"]
        require(isinstance(query, str) and 0 < len(query.strip()) <= 1000, "Invalid query")
        query = query.strip()
    stamp = utc(request["as_of"])
    require(stamp <= utc(datetime.now(timezone.utc).isoformat()), "Future as_of is unavailable")
    filters = request.get("filters", {})
    fields(filters, (), FILTERS)
    for value in filters.values():
        require(isinstance(value, str) and 0 < len(value) <= 100, "Invalid filter")
    if "kind" in filters:
        require(filters["kind"] in KINDS, "Unknown source kind")
    k = request.get("k", 5)
    require(type(k) is int and 1 <= k <= 20, "k must be between 1 and 20")
    try:
        uri = Path(db_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            settings = conn.execute("SELECT value FROM settings").fetchone()
            require(settings is not None, "Missing index configuration", "unavailable")
            config = json.loads(settings[0])
            rows = eligible(conn, principal, stamp, filters, request.get("chunk_id"))
    except sqlite3.Error:
        raise Fault("unavailable", "Index unavailable")
    if operation == "resolve":
        require(rows, "Citation unavailable", "not_found")
        return {"citation": evidence(rows[0]), "as_of": stamp}
    hits = rank(query, rows, config, k)
    if operation == "search":
        return {"as_of": stamp, "hits": [dict(evidence(h), score=h["score"]) for h in hits]}
    return dict(answer(query, hits), as_of=stamp)
