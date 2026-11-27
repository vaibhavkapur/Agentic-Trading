# Local operator runbook

Run `./scripts/validate` before serving a snapshot. The command runs unit, HTTP integration and scenario tests, verifies fixture hashes and retained results, and exercises the CLI demo. The HTTP integration test needs permission to listen on an ephemeral loopback port.

## Start and inspect

Set distinct per-role secrets outside the repository. For a local session, generate ephemeral credentials in a private terminal.

```sh
export SENTIMENT_READER_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SENTIMENT_REVIEWER_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
./scripts/engine serve --port 8080
```

Open the loopback dashboard at `http://127.0.0.1:8080/dashboard` with HTTP Basic user `reviewer` and the corresponding token. To query from another shell with the credentials available, use curl's password prompt.

```sh
curl --user reader 'http://127.0.0.1:8080/v1/features?as_of=2025-04-23T00:00:00Z&issuer=NVL'
curl --user reviewer http://127.0.0.1:8080/v1/metrics
```

The static HTML in reports opens without credentials and contains synthetic evaluation evidence. The CLI relies on local filesystem access. Use access-controlled storage for any additional observations. To stop, press Ctrl-C. Restart with fresh environment secrets to rotate them. To replace a feed snapshot, prepare and validate a complete JSONL file, then restart with `--articles PATH`.

## Respond to faults

- **Feed empty or late.** Check event-window boundaries, availability, issuer aliases and the snapshot path. Repeat the exact as-of query to reproduce a historical result. To inspect a subsequent arrival, advance only the as-of and keep the original window end.
- **Uncertain or ambiguous.** Inspect the decision reason, raw probabilities and counts. Unresolved names produce no issuer feature. Preserve nulls and abstentions in downstream research. Review new aliases and annotation evidence before changing policy.
- **Validation or startup fails.** Inspect the structured error, restore the last verified config and fixture files and rerun validation. Resolve immutable-ID conflicts at the producer. Keep the last reviewed snapshot available to consumers.
- **Drift or calibration deteriorates.** Review corpus coverage, out-of-vocabulary feature rate, reliability bins and raw errors. Suspend downstream use of the affected feature until a new chronological evaluation is reviewed. This prototype has no automated promotion or retraining.
- **Authorization failures.** Check the role and token in the operator environment. Review response counts. Keep the server bound to loopback. HTTP Basic here assumes a trusted local machine.

## Review and rollout boundary

The package uses original synthetic fixtures and Python's standard library. The manifest records provenance and permitted local use. No external provider, real customer content, trader identity, broker connection or execution interface is present. The read API enforces separate roles and the HTML view escapes variable text. Credentials are runtime environment values. The benchmark and dashboard are deliberately shareable synthetic artifacts.

Custom data requires operator-confirmed rights and local access controls. Live feeds, a broader deployment, durable telemetry, remote authentication/TLS, rate limiting, high availability, near-duplicate detection, revision lifecycles, general sarcasm understanding and multilingual entity resolution are unsupported. Exact repeated texts are treated as copies across the entire snapshot. A fresh legitimate publication with identical text may therefore be suppressed.

The asset class, intended horizon, licensing, background IP, SAAT ownership, responsible reviewers and operational constraints remain owner decisions. Any move to a paper/sandbox or real-capital environment requires separate approval. The local review provides implementation evidence only.
