# Corpus and reader contracts

## Build input

`python3 -m finrag [--db PATH] build [--manifest PATH] [--config PATH]` applies a complete ordered manifest. Run from the project root with `PYTHONPATH=src`. Defaults are in [the manifest](../data/fixtures/manifest.json) and [index configuration](../config/index-v1.json). The database parent directory must already exist.

The manifest object contains integer `schema_version` 1 and an `events` array. Event order is append-only. A publish event has the following fields.

- `op` is `publish`. The tenant and document identifiers are `tenant` and `doc_id`. Identifiers start with an ASCII letter or digit and accept letters, digits, dots, underscores or hyphens, up to 80 characters.
- `version` increments from 1 per tenant and document. `audience` names one required group within the tenant.
- `issuer`, `period` and `kind` describe the source. Kinds are `filing`, `research` and `internal`. These three fields and the audience are invariant across versions.
- `event_at` and `available_at` accept offset-aware ISO timestamps with seconds and up to six fractional digits. Output is normalized to UTC. Availability must be at or after the event and advance between versions.
- `path` identifies a UTF-8 object beneath the manifest directory. `sha256` is the lowercase hex digest of its exact bytes. `provenance` records origin, and `license` records the operator's permission basis.
- A delete event contains exactly `op` set to `delete`, `tenant`, `doc_id` and `available_at`. It follows a known publication with a later availability timestamp. Applying it retires the ID immediately, including historical access. The timestamp records the operator's deletion decision. Future-dated entries are unsuitable for scheduling deletion.

The build response contains applied event, live-version, chunk and retired-ID counts plus a digest of the canonical manifest. A retired ID cannot be republished. Its object bytes may be removed before rebuilding the full manifest. The live index keeps event fingerprints for replay protection.

## Reader requests

Every POST request uses a JSON object and `Authorization: Bearer TOKEN`. The server maps the token to one tenant and a list of group identifiers in an operator-managed JSON file. Request fields cannot select a tenant or change group membership. Valid request bodies are limited to 16 KiB. CLI equivalents are `python3 -m finrag <search|answer|resolve> --credentials FILE REQUEST.json` using `FINRAG_TOKEN`.

### Search

`POST /v1/search` requires `query` (1–1000 characters after trimming) and `as_of` (offset-aware, at or before now). Optional `k` is an integer from 1 to 20, default 5. Optional `filters` accepts an intersection of `issuer` (ASCII case-insensitive), `kind`, `period` and `doc_id`. Returned hits include the citation fields and ranking score. A valid request can return an empty list.

### Answer

`POST /v1/answer` uses the search contract. The two supported English forms are below. Case differences and straight or curly apostrophes are supported.

```text
What was Aster Grid's net income in FY2024?
Compare Aster Grid's revenue in FY2024 across sources.
```

Supported metrics are revenue, net income, operating income, capital expenditure and operating cash flow. The current evidence grammar requires a full standalone line of the form `Aster Grid reported FY2024 revenue of USD 112 million.` It accepts USD/EUR/GBP, integer or decimal amounts with an optional minus sign, and thousand/million/billion scales. Issuer and period must agree with source metadata. An answer includes an `as_of`, a `status` of `answered` and one or more claims with `text`, `value` and a `citation`. Comparisons also include `comparison` with `identical_reported_values` or `different_reported_values`. The comparison covers matched passages in the top k candidates.

A valid question can return HTTP 200 with `status` set to `abstained`, an empty `claims` list and a reason of `unsupported_question`, `missing_evidence` or `insufficient_sources`.

### Citation resolution

`POST /v1/resolve` requires exactly `chunk_id` (64 lowercase hex digits) and `as_of`. The resolver reapplies access and time checks and returns a `citation` and the normalized `as_of`. Each citation includes the following fields.

- `doc_id`, `version`, source `sha256` and opaque `chunk_id` binding the tenant, document, version, digest and span.
- Zero-based `start` inclusive and `end` exclusive, measured in Unicode code points in the original decoded UTF-8 object. `passage` is precisely that slice.
- `issuer`, `period`, `kind`, `event_at`, `available_at`, `license` and `provenance`.

Retain the answer's original as-of instant with the citation. Replaying it can still fail after a deletion or access change. Configurations that change chunk boundaries produce new passage identifiers.

### Health and failures

`GET /health` returns process liveness. A reader query checks index availability. Failures use `error` with a stable code, optionally accompanied by `message`. Invalid input returns HTTP 400, failed authentication returns 401, unknown routes and unavailable citations return 404, and an unavailable index returns 503. The builder exits nonzero on validation, history conflicts, object integrity or storage failures. An interrupted or rejected transaction leaves the previous committed projection in place.
