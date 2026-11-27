#!/usr/bin/env python3
"""Exercise the application against independently labeled chronological cases."""
import json
import platform
import sqlite3
import statistics
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from research.domain import ROOT
from research.ingest import ingest
from research.store import connect, initialize
from research.workflow import research, source


def check(db, case):
    payload = {"subject": case["subject"], "period": case.get("period", "FY2024"), "as_of": case["as_of"]}
    if "metric" in case:
        payload["metrics"] = [case["metric"]]
    else:
        payload["question"] = case["question"]
    start = time.perf_counter()
    brief = research(db, payload)
    elapsed = round((time.perf_counter() - start) * 1000, 3)
    result = brief["result"]
    actual = result.get("reason")
    observed = []
    verified = True
    for item in result["items"]:
        actual = item["status"]
        rows = item.get("observations", [])
        if actual == "supported":
            rows = [dict(item, citation=c) for c in item["citations"]]
        for row in rows:
            c = row["citation"]
            passage = source(db, c["document"], c["line"])
            verified &= passage["text"] == c["passage"] and passage["metadata"]["sha256"] == c["sha256"]
            observed.append([c["document"], c["line"], row["value"], row["unit"], row["currency"]])
    repeat = research(db, payload)["id"] == brief["id"]
    passed = (verified and repeat and actual == case["expected"] and observed == case["evidence"]
              and result["status"] == ("supported" if actual == "supported" else "abstained"))
    return {"case": case["case"], "as_of": case["as_of"], "expected": case["expected"], "actual": actual,
            "observed": observed, "passages_verified": verified, "repeat_id_equal": repeat, "passed": passed,
            "latency_ms": elapsed}


def main():
    fixtures = ROOT / "data/fixtures"
    with tempfile.TemporaryDirectory() as tmp, closing(connect(Path(tmp) / "evaluation.sqlite")) as db:
        initialize(db)
        ingest(db, fixtures / "manifest.json")
        rows = [check(db, case) for case in json.loads((fixtures / "evaluation.json").read_text())]
    times = [r["latency_ms"] for r in rows]
    print(json.dumps({"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                      "system": platform.system() + " " + platform.machine(), "cases": len(rows),
                      "passed": sum(r["passed"] for r in rows), "median_ms": statistics.median(times),
                      "min_ms": min(times), "max_ms": max(times), "results": rows}, indent=2))
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
