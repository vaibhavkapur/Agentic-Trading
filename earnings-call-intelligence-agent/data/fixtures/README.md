# Synthetic Fixtures & Provenance

All JSON fixtures in this directory are **100% synthetic educational and research fixtures** created specifically for `earnings-call-intelligence-agent`.

- **No real customer data:** Fictional companies (`Acme Cloud Systems Inc.`, `Boreal Industrial Robotics Corp.`, `Meridian Semiconductor Labs Inc.`, `Northstar Logistics Group`) and fictional executive/analyst names are used throughout.
- **No live credentials or trade orders:** Zero API keys, brokerage details, or executable order payloads exist in any fixture.
- **No proprietary or employer/SAAT artifacts:** All transcripts, filing timestamps, prior guidance tables, and expected-result oracles are original synthetic text licensed under MIT for reproducible offline testing.

## Fixture Inventory

| File | Milestone / Scenario | Purpose |
|---|---|---|
| `reference_valid.json` | M1 / M2 | Deterministic reference call with reported metrics, forward guidance, prior guidance, and QA |
| `reference_expected.json` | M1 / M2 | Hand-calculated independent oracle for `reference_valid.json` |
| `contradictory_guidance.json` | M2 | Contradictory guidance across speakers/sections, mixed units ($B vs $M, % vs bps), GAAP vs non-GAAP, fiscal periods |
| `prompt_injection.json` | M3 | Adversarial prompt injections embedded inside transcript segments (instruction override, fake revenue, buy-order injection) |
| `stale_and_unanswerable.json` | M4 | Stale transcript beyond freshness SLA and unanswerable questions lacking transcript support |
| `invalid_inputs.json` | M1 / M2 | Malformed, unsupported, and boundary inputs testing explicit validation errors |
| `gold_eval_suite.json` | M4 | Multi-case gold benchmark suite measuring extraction F1, citation validity, guidance accuracy, abstention, and injection defense |
