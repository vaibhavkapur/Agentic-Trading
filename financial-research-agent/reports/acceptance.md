# MVP acceptance evidence

All results below apply to the synthetic local corpus. [Raw test and evaluation transcript](validation.txt) · [Per-case evaluation JSON](evaluation.json) · [Demo output](demo.txt)

## Results by milestone

| Milestone | Delivered | Reproduction |
|---|---|---|
| M1 | Versioned subject, metric and source contracts, local ingestion with original bytes, timestamps and entitlement checks | `./scripts/setup` and the storage integration tests |
| M2 | Exact-decimal statement facts, canonical issuer/instrument resolution, scale, currency and full-document restatements | `./scripts/demo` and the contract and revision tests |
| M3 | As-of questions and multi-measure briefs, stable verified passage links and explicit abstentions | `python3 scripts/evaluate.py` |
| M4 | Authenticated local analyst desk, immutable review decisions, negative scenarios, reproducible evaluation and CI workflow | `./scripts/validate` and the analyst walkthrough in the README |

## Acceptance checklist

- [x] Every supported claim has a verified passage. The evaluator compares document and line against independently labeled answers and opens each returned citation.
- [x] The result carries the research cutoff, fiscal period or event date, normalized decimal value, unit and currency. Citations retain both source timestamps and revision number.
- [x] The missing, stale and conflicting cases abstain with distinct reasons. A multi-measure brief preserves individually supported and unsupported items.
- [x] Unsupported price-target questions abstain. Document prose cannot change the query grammar, emit claims or approve a brief.
- [x] Each evaluation request was repeated and returned the same content ID. A storage integration test also checked alias equivalence and looked up the cited passage after reopening the database.
- [x] Setup, test and demo commands use bundled synthetic inputs and the standard library. HTTP tests exercise an ephemeral loopback port.
- [x] Architecture, assumptions, contracts, unsupported features, controls and operating procedures are in the [docs](../docs/) directory.
- [x] The local validation command used by CI passed all 22 automated tests and 12 labeled evaluation cases. The [CI workflow](../.github/workflows/validate.yml) retains logs on success or failure. Hosted CI requires a repository with Actions enabled.
- [x] Local data licensing, security boundaries, external dependencies, unresolved ownership and deployment approval requirements are recorded in the [runbook](../docs/runbook.md).

## Scenario evidence

| Scenario | Observed outcome |
|---|---|
| Wrong issuer | The Birch query returns EUR. A manifest claiming Birch for an Alder document is rejected. |
| Restated filing | One second before retrieval the old USD 120 million figure is used. At retrieval it changes to USD 118 million with a revision 2 citation. A replacement that omits a measure withdraws the earlier observation. |
| Unit or currency error | Incompatible currency, wrong measure dimension and unknown scale fail ingestion. |
| Conflicting facts | Revenue sources of USD 118 million and USD 119 million both appear with their passages. Net income remains supported. Approval of the partial brief fails. |
| Missing source | An absent file stops ingestion. A cutoff before document retrieval returns missing evidence. |
| Document prompt injection | The extraneous instruction in the news fixture creates no claim or review. Only tagged quantitative passages enter the brief. |
| Stale evidence | The net income query past the freshness limit returns its dated observation with a stale reason. |
| Analyst review | A reader's review is denied, and an analyst's decision is persisted. A race records only one terminal decision. A new eligible conflicting source blocks approval of the older pending snapshot. |
| Integrity | Altering either stored source bytes or an indexed value causes the research workflow to fail closed. |

A headless Chrome walkthrough on the implementation host connected with a temporary analyst credential, generated a March brief, opened line 4 of the restatement, approved and reopened the decision, and confirmed that the April conflict disables approval. The walkthrough used an isolated database. The standard-library HTTP integration suite covers the corresponding endpoints on every validation run.

## Evaluation scope

The 12 fixed cases run in chronological cutoff order over five fixture documents. Each case checks the expected disposition and the complete set of normalized observations and passage locators. Six cases expect a supported observation and six expect abstention. The evaluator verifies the returned text and digest through the passage adapter. It records all cases, including failures, and exits nonzero on a mismatch. There is no fitting, random sampling or external model.

The recorded baseline ran on Darwin arm64 with Python 3.9.6 and SQLite 3.51.0. The JSON contains elapsed milliseconds per first research call and the observed median, minimum and maximum. The timed interval includes local SQLite persistence and excludes initial ingestion, HTTP transport, citation follow-up and the repeated query. One small, hand-authored corpus cannot establish statistical accuracy, latency bounds or robustness on real filings.

During verification, an initial injection test incorrectly matched the digits “900” inside a legitimate normalized revenue figure. The corrected test checks for injected claim text, an unsupported price target, and unintended review side effects. The initial sandbox run also denied binding a test port. The retained passing run used temporary loopback access.
