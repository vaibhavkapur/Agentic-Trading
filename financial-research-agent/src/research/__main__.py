import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing

from .domain import METRICS, ROOT, Problem, resolve
from .http import credentials, serve
from .ingest import ingest
from .store import connect, initialize
from .workflow import get_brief, research, source


def main():
    parser = argparse.ArgumentParser(description="Local evidence-linked research desk")
    parser.add_argument("--db", default=str(ROOT / ".state/research.sqlite"))
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("ingest")
    load.add_argument("manifest", nargs="?", default=str(ROOT / "data/fixtures/manifest.json"))
    sub.add_parser("resolve").add_argument("identifier")
    for cmd in ("ask", "brief"):
        q = sub.add_parser(cmd)
        q.add_argument("subject")
        q.add_argument("period")
        q.add_argument("--as-of", required=True)
        if cmd == "ask":
            q.add_argument("question")
        else:
            q.add_argument("metrics", choices=list(METRICS), nargs="+")
    sub.add_parser("show").add_argument("id")
    passage = sub.add_parser("source")
    passage.add_argument("document")
    passage.add_argument("line", type=int)
    web = sub.add_parser("serve")
    web.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with closing(connect(args.db)) as db:
        initialize(db)
        if args.command == "ingest":
            result = ingest(db, args.manifest)
        elif args.command == "resolve":
            result = resolve(args.identifier)
        elif args.command in ("brief", "ask"):
            payload = {key: getattr(args, key) for key in ("subject", "period", "as_of")}
            field = "question" if args.command == "ask" else "metrics"
            result = research(db, dict(payload, **{field: getattr(args, field)}))
        elif args.command == "source":
            result = source(db, args.document, args.line)
        elif args.command == "show":
            result = get_brief(db, args.id)
        else:
            keys = credentials(*(os.environ.get("RESEARCH_" + k) for k in ("READER_TOKEN", "ANALYST_TOKEN", "ANALYST_NAME")))
            serve(args.db, args.port, keys)
            return
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (Problem, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": getattr(exc, "code", "storage_failure"), "message": str(exc)}), file=sys.stderr)
        sys.exit(1)
