# Financial Research Agent

Build point-in-time research briefs from a small, synthetic collection of annual filings and news bulletins. Each supported statement opens the exact source passage behind it. An analyst can record a decision after inspecting the evidence.

## Run the local demo

From this directory, use Python 3.9+ with SQLite 3.25+ and a POSIX shell. The app uses the Python standard library. Setup requires no network access, provider account or package installation.

```sh
./scripts/setup
./scripts/demo
./scripts/validate
```

Setup loads five original fixture documents into `.state/research.sqlite`. Running it again verifies the same files and skips existing documents. The demo and validation use temporary databases. Validation needs permission to bind to loopback for the HTTP integration tests.

## Run a query

```sh
./bin/research resolve DEMO:ALDR
./bin/research ask Alder FY2024 'What was revenue?' --as-of 2025-03-15T00:00:00Z
./bin/research brief DEMO:ALDR FY2024 revenue net_income --as-of 2025-04-02T00:00:00Z
./bin/research ask Northland 2025-03-12 'What was policy rate?' --as-of 2025-03-15T00:00:00Z
./bin/research source alder-annual-v2 4
```

The March revenue query returns USD 118 million from the restated filing. The April brief shows the conflicting revenue passages side by side and still answers the net income question. Repeating a request over the same evidence returns the same brief ID and citation links.

## Open the analyst desk

```sh
export RESEARCH_READER_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export RESEARCH_ANALYST_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export RESEARCH_ANALYST_NAME=local-analyst
# Copy the desired token from your own terminal into the desk.
printf '%s\n' "$RESEARCH_ANALYST_TOKEN"
./bin/research serve
```

Open [the local analyst desk](http://127.0.0.1:8765), enter the token, and choose **Build brief**. Open a document and line number to inspect the cited passage. Enter a note and choose **Approve** or **Reject**. Readers can generate briefs and inspect evidence. The analyst credential also grants review access. The UI keeps the token in memory until reload. Use a private terminal when displaying it.

## Handoff

- [Architecture and assumptions](docs/architecture.md)
- [Input, research and HTTP contracts](docs/contracts.md)
- [Operational runbook, controls and rollout decisions](docs/runbook.md)
- [Acceptance checklist, scenario evidence and evaluation results](reports/acceptance.md)
- [Original implementation plan](plan.md)

The prototype supports the fixture text format, the catalog's four measures, calendar-year statements and dated macro observations. PDF/OCR, free-form document extraction, open-ended forecasting, live feeds, trading and multi-user production deployment are outside this implementation.
