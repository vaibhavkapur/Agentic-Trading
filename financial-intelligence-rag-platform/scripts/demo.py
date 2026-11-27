#!/usr/bin/env python3
"""Build an isolated fixture index and exercise the same reader service as HTTP."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from finrag.domain import Principal
from finrag.service import dispatch
from finrag.store import rebuild


def main():
    with tempfile.TemporaryDirectory() as folder:
        db = Path(folder) / "demo.sqlite"
        result = rebuild(db, ROOT / "data/fixtures/manifest.json", ROOT / "config/index-v1.json")
        print(json.dumps({"build": result}, indent=2))
        reader = Principal("demo-fund", ("researchers",))
        examples = [
            ("search", "substation upgrade", {"kind": "internal"}, "2025-03-06"),
            ("answer", "What was Aster Grid's revenue in FY2024?", {"kind": "filing"}, "2025-02-28"),
            ("answer", "Compare Aster Grid's revenue in FY2024 across sources.", {}, "2025-03-06"),
            ("answer", "What was Aster Grid's operating income in FY2024?", {}, "2025-03-06"),
        ]
        for op, q, filters, day in examples:
            req = {"as_of": day + "T12:00:00Z", "query": q, "filters": filters}
            response = dispatch(db, reader, op, req)
            print(json.dumps({"request": req, "response": response}, indent=2))
            for claim in response.get("claims", []):
                resolved = dispatch(db, reader, "resolve", {"as_of": req["as_of"],
                                    "chunk_id": claim["citation"]["chunk_id"]})
                assert resolved["citation"] == claim["citation"]


if __name__ == "__main__":
    main()
