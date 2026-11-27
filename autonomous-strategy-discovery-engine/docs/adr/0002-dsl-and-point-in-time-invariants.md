# ADR-0002: Constrained Declarative Strategy DSL and Point-in-Time Invariants

- **Status:** Accepted (M1 / M2)
- **Context:** Unconstrained code generation creates severe security risks (`eval`/`exec`), reproducibility failures, and subtle look-ahead leakage.
- **Decision:**
  1. Restrict strategies to declarative `StrategySpec` objects belonging to versioned families in `config/strategy_catalog.json` with strict parameter bounds and safe declarative constraints (no `eval()`).
  2. Explicitly reject `raw_code` or forbidden code-like parameter keys with `UnconstrainedCodeError`.
  3. Enforce `signal_lag_bars >= 1` and verify `event_time_utc <= available_time_utc <= next_bar_event_time_utc` for every bar during compilation, raising `LookAheadError` on any violation.
- **Consequences:** All candidate strategies are deterministic, inspectable, bounded, and structurally incapable of executing arbitrary code or peeking at future bars.
