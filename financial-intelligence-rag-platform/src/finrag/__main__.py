import argparse
import json
import os
import sqlite3
import sys

from .domain import Fault, require
from .http import credentials, serve
from .service import dispatch
from .store import read_json, rebuild


def main():
    parser = argparse.ArgumentParser(description="Financial intelligence research index")
    parser.add_argument("--db", default=".runtime/index.sqlite")
    actions = parser.add_subparsers(dest="action", required=True)
    build = actions.add_parser("build")
    build.add_argument("--manifest", default="data/fixtures/manifest.json")
    build.add_argument("--config", default="config/index-v1.json")
    for action in ("search", "answer", "resolve", "serve"):
        read = actions.add_parser(action)
        read.add_argument("--credentials", required=True)
        if action == "serve":
            read.add_argument("--port", type=int, default=8787)
        else:
            read.add_argument("request", help="JSON request file")
    args = parser.parse_args()
    try:
        if args.action == "build":
            result = rebuild(args.db, args.manifest, args.config)
        elif args.action == "serve":
            serve(args.db, args.credentials, args.port)
            return
        else:
            identities = credentials(args.credentials)
            principal = identities.get(os.environ.get("FINRAG_TOKEN"))
            require(principal is not None, "Authentication required", "unauthorized")
            result = dispatch(args.db, principal, args.action, read_json(args.request))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (Fault, sqlite3.Error, OSError) as exc:
        print(json.dumps({"error": getattr(exc, "code", "storage_error"), "message": str(exc)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
