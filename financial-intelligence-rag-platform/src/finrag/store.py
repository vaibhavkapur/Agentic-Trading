"""Build a transactional SQLite projection of an operator-owned manifest."""
import json
import sqlite3
from collections import Counter
from pathlib import Path

from .domain import KINDS, Fault, digest, fields, identifier, require, utc
from .index import chunks, dense, tokens


DDL = (
    "CREATE TABLE IF NOT EXISTS journal (seq INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS settings (value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS versions (
       tenant TEXT, doc_id TEXT, version INTEGER, audience TEXT, issuer TEXT, kind TEXT, period TEXT,
       event_at TEXT, available_at TEXT, provenance TEXT, license TEXT, sha256 TEXT, body TEXT,
       PRIMARY KEY (tenant, doc_id, version))""",
    """CREATE TABLE IF NOT EXISTS chunks (
       chunk_id TEXT PRIMARY KEY, tenant TEXT, doc_id TEXT, version INTEGER,
       start INTEGER, end INTEGER, terms TEXT, vector TEXT,
       FOREIGN KEY (tenant, doc_id, version) REFERENCES versions)""",
    "CREATE INDEX IF NOT EXISTS by_version ON chunks(tenant, doc_id, version)",
)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise Fault("invalid_input", "Cannot read JSON input")


def config_values(config):
    fields(config, ("schema_version", "chunk_chars", "dimensions", "keyword_weight", "candidate_limit"))
    require(type(config["schema_version"]) is int and config["schema_version"] == 1, "Unknown index schema")
    for key, low, high in (("chunk_chars", 128, 4096), ("dimensions", 16, 512), ("candidate_limit", 20, 1000)):
        require(type(config[key]) is int and low <= config[key] <= high, "Invalid " + key)
    require(type(config["keyword_weight"]) in (int, float) and 0 < config["keyword_weight"] < 1,
            "Invalid fusion weight")
    return config


def inspect_manifest(manifest):
    fields(manifest, ("schema_version", "events"))
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
            and isinstance(manifest["events"], list), "Invalid manifest")
    latest, deleted = {}, set()
    for item in manifest["events"]:
        require(isinstance(item, dict), "Invalid event")
        common = ("op", "tenant", "doc_id", "available_at")
        publish = ("version", "audience", "issuer", "kind", "period", "event_at",
                   "path", "sha256", "provenance", "license")
        require(item.get("op") in ("publish", "delete"), "Unknown event")
        fields(item, common if item["op"] == "delete" else common + publish)
        key = identifier(item["tenant"]), identifier(item["doc_id"])
        prev = latest.get(key)
        available = utc(item["available_at"])
        require(key not in deleted, "Document ID is retired")
        require(not prev or available > utc(prev["available_at"]), "Availability must advance")
        if item["op"] == "delete":
            require(prev is not None, "Cannot delete unknown document")
            deleted.add(key)
            continue
        require(type(item["version"]) is int and item["version"] == (prev["version"]+1 if prev else 1),
                "Versions must be consecutive")
        for name in ("audience", "period"):
            identifier(item[name])
        for name in ("issuer", "provenance", "license", "path"):
            require(isinstance(item[name], str) and 0 < len(item[name].strip()) <= 500, "Invalid " + name)
        require(isinstance(item["sha256"], str) and len(item["sha256"]) == 64 and
                all(c in "0123456789abcdef" for c in item["sha256"]), "Invalid content digest")
        require(item["kind"] in KINDS and utc(item["event_at"]) <= available, "Invalid source kind or dates")
        require(not prev or all(item[f] == prev[f] for f in ("issuer", "period", "audience", "kind")),
                "Document identity and audience must remain stable")
        latest[key] = item
    return deleted


def rebuild(db_path, manifest_path, config_path):
    manifest = read_json(manifest_path)
    config = config_values(read_json(config_path))
    deleted = inspect_manifest(manifest)
    base = Path(manifest_path).resolve().parent
    events = manifest["events"]
    fingerprints = [digest(canonical(e).encode()) for e in events]
    conn = sqlite3.connect(db_path, timeout=15, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA secure_delete=ON")
        conn.execute("BEGIN IMMEDIATE")
        for ddl in DDL:
            conn.execute(ddl)
        old = [r[0] for r in conn.execute("SELECT fingerprint FROM journal ORDER BY seq")]
        require(fingerprints[:len(old)] == old, "Manifest rewrites existing history", "history_conflict")
        for table in ("chunks", "versions", "settings"):
            conn.execute("DELETE FROM " + table)
        for item in events:
            key = item["tenant"], item["doc_id"]
            if key in deleted:
                continue
            path = (base / item["path"]).resolve()
            require(base in path.parents, "Object outside manifest directory")
            try:
                raw = path.read_bytes()
                body = raw.decode("utf-8")
            except (OSError, UnicodeError):
                raise Fault("invalid_object", "Missing or invalid UTF-8 object")
            require(digest(raw) == item["sha256"], "Object hash mismatch", "invalid_object")
            require(body.strip() and "\x00" not in body, "Empty or invalid document")
            conn.execute("INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (*key, item["version"], item["audience"], item["issuer"], item["kind"],
                          item["period"], utc(item["event_at"]), utc(item["available_at"]),
                          item["provenance"], item["license"], item["sha256"], body))
            for start, end, passage in chunks(body, config["chunk_chars"]):
                cid = digest(canonical([*key, item["version"], item["sha256"], start, end]).encode())
                conn.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?)",
                             (cid, *key, item["version"], start, end, canonical(Counter(tokens(passage))),
                              canonical(dense(passage, config["dimensions"]))))
        conn.execute("INSERT INTO settings VALUES (?)", (canonical(config),))
        conn.executemany("INSERT INTO journal VALUES (?,?)", enumerate(fingerprints[len(old):], len(old)+1))
        result = {t: conn.execute("SELECT count(*) FROM " + t).fetchone()[0] for t in ("versions", "chunks")}
        result.update(events=len(events), retired_ids=len(deleted), manifest_sha256=digest(canonical(manifest).encode()))
        conn.commit()
        return result
    finally:
        conn.close()
