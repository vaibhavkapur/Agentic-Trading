# Local operator runbook

## Start, inspect and recover

1. Run the setup command in the README. The manifest paths, checksums, subject headers, timestamps, units and predecessor chain are validated before the transaction commits. Setup can be retried.
2. Use the demo for an isolated example or use the CLI and desk against the persistent local database. Set separate random reader and analyst credentials in the launching shell and identify the analyst. Use a private OS account. Token rotation takes effect on server restart.
3. Check `GET /health` for database availability. Inspect authenticated `GET /api/metrics` for abstentions, partial results, reviews and API errors. Counts are cumulative in this database. They include repeated requests and do not measure unique briefs. CLI ingestion failures are reported to stderr.
4. An integrity or entitlement failure requires operator investigation of the source, manifest and local access. Keep the failed input out of the active corpus. For an authorized correction use a new document revision and preserve the old bytes. Do not edit stored claims or lower the freshness threshold to force an answer.
5. For missing, conflicting or stale evidence, inspect the passages, obtain an authorized source if applicable and rerun the request. A change to eligible evidence produces a new snapshot. An approved historical snapshot records evidence at the prior decision. An analyst can reject an unresolved brief with a note.
6. Stop the server with Ctrl-C. To back up the database, stop all writers and use SQLite's backup API or the SQLite CLI `.backup` command. A fixture-only database can be rebuilt using `./bin/research --db /path/to/new.sqlite ingest`. Rebuilding restores source facts. Retain the original database or its backup to preserve reviews.
7. Run `./scripts/validate` and `./scripts/demo` after any catalog, parser or storage change. The versioned schema rejects unknown database versions. Introduce an explicit migration for a future schema change.

## Security, licensing and rollout review

The local reader can inspect all ingested fixture passages and generate briefs. The analyst can additionally decide on a brief. There is no HTTP ingestion endpoint. Direct CLI and database access belong to the trusted OS operator. The service accepts loopback Host values, uses bearer authorization for evidence, has no cross-origin grants, and renders document content as text. Credentials are supplied through the environment. Only the browser's in-memory token and temporary test credentials are used. The launcher restricts new local data files to the OS user.

The original text and data are synthetic. The fixture entitlement label authorizes only this local corpus under the prototype's admission policy. Operators must establish actual rights independently before adding external material. No personal source repositories, model providers or financial feeds were used. Organizational IP ownership, data contracts, target asset class, strategy horizon and security sign-off remain decisions for the responsible owner. No SAAT deployment approval is asserted.

Outside the supported scope are arbitrary PDFs, XBRL, OCR, unrestricted natural-language research, foreign exchange conversion, quarterly or non-calendar fiscal periods, corporate-action-adjusted identifiers, production SSO, per-source ACLs, network deployment, automated trade execution and price targets. A paper or real deployment requires a separate approval with documented entitlements and risk controls. The measured fixture baseline in the acceptance report does not establish a production service target.
