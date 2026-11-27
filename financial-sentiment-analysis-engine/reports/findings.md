# Local MVP evaluation

The held-out set contains 25 issuer labels from 24 canonical articles, dated April 2025 by first availability. The fit uses 40 earlier labels and a separate calibration set of 16. Synthetic labels describe issuer news. The shared editorial style and small sample limit generalization.

## Comparison

- **Non-text training prior** achieved macro-F1 0.097, multiclass Brier 0.750 and expected calibration error (ECE) 0.010. All four training priors tie. A constant prediction can have a small aggregate calibration gap.
- **Finance lexicon** achieved macro-F1 1.000, Brier 0.151 and ECE 0.312. Its directional vocabulary and caution rules align closely with the synthetic annotation protocol.
- **Supervised text classifier** achieved macro-F1 0.887, Brier 0.209, ECE 0.132 and negative log likelihood 0.481 before temperature scaling.
- **Calibrated classifier** achieved macro-F1 0.887, Brier 0.219, ECE 0.106 and negative log likelihood 0.680. Temperature 0.5 minimized calibration-period log loss. Sharpening reduced the held-out average confidence gap and increased the penalty for confident mistakes.
- **Served decisions** achieved macro-F1 0.962 with 18 accepted decisions and seven abstentions. Correctly abstaining on a gold uncertain label counts as correct in four-class evaluation. Served accuracy was 24/25, with an approximate 95% Wilson interval of 80.5% to 99.3%. The interval treats issuer labels as independent, although a multi-issuer article contributes two labels. Article correlations and synthetic sampling limit inference.

The remaining served error is note-073. Harborloom's recovery in freight was labeled positive and the classifier returned negative. Retaining all scores exposes the failure of a small bag-of-words model on context-dependent phrasing.

Macro-F1 averages the four one-vs-rest F1 values. Brier is the sum of squared class-probability errors per observation, averaged over observations. ECE is the count-weighted absolute gap between mean confidence and top-class accuracy in five equal-width confidence bins. The served policy uses the calibrated distribution before applying abstention. Its probability metrics therefore match the calibrated classifier's metrics. Raw JSON includes confusion matrices, nonempty reliability bins, all calibration trials and per-observation results.

## Drift and performance

On the held-out set, 43.7% of unigram and bigram occurrences were outside the training vocabulary. Jensen–Shannon divergence between training and held-out gold label frequencies was 0.0033 bits. The former measures text coverage and the latter requires labels available retrospectively. Production thresholds need a representative permitted corpus.

[Benchmark evidence](benchmark.json) records 200 iterations of the same warm in-process query over 81 canonical fixture articles, returning two issuer decisions. It includes the environment, median, nearest-rank p95 and maximum in milliseconds. HTTP transport, model fitting and file reads are outside the timed interval.

## Milestone and acceptance evidence

- **M1.** Versioned label rules, annotation times, source provenance and chronological cutoffs are in [annotations](../docs/annotations.md), the [manifest](../data/fixtures/manifest.json) and the [config](../config/v1.json). Unit tests validate UTC, IDs, schema and annotation integrity.
- **M2.** The [domain and linker](../src/sentiment/domain.py) and [baselines](../src/sentiment/models.py) process exact syndicated copies, unresolved aliases and issuer-specific text. A copy of a training story reappears during test and is removed before evaluation.
- **M3.** [The engine](../src/sentiment/engine.py) enforces known-at cutoffs, freezes calibration, emits both timestamps and excludes abstentions from issuer means. [Scenarios](../tests/scenarios/test_scenarios.py) cover syndication, headline/body conflict, ambiguity, sarcasm, late availability and leakage.
- **M4.** [Raw evaluation](evaluation.json), [dashboard](dashboard.html), [HTTP tests](../tests/integration/test_interfaces.py) and [validation output](validation.txt) cover model comparison, drift, role separation and fail-closed behavior.
- **Handoff.** The [architecture](../docs/architecture.md), [contracts](../docs/contracts.md) and [runbook](../docs/runbook.md) document decisions, limitations and operational and ownership boundaries. The CI workflow runs the local validation entry point on Linux for Python 3.9 and 3.12. Retained test evidence records the local run. Hosted CI and organizational deployment approval require an external repository or owner workflow.
