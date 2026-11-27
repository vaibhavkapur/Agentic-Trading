# Contracts · sentiment.v1

## Local input

Use a UTF-8 JSON object per line. An article has exactly these seven fields.

```json
{"schema_version":"sentiment.v1","id":"my-note-1","source":"synthetic-desk","event_at":"2025-04-22T08:00:00Z","available_at":"2025-04-22T09:00:00Z","headline":"Novalume won the order","body":"Service demand grew."}
```

IDs are stable across replays. Source and headline are nonblank strings. The body may be empty. Each text field is limited to 65,536 characters. UTC timestamps end in Z and support up to six fractional digits. Availability must be at or after publication. Malformed input rejects the catalog at startup. Keep news and credentials out of logs.

The reference label file contains `article_id`, `issuer`, `label`, `rule` and `annotated_at`. Labels attach to canonical, resolved mentions. Each pair appears once. The three configured fictitious issuer IDs are NVL, HBR and KST. Pioneer is an intentionally ambiguous alias for NVL and HBR.

## Read API

- `GET /health` returns readiness after a successful startup.
- `GET /v1/features?as_of=2025-04-23T00:00:00Z&issuer=NVL` returns a feature snapshot. Reader or reviewer credentials are required. Optional `window_end` defaults to `as_of`. Omitting the optional issuer selects every resolved issuer.
- `GET /dashboard` returns the HTML evaluation dashboard to a reviewer.
- `GET /v1/evaluation` returns the reference-corpus report, comparison metrics, drift, linking issues, duplicate IDs, calibration trials and raw predictions to a reviewer.
- `GET /v1/metrics` returns HTTP status counts, scored/abstained decision counts, duplicate count and article linking-issue count to a reviewer. Decision counts measure responses served, including repeated queries. Counters reset at restart.

Features select publication instants in `[window_end − 24 hours, window_end)` and inputs available at or before `as_of`. An explicit earlier window end supports vintage comparisons. An as-of before model availability, a future window end, unknown issuer or malformed query returns HTTP 400 with a stable error code. Missing credentials return 401 and insufficient role returns 403. Unknown routes with valid credentials return 404. Querying an empty window returns 200 with empty lists.

The response envelope contains the schema and model versions, simulated `model_available_at`, event-window bounds, and `available_at`, the requested knowledge instant. Each issuer aggregate gives total, used and abstained article counts, latest input event and availability instants, and the unitless mean sentiment in [−1, 1] or null. Each decision contains the canonical article ID and source, both timestamps, issuer ID, label, nullable reason, four class probabilities, and nullable sentiment. The probabilities describe the calibrated classifier before the abstention rules. An abstaining decision has label `uncertain`.

The evaluation JSON includes a fingerprint of article inputs and an independently reproducible model ID. The fixture manifest hashes both articles and annotations. Raw per-model probabilities permit recomputation of every held-out score.
