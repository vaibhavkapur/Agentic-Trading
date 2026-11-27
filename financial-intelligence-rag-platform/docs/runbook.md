# Local operator runbook

### Start and verify

Run the setup and validation commands in the [README](../README.md) with a local filesystem and a Python distribution supporting SQLite window functions. The service account needs read access to the index and credential file. The offline builder needs write access to the database directory, manifest and source objects as appropriate. Keep the runtime directory private (0700) and credentials and databases private (0600). A reader receives only its assigned token. The credential-file CLI is for trusted local operators.

Start the loopback HTTP server and probe `GET /health`. Exercise one authenticated query at a known timestamp to check readiness. The service logs operation, outcome or abstention reason, and elapsed milliseconds to stderr. Count outcomes by reason and examine latency across requests to track failures and decisions. There are no source passages, request text, bearer tokens or citation IDs in normal access logs. Stop the server with Ctrl-C. SQLite uses write-ahead logging. Keep database, WAL and shared-memory files together on local disk and allow SQLite to manage its sidecars. The quick start uses the same trusted OS account for building and serving.

### Publish or correct a source

1. Verify source ownership, license, issuer identity and group entitlement. Save distinct UTF-8 object bytes per version and calculate their SHA-256 digest.
2. Append a publish event to the authoritative manifest. Keep prior events identical. Provide the actual information-availability time, including delays in publication or delivery.
3. Run the builder against the same database. Replaying an unchanged manifest safely rebuilds its index. Restart-free publication is visible to newly opened reader snapshots after commit.
4. Query just before and at the new availability instant. Resolve a returned citation and verify the original text slice. Run the fixture suite when changing code or configuration.

### Delete, revoke or recover

Append a deletion, apply the manifest, and verify the former chunk IDs are unavailable at current and historical timestamps. Remove retired source objects from the controlled object store in accordance with the operator's retention policy. Coordinate removal from backups, logs and previous exports. Database projection deletion cannot recall material previously delivered to a reader. For strict revocation, stop accepting requests, drain in-flight requests, apply the deletion and restart.

To change reader groups or revoke a token, edit the private credential file and restart the server. To tighten a document audience, delete its ID and republish eligible material under a new ID with the new group. Applying both changes in one build avoids a partial update.

On digest, chronology or history errors, inspect the indicated input and restore the authentic source or append a valid correction. Retain the last good database. If a failed build involved a required restriction, stop serving until the restriction is successfully applied. If the database is lost, rebuild a new database from the latest authoritative manifest and original live objects, check the manifest digest and verify retired IDs before serving. Old manifests on an empty database can restore stale access. Keep the manifest and its deletion history under operator-controlled backup and change review.

### Reproduce evidence

```sh
PYTHONPATH=src python3 -m unittest discover -v
python3 scripts/evaluate.py --output .runtime/evaluation.json
python3 scripts/demo.py
```

Evaluation uses predeclared 2024 development cases and later 2025 holdout queries. Reported latency covers a local search, including opening the database. The small fixtures establish a functional baseline. Real filings, realistic corpus volumes, language diversity and sustained load need separate measurement. Inspect per-case failures even when aggregate metrics look acceptable.

### Deployment decisions

This delivery uses hand-authored synthetic inputs and local processing. No external model or market-data provider is configured. Code and fixtures were created in this project. Organizational ownership, licensing of any proposed real inputs, strategy horizon, asset class, data retention, operating limits and reviewers remain for the project owner to confirm. Production or paper/sandbox deployment needs an approved identity and transport design, operational ownership, and a separate security and risk review. The system provides research evidence and has no order submission interface.
