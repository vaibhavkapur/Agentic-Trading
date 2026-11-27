# Financial Intelligence RAG Platform

Search synthetic filings, research notes and internal investment documents as a specific reader at a specific instant. The local service combines keyword and dense-vector retrieval, quotes financial claims with verifiable citations, compares sources, and abstains when it lacks evidence.

## Run from a clean checkout

Use Python 3.9+ with the standard-library SQLite module linked against SQLite 3.25+. Run these commands from this directory. Setup uses local files only.

```sh
./scripts/setup.sh
./scripts/validate.sh
python3 scripts/demo.py
```

Setup builds `.runtime/index.sqlite`. Validation runs the unit, integration and scenario tests, replays chronological evaluation cases, and exercises the demo. The demo uses a temporary database and synthetic reader. At 12:00 UTC on February 28, 2025, it quotes the Aster Grid filing at USD 110 million. On March 6 it shows the restated filing at USD 112 million alongside a research note at USD 111 million.

## Try the reader API

Create an operator-owned credential file in the private runtime directory, then start the loopback server. This example creates a fresh token and uses exclusive creation to protect existing credentials.

```sh
export PYTHONPATH=src
(umask 077 && python3 - <<'PY'
import json, secrets
with open(".runtime/readers.json", "x") as out:
    json.dump({secrets.token_hex(32): {"tenant": "demo-fund", "groups": ["researchers"]}}, out)
PY
)
python3 -m finrag serve --credentials .runtime/readers.json
```

In another local shell in this directory, run the following request.

```sh
export FINRAG_TOKEN="$(python3 -c 'import json; print(next(iter(json.load(open(".runtime/readers.json")))))')"
curl -sS http://127.0.0.1:8787/v1/answer \
  -H "Authorization: Bearer $FINRAG_TOKEN" -H 'Content-Type: application/json' \
  -d '{"query":"What was Aster Grid’s revenue in FY2024?","as_of":"2025-03-06T12:00:00Z","filters":{"kind":"filing"}}'
```

The response includes the reported amount, exact passage, immutable document digest, version, character offsets and chunk ID. Pass the ID and the same timestamp to `/v1/resolve` to recheck access and inspect the passage.

## Project guide

- [Architecture and design decisions](docs/architecture.md) describes the corpus, trust boundaries, ranking and limitations.
- [API and manifest contract](docs/contracts.md) specifies requests, permissions, versioning, evidence and errors.
- [Operator runbook](docs/runbook.md) covers rebuilds, deletion, monitoring, recovery and rollout.
- [Acceptance evidence](reports/acceptance.md) maps the plan to tests, benchmark results and pending organizational decisions.
- [Implementation plan](plan.md) contains the original scope.
