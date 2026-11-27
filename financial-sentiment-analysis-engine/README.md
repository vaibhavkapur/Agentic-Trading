# Financial sentiment analysis engine

Turn timestamped financial text into issuer-level sentiment features that a researcher could have observed at a specified instant. The local prototype trains on original synthetic desk notes, calibrates on a later period and exposes a read-only JSON feed and evaluation dashboard.

## Run locally

From this directory, use Python 3.9 or later on macOS or Linux. All runtime and test dependencies are in the standard library.

```sh
./scripts/setup
./scripts/validate
./scripts/engine demo
```

The demo uses a single contract announcement. Novalume wins the order and Harborloom loses it. Inspect the individual probabilities, abstention reasons and issuer aggregates in the JSON output.

```sh
./scripts/engine features --as-of 2025-04-23T00:00:00Z --issuer NVL
./scripts/engine evaluate
./scripts/benchmark
```

Open [the offline dashboard](reports/dashboard.html) in a browser. Evaluation writes the HTML and [raw predictions and metrics](reports/evaluation.json). The benchmark measures a warm, in-process query and prints environment and latency measurements.

## Supply your own observations

Pass a local JSONL file of permitted observations to `features` or `serve` with `--articles PATH`. It replaces the observation catalog for that run. Training, calibration and evaluation still use the versioned reference corpus. The [contract](docs/contracts.md) defines required fields and issuer aliases. See the [runbook](docs/runbook.md) to start the authenticated HTTP service.

## Results on the bundled corpus

The chronological split contains 40 training, 16 calibration and 25 held-out issuer labels. The served policy classified 24 of 25 correctly and abstained on seven. Its macro-F1 was 0.962. The lexicon scored 1.000 and the non-text class prior scored 0.097. The corpus uses fictional issuers and shares vocabulary with the lexicon. These measurements characterize the fixture workload.

Read the [evaluation and acceptance evidence](reports/findings.md), [annotation rules](docs/annotations.md), [architecture and decisions](docs/architecture.md), [API and schema](docs/contracts.md) and [operating limits](docs/runbook.md).
