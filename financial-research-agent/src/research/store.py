import sqlite3
from pathlib import Path

from .domain import Problem, require

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, series TEXT NOT NULL, revision INTEGER NOT NULL,
 supersedes TEXT REFERENCES documents(id), subject TEXT NOT NULL, kind TEXT NOT NULL,
 published TEXT NOT NULL, retrieved TEXT NOT NULL, metadata TEXT NOT NULL,
 sha TEXT NOT NULL, raw BLOB NOT NULL, UNIQUE(series,revision));
CREATE TABLE IF NOT EXISTS facts (
 doc TEXT NOT NULL REFERENCES documents(id), line INTEGER NOT NULL, metric TEXT NOT NULL,
 period TEXT NOT NULL, value TEXT NOT NULL, unit TEXT NOT NULL, currency TEXT,
 PRIMARY KEY(doc,metric,period), UNIQUE(doc,line));
CREATE TABLE IF NOT EXISTS briefs (
 id TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (
 brief TEXT PRIMARY KEY REFERENCES briefs(id), decision TEXT NOT NULL, actor TEXT NOT NULL,
 note TEXT NOT NULL, reviewed TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, count INTEGER NOT NULL);
"""


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def initialize(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    require(version in (0, 1), "unknown_schema", "Unsupported database schema.")
    db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nPRAGMA user_version=1; COMMIT;")


def increment(db, name):
    db.execute("INSERT INTO counters VALUES (?,1) ON CONFLICT(name) DO UPDATE SET count=count+1", (name,))


def one(db, sql, params):
    row = db.execute(sql, params).fetchone()
    if row is None:
        raise Problem("not_found", "Record not found.", 404)
    return row
