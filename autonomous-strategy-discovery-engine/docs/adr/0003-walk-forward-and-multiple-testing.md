# ADR-0003: Chronological Purged/Embargoed Walk-Forward and Full-Trial Multiple-Testing Accounting

- **Status:** Accepted (M2 / M3 / M4)
- **Context:** Evaluating many parameter combinations on overlapping periods or dropping failed trials leads to severe selection bias and false discoveries.
- **Decision:**
  1. Enforce immutable chronological `train / validation / test` splits with `embargo_bars` gaps and cryptographic SHA-256 `manifest_hash`.
  2. Perform nested inner parameter tuning strictly inside `train` (`inner_folds`), outer evaluation strictly on non-overlapping `walk_forward_folds` inside `validation`, and lock out `test` via `HoldoutGuard` during selection.
  3. Record **every** trial (inner, outer, baseline, rejected, and failed) into an append-only SQLite + JSONL ledger (`SqliteTrialStore`).
  4. Apply Probabilistic Sharpe Ratio (PSR), Deflated Sharpe Ratio (DSR), Bonferroni, Holm-Bonferroni, and Benjamini-Hochberg FDR using the full candidate trial count `N`.
- **Consequences:** Honest reporting of uncertainty and failed candidates; strong protection against multiple-testing inflation on noisy series.
