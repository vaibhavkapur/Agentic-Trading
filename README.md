# Agentic Trading

Thirteen independent Python projects use synthetic market data, filings, transcripts, macroeconomic releases, and telemetry fixtures to discover and test trading strategies, generate and sandbox strategy code, synthesize point-in-time research, earnings, macro, and sentiment evidence, govern multi-agent investment proposals, investigate trading incidents, evaluate reinforcement-learning allocation policies, and benchmark financial agents.

## Getting started

Start with the Autonomous Strategy Discovery Engine. Its demo uses Python 3.9 or later and the standard library to compare candidate strategies after trading costs.

```bash
git clone https://github.com/vaibhavkapur/Trading-Agentic.git
cd Trading-Agentic/autonomous-strategy-discovery-engine
bash scripts/setup.sh
bash scripts/demo.sh
```

Open [the demo leaderboard](autonomous-strategy-discovery-engine/reports/demo_leaderboard.md) to see which candidates passed the review criteria and how they compared with the baselines. Each project has its own dependencies, demo, and validation commands. Run them from that project's directory.

## Projects

- [Autonomous Strategy Discovery Engine](autonomous-strategy-discovery-engine/) — Tests candidate strategies on successive time windows, accounts for trading costs and repeated trials, and exports candidates for independent review.
- [Recursive AI Research Platform](recursive-ai-research-platform/) — Proposes and refines hypotheses within a fixed experiment budget. Its critic checks claims against recorded results, and its research registry keeps failed hypotheses for future runs.
- [Multi-Agent AI Trading Platform](multi-agent-ai-trading-platform/) — Combines research and portfolio proposals, checks them against risk limits, and requires human approval for the exact order before dispatch to a simulated broker.
- [Financial Research Agent](financial-research-agent/) — Builds point-in-time research briefs from synthetic filings and news bulletins with exact passage citations and analyst review decisions.
- [Financial Sentiment Analysis Engine](financial-sentiment-analysis-engine/) — Produces point-in-time issuer-level sentiment features from timestamped financial text with chronological calibration, abstention controls, and an offline evaluation dashboard.
- [Financial Intelligence RAG Platform](financial-intelligence-rag-platform/) — Combines keyword and dense-vector retrieval over synthetic filings and research notes with reader entitlements, point-in-time filtering, verifiable citations, and abstention when evidence is missing.
- [Reinforcement Learning Trading Engine](reinforcement-learning-trading-engine/) — Evaluates a tabular Q-learning daily allocation policy against cash, buy-and-hold, and seeded random baselines under shared costs, auction capacity limits, and reproducible walk-forward splits.
- [Earnings Call Intelligence Agent](earnings-call-intelligence-agent/) — Extracts verifiable financial metrics and forward guidance changes from synthetic earnings-call transcripts with verbatim character-span citations, contradiction detection, prompt-injection quarantine, and strict abstention.
- [Macro Intelligence Agent](macro-intelligence-agent/) — Tracks macroeconomic releases and central bank communication cues across vintages with strict UTC publication gates, verifiable citations, unit and conflict abstention guardrails, and SQLite replay.
- [AI Investment Committee](ai-investment-committee/) — Orchestrates isolated bull, bear, portfolio, and independent risk reviews for paper investment proposals with citation auditing, prompt-injection quarantine, non-overridable risk vetoes, and SHA-256 hash-bound human approval.
- [Trading Incident Investigation Agent](trading-incident-investigation-agent/) — Reconstructs simulated trading incidents from synthetic OpenTelemetry traces, structured logs, OMS events, alerts, and runbooks with calibrated multi-modality root-cause hypotheses and approval-gated simulated remediation.
- [AI Strategy Code Generation Sandbox](ai-strategy-code-generation-sandbox/) — Evaluates AI-generated trading strategy code in an isolated, resource-bounded subprocess sandbox with static AST allowlisting, future-data leakage probes, double-entry paper accounting, and hash-bound promotion gates.
- [Financial Agent Evaluation Framework](financial-agent-evaluation-framework/) — Evaluates financial agents offline across numeric correctness, citation faithfulness, HMAC-signed mock tool receipts, abstention discipline, failure injection, and confidence-interval reporting with deterministic replay.

Each project README links to its architecture, data contracts, integration boundaries, operator runbook, and validation evidence.
