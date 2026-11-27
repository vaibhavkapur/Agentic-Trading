# Local MVP acceptance record

The retained run used Python 3.9.6, SQLite 3.51.0 and the synthetic manifest. Its ten events produce eight accessible-by-policy document versions, 17 stored chunks and one retired document ID. A reader sees a subset determined by tenant, groups, as-of instant and supersession.

## Evidence by milestone

- **M1 — Corpus and design.** The [manifest](../data/fixtures/manifest.json) pins source bytes, provenance, permissions and availability. The [architecture](../docs/architecture.md) and [contract](../docs/contracts.md) specify trust, identity, version and time invariants. Unit tests exercise invalid versions, dates, identifiers and configuration.
- **M2 — Retrieval.** The [demo transcript](demo.txt) and [adapter tests](../tests/integration/test_adapters.py) cover deterministic rebuilding, exact character offsets, combined metadata filters, retry after corruption and simultaneous database access. The [fixture evaluation](evaluation.json) retains the ranked passages for each query.
- **M3 — Cited answers and comparison.** The demo compares two attributed revenue figures and abstains on an inaccessible operating-income figure. The integration suite checks that a comparison requires two documents and every emitted citation resolves to the original text. A loopback smoke check also exercised server liveness, an authenticated request, citation resolution and equivalent CLI output.
- **M4 — Boundaries and delivery.** All six required failure scenarios are in the [scenario suite](../tests/scenarios/test_boundaries.py). They exercise search, synthesis and direct citation resolution as applicable. [Raw test output](tests.txt) records all 17 tests passing. The [runbook](../docs/runbook.md) covers revocation, deletion, recovery, monitoring and rollout.

## Retrieval and citation baseline

Two development cases precede 13 chronological holdout cases. Of the latter, seven have labeled relevant passages. Macro recall@1 was 0.9286 and recall@3 and recall@5 were both 1.0. The top-one experiment missed one of the two required passages for the comparison query. Each rank can contain only one passage. Evaluation retains that result alongside the successful top-five result.

All 13 holdout answer/abstain decisions matched their labels. All seven emitted holdout claims matched labeled evidence, a freshly resolved citation and the exact slice of hash-verified source bytes. A free-text sales query has a retrieval label and an expected abstention for synthesis. This checks the two contracts independently.

Per-query rankings, decision reasons, support checks and search timings are in [the raw evaluation](evaluation.json). The report computes macro recall over queries having gold passages and supported-claim rate over emitted claims. Seven holdout claims give limited precision: one unsupported claim would shift the result by about 14 percentage points. The hand-authored corpus and judgments measure regression behavior. Accuracy and throughput on investment documents of other formats and distributions remain unmeasured.

An initial concurrent-reader test exposed an intermittent disk I/O error with SQLite's rollback journal on the test machine. Write-ahead logging passed 100 consecutive runs of the same overlapping-build/read test, followed by a passing full suite.

## Acceptance and rollout status

1. **Permission and time filters.** The scenarios cover foreign tenants, missing group entitlements, unavailable future filings, superseded versions and historical access after deletion. Unavailable and unauthorized citation IDs share the same outward error.
2. **Citation integrity and abstention.** Integration tests recompute original hashes and slices. Negative cases include a malicious instruction, forged example, missing metric, unavailable comparison source and unsupported compound question.
3. **Reproducibility.** Build, demo and validation commands use checked-in data, versioned settings and the Python standard library. Content mismatches roll back the entire build. Replaying a valid manifest yields the same ranked evidence identifiers.
4. **Delivery and CI.** The [workflow](../.github/workflows/validate.yml) runs setup, tests, evaluation and demo, retaining raw output. The local checks passed. Hosted CI execution awaits a configured remote.
5. **Security, data and ownership.** The implementation uses local synthetic objects with recorded permissions and no external providers. The [runbook](../docs/runbook.md) records the security boundary and organizational review requirements. Actual SAAT ownership, asset class, data licenses and approval for any deployment beyond the local prototype remain open.
