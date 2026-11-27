# Agentic Trading

Three independent Python projects use synthetic market data to test trading strategies, review research evidence, and simulate the approval and execution of paper orders.

## Getting started

Start with the Autonomous Strategy Discovery Engine. Its demo uses Python 3.9 or later and the standard library to compare candidate strategies after trading costs.

```bash
git clone https://github.com/vaibhavkapur/Agentic-Trading.git
cd Agentic-Trading/autonomous-strategy-discovery-engine
bash scripts/setup.sh
bash scripts/demo.sh
```

Open [the demo leaderboard](autonomous-strategy-discovery-engine/reports/demo_leaderboard.md) to see which candidates passed the review criteria and how they compared with the baselines. Each project has its own setup and validation commands. Run them from the project directory.

## Projects

- [Autonomous Strategy Discovery Engine](autonomous-strategy-discovery-engine/) — Tests candidate strategies on successive time windows, accounts for trading costs and repeated trials, and exports candidates for independent review.
- [Recursive AI Research Platform](recursive-ai-research-platform/) — Proposes and refines hypotheses within a fixed experiment budget. Its critic checks claims against recorded results, and its research registry keeps failed hypotheses for future runs.
- [Multi-Agent AI Trading Platform](multi-agent-ai-trading-platform/) — Combines research and portfolio proposals, checks them against risk limits, and requires human approval for the exact order before dispatch to a simulated broker.

Each project README links to its architecture, API reference, and operator runbook.
