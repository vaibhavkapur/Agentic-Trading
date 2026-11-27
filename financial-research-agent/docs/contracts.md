# Contracts, version 1

## Source adapter

See the [manifest](../data/fixtures/manifest.json), [example filing](../data/fixtures/documents/alder-annual-v2.txt) and [catalog](../config/catalog.v1.json). All source bytes in the corpus were written for this project. The issuer names, instrument codes, macro institution and numbers are fictional.

A manifest has integer `version: 1` and a nonempty `documents` array in predecessor order. Each record specifies the following fields.

- `id`, `series` and `subject` are lowercase stable identifiers. `subject` must be a canonical ID in the catalog.
- `kind` is `filing` or `news`. `revision` starts at 1 and increments by one in the same series. `supersedes` is null for the first version and the previous ID thereafter. Revisions preserve subject and kind.
- `published` and `retrieved` are UTC seconds in `YYYY-MM-DDTHH:MM:SSZ` format. Retrieval represents point-in-time availability. It must follow or equal publication. Both timestamps are nondecreasing within the revision chain.
- `license` must match the local `synthetic-project-fixture` allowlist. `path` resolves inside the manifest directory. `sha256` pins the bytes. A license label is an operator assertion, not a rights verification service.

The v1 parser accepts a UTF-8 file up to 1 MB. Its first line is `Subject: <canonical-id>`. One physical line is one addressable passage, with numbering starting at 1. Other prose is preserved for audit. Only records with the following explicit structure enter the fact index.

```text
Fact|metric|period|amount|scale|unit|currency
Fact|revenue|FY2024|118|millions|money|USD
Fact|shares_outstanding|FY2024|12|millions|shares|-
Fact|policy_rate|2025-03-12|3.25|ones|percent|-
```

Scale is `ones`, `thousands` or `millions`. Percent requires `ones` and 3.25 denotes 3.25 percent. Financial figures use the issuer's catalog reporting currency. Counts require a whole, nonnegative normalized value. Nonmonetary currency is `-` in the source and null in JSON. Decimal amounts allow up to 15 integer digits and six fractional digits. Normalized values are strings so downstream clients can preserve decimal precision. FY labels represent calendar years ending December 31. Macro periods use ISO event dates. Period ends must precede or coincide with publication. Each metric and period appears at most once per document.

## Research contract

Supply `subject`, `period`, `as_of`, and exactly one of `metrics` (a unique list of catalog keys) or `question`. For QA the recognized form is “What was NAME?” using a catalog measure name, case-insensitive. Subject and period are separate structured fields. A valid but unsupported question returns an abstention with reason `unsupported_question`.

At the cutoff, select revisions whose publication and retrieval times are both available, then take the highest eligible revision per series. Distinct active series that report different normalized values produce `conflicting_evidence`, including when one is older. Unanimous values are `stale_evidence` if every supporting publication is older than the catalog's 400-day threshold at the cutoff. An empty set produces `missing_evidence`. The rule measures publication age, not time since the fiscal period. The historical cutoff remains fixed at review.

Every supported item includes `metric`, `value`, `unit`, `currency`, display `text` and `citations`. The parent result records `subject`, `period` and `as_of` for all items. A citation includes the document, physical line, quote, lookup path, source digest, publication, retrieval and revision. Conflict and stale items expose the observations that caused abstention. Brief IDs hash the canonical resolved request and result. Wall-clock creation and review timestamps sit outside that hash.

## HTTP API

The server binds to 127.0.0.1. The root, static assets and `GET /health` are public. All `/api` requests require an `Authorization: Bearer TOKEN` header. POST bodies use JSON and have an 8 KiB limit.

| Method and path | Request and response |
|---|---|
| GET /api/catalog | Versioned subjects, aliases, instruments, measures and freshness policy |
| POST /api/resolve | `{"identifier":"DEMO:ALDR"}` returns the canonical subject record |
| POST /api/briefs | Research request returns `id`, `created`, `request`, `result` and nullable `review` |
| GET /api/briefs | Newest 100 snapshot IDs with query, creation time and decision |
| GET /api/briefs/{id} | Saved snapshot with decision, actor, note and review time if reviewed |
| GET /api/sources/{doc}/{line} | Verified passage text and manifest metadata including provenance |
| POST /api/briefs/{id}/review | Analyst only. Supply `{"decision":"approve","note":"Checked the cited statement."}` or a rejection |
| GET /api/metrics | Persistent ingest, query outcome, review decision and handled API error counts |

Validation and lookup errors use `{"error":"machine_code","message":"human-readable reason"}`. Invalid input returns 400, missing credentials 401, insufficient role 403, missing records 404, and integrity or review conflicts 409. Storage outages return 503. CLI errors go to stderr with a nonzero exit status. An abstention is a completed research result and uses HTTP 200.
