# Reinforcement learning trading engine

An offline experiment comparing daily allocations to a synthetic USD asset and cash. A tabular Q-learning policy competes with cash, buy-and-hold and seeded random allocation under the same market path, costs, auction capacity and starting capital.

## Run locally

From this directory with Python 3.9, run the tests, generate a fresh evaluation and reproduce the retained results.

```sh
./scripts/test.sh
python3 scripts/demo.py
python3 scripts/reproduce.py
```

These commands use the standard library. The demo prints the path to its Markdown report and retains the decisions, configuration, candidate scores and inference policies alongside it. Each invocation creates a new directory. The checked-in [reference report](reports/reference/report.md) contains the results for [the default configuration](config/demo.json).

For the native Gymnasium interface and its upstream environment checker, install the pinned dependencies in an isolated environment.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-gym.txt
PYTHON=.venv/bin/python ./scripts/test.sh
```

```python
# Run with PYTHONPATH=src from this directory using the virtual environment.
from pathlib import Path
from trading_engine.gym_adapter import GymAllocationEnv
from trading_engine.market import load_fixture

env = GymAllocationEnv(load_fixture(Path("data/fixtures")))
state, account = env.reset(seed=731)
state, log_return, terminated, truncated, fill = env.step(1)  # target 50% exposure
```

[Design and contracts](docs/design.md) covers information timing, accounting, policy inference and evaluation. The [runbook and acceptance evidence](docs/runbook.md) covers reproduction, failure handling, dependencies and rollout status.
