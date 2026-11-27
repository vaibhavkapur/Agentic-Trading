#!/usr/bin/env python3
"""Run a local experiment. Every invocation owns a new evidence directory."""
import argparse
import hashlib
import json
import platform
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_engine.evaluation import experiment, record, write_json
from trading_engine.market import digest, load_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/demo.json")
    parser.add_argument("--fixture", type=Path, default=ROOT / "data/fixtures")
    parser.add_argument("--out", type=Path, help="new directory, defaults to reports/run-*")
    args = parser.parse_args()
    if args.out:
        out = args.out
        try:
            out.mkdir(parents=True)
        except FileExistsError:
            parser.error(f"Evidence directory already exists: {out}")
    else:
        reports = ROOT / "reports"
        reports.mkdir(exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix="run-", dir=reports))
    try:
        cfg = json.loads(args.config.read_text())
        write_json(out / "config.json", cfg)
        bars = load_fixture(args.fixture)
        source = hashlib.sha256()
        for file in [Path(__file__).resolve(), *sorted((ROOT / "src/trading_engine").glob("*.py"))]:
            source.update(file.name.encode() + b"\0" + file.read_bytes())
        meta = dict(python=platform.python_version(), platform=platform.platform(),
                    source_sha256=source.hexdigest(), config_sha256=digest(out / "config.json"),
                    fixture_sha256=digest(args.fixture / "sessions.csv"),
                    fixture_manifest_sha256=digest(args.fixture / "manifest.json"))
        write_json(out / "provenance.json", meta)
        experiment(bars, cfg, out, meta)
        record(out / "runs.jsonl", dict(event="experiment_complete"))
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError) as error:
        record(out / "runs.jsonl", dict(event="experiment_failed", code=getattr(error, "code", type(error).__name__),
                                        message=str(error)))
        print(f"Experiment failed. See {out / 'runs.jsonl'}", file=sys.stderr)
        return 1
    print(out / "report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
