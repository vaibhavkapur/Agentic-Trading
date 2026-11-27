#!/usr/bin/env python3
"""Replay gold passages and evaluate decisions against independently labeled evidence."""
import argparse
import json
import platform
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from finrag.domain import Principal, digest
from finrag.service import dispatch
from finrag.store import read_json, rebuild


def key(hit):
    return (hit["doc_id"], hit["version"], hit["passage"])


def replay(db, objects, case):
    principal = Principal("demo-fund", tuple(case["groups"]))
    request = {k: case[k] for k in ("query", "filters", "as_of")}
    request["k"] = 5
    start = time.perf_counter()
    hits = dispatch(db, principal, "search", request)["hits"]
    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    ans = dispatch(db, principal, "answer", request)
    gold = set(map(key, case["relevant"]))
    checks = []
    for claim in ans["claims"]:
        cite = claim["citation"]
        resolved = dispatch(db, principal, "resolve", {"as_of":case["as_of"], "chunk_id":cite["chunk_id"]})
        raw = objects[principal.tenant, cite["doc_id"], cite["version"]]
        supported = (key(cite) in gold and cite == resolved["citation"] and digest(raw) == cite["sha256"]
                     and raw.decode()[cite["start"]:cite["end"]] == cite["passage"] == claim["text"])
        checks.append({"citation":cite, "supported":supported})
    recall = {str(k): len(gold.intersection(map(key, hits[:k]))) / len(gold) if gold else None for k in (1,3,5)}
    return {**case, "status":ans["status"], "reason":ans.get("reason"), "recall":recall,
            "claims":checks, "ranking":[{k:h[k] for k in ("chunk_id","doc_id","version","passage","score")} for h in hits],
            "decision_correct":ans["status"] == case["expected"], "search_ms":elapsed_ms}


def summary(rows):
    positives = [r for r in rows if r["relevant"]]
    claims = [c for r in rows for c in r["claims"]]
    return {"cases":len(rows), "retrieval_cases":len(positives), "claims":len(claims),
            "recall_at_k":{k:round(sum(r["recall"][k] for r in positives)/len(positives),4) for k in ("1","3","5")},
            "supported_claim_rate":sum(c["supported"] for c in claims)/len(claims) if claims else None,
            "correct_decisions":sum(r["decision_correct"] for r in rows),
            "median_search_ms":round(median(r["search_ms"] for r in rows),3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    fixtures = ROOT / "data/fixtures"
    manifest = fixtures / "manifest.json"
    objects = {(e["tenant"],e["doc_id"],e["version"]):(fixtures / e["path"]).read_bytes()
               for e in read_json(manifest)["events"] if e["op"] == "publish"}
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp)/"evaluation.db"
        build = rebuild(db, manifest, ROOT/"config/index-v1.json")
        rows = [replay(db, objects, c) for c in read_json(fixtures/"evaluation.json")]
    metrics = {split:summary([r for r in rows if r["split"] == split]) for split in ("development","holdout")}
    result = {"environment":{"python":platform.python_version(), "sqlite":sqlite3.sqlite_version,
                             "system":platform.system(), "machine":platform.machine()},
              "build":build, "metrics":metrics, "cases":rows}
    if args.output:
        args.output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(metrics, indent=2))
    # Every required top-five evidence passage, answer decision and citation must pass on the fixtures.
    failed = any(
        not row["decision_correct"]
        or row["recall"]["5"] not in (None, 1.0)
        or any(not claim["supported"] for claim in row["claims"])
        for row in rows
    )
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
