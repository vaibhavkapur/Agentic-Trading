# Assumptions, Known Limitations, Security & IP Review

## Explicit Assumptions

1. **Asset Class & Horizon (Prototype Default)**: Daily (`1D`) liquid USD-denominated synthetic equities (`SYN_TECH`, `SYN_IND`, `SYN_HLTH`, `SYN_ENER`, 1,800 trading bars / ~7.1 years) with post-close availability (`21:05:00Z` vs `21:00:00Z` close). Confirm actual SAAT asset class, horizon, and universe before connecting real market data.
2. **Execution Model**: Target weights computed from bars `<= t - signal_lag_bars` (`signal_lag_bars >= 1`) are rebalanced at bar `t` and earn close-to-close returns minus explicit linear costs (commission + half-spread + slippage), non-linear market impact (`traded_notional^1.5`), and daily short borrow.
3. **Turnover Unit**: Reported `annualized_turnover` is annualized two-sided traded notional divided by NAV (`mean(sum(|w_target - w_drifted|)) * 252`).
4. **Multiple-Testing Assumption**: Deflated Sharpe Ratio (DSR) assumes trials are approximately independent; when inner-tuning neighbors are correlated, using the full trial count `N` (inner + outer + failed) is conservative (reduces false positives).

## Explicit Unsupported Features (Out of MVP Scope)

- Unconstrained code generation or LLM-generated executable Python strategies.
- Live order routing, broker connectivity, or automated live strategy promotion.
- Intraday tick/order-book microstructure simulation, partial fills, queue priority, or corporate-action split/dividend adjustments.
- Multi-currency FX hedging, margin call liquidation dynamics, or options/futures roll schedules.
- Distributed multi-node cluster orchestration (optional PostgreSQL/Optuna/Polars adapters are documented as future extensions).

## Security, Data Licensing, IP, and Approval Review

- **Data Entitlements**: All committed fixtures in `data/fixtures/` are 100% synthetically generated (`entitlement: "permitted_internal_synthetic_fixture"`). No third-party licensed market data or PII is stored in the repository.
- **Secrets Hygiene**: Configuration files in `config/` contain zero credentials, API keys, or connection strings. Future database/broker credentials must be injected via environment variables or a secret manager outside code.
- **External Repository IP / Licensing**: Linked personal prototypes (`Trading-Software/14-ai-quant-research-agent`, `Trading-Software/06-event-driven-backtesting-engine`, `Quantum-Trading/09-quantum-strategy-optimizer`) were NOT copied; clean adapter protocols (`BacktesterAdapter`, `OptimizerAdapter`, `TrialStore`) were implemented instead pending formal SAAT IP/license clearance.
- **Deployment Approval Controls**: `order_execution_enabled` is hardcoded to `false` in discovery and exported packages. `ReviewGate` allows independent human approval for `paper_sandbox` only; any real-capital deployment requires a separate legal, regulatory, broker, security, and risk approval outside this system.
