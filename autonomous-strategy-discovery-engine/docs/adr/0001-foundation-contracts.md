# ADR-0001: Clean Foundation Contracts Over Unverified Repo Copying

- **Status:** Accepted (M1)
- **Context:** `plan.md` references three personal prototype repositories (`TS-14`, `TS-06`, `QT-09`) and specifies: *"Confirm access, licenses, background IP and SAAT ownership terms before copying or adapting any personal repository. If access or licensing is unresolved, implement against clean, documented contracts instead."*
- **Decision:** Implement clean internal reference modules behind explicit `Protocol` boundaries (`BacktesterAdapter`, `OptimizerAdapter`, `TrialStore`) and a versioned JSON `StrategyCatalog` schema (`dsl_version: "1.0.0"`). Do not copy external repository code until licensing and IP ownership are formally confirmed.
- **Consequences:** Zero external IP risk, zero mandatory external runtime dependencies on clean checkouts, and straightforward future integration of TS-06, TS-14, QT-09, Optuna, Polars, or PostgreSQL by implementing the documented protocols.
