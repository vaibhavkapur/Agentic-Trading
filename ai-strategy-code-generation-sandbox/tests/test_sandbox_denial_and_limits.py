"""Security denial and resource-limit tests for the isolated strategy sandbox.

Covers:
- Infinite loop termination within wall-clock budget
- Memory allocation abuse caught within memory budget
- Output flooding abuse caught within max_output_bytes
- Attempted filesystem, network, subprocess, and dunder-escape access denied
  both at Layer 1 (static AST) and independently at Layer 2/3 (runtime sandbox)
- Environment secret scrubbing (no broker credentials visible in worker)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from strategy_sandbox import (
    DatasetManifest,
    ExperimentBudget,
    ExperimentEvaluator,
    SandboxConfig,
    StrategyProposal,
    StrategySpec,
    analyze_strategy_code,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures"


def _base_inputs() -> tuple[DatasetManifest, StrategySpec]:
    dataset = DatasetManifest.model_validate(
        json.loads((FIXTURES / "reference_dataset.json").read_text(encoding="utf-8"))
    )
    spec = StrategySpec.model_validate(
        json.loads((FIXTURES / "reference_spec.json").read_text(encoding="utf-8"))
    )
    return dataset, spec


def _proposal(proposal_id: str, code: str) -> StrategyProposal:
    return StrategyProposal(
        proposal_id=proposal_id,
        spec_id="sma-crossover-reference-v1",
        author_type="llm_generated",
        code=code,
    )


def test_infinite_loop_terminates_within_wall_budget() -> None:
    dataset, spec = _base_inputs()
    budget = ExperimentBudget(max_wall_time_sec=0.4, max_cpu_time_sec=0.4)
    prop = _proposal(
        "prop-inf-loop",
        "def on_bar(ctx):\n    while True:\n        pass\n",
    )

    evaluator = ExperimentEvaluator(config=SandboxConfig())
    t0 = time.monotonic()
    trial = evaluator.evaluate(proposal=prop, spec=spec, dataset=dataset, budget=budget)
    elapsed = time.monotonic() - t0

    assert trial.status == "FAILED_SANDBOX"
    sandbox_chk = next(c for c in trial.checks if c.name == "sandbox_execution")
    assert not sandbox_chk.passed
    assert sandbox_chk.code in ("SANDBOX_TIMEOUT", "RESOURCE_LIMIT_EXCEEDED")
    # Must terminate promptly without hanging
    assert elapsed < 3.0


def test_memory_abuse_terminated_within_budget() -> None:
    dataset, spec = _base_inputs()
    budget = ExperimentBudget(max_wall_time_sec=2.0, max_cpu_time_sec=1.5, max_memory_mb=16)
    prop = _proposal(
        "prop-mem-abuse",
        "def on_bar(ctx):\n    ctx.state['blob'] = [i for i in range(1_500_000)]\n    return []\n",
    )

    evaluator = ExperimentEvaluator(config=SandboxConfig())
    trial = evaluator.evaluate(proposal=prop, spec=spec, dataset=dataset, budget=budget)

    assert trial.status == "FAILED_SANDBOX"
    sandbox_chk = next(c for c in trial.checks if c.name == "sandbox_execution")
    assert not sandbox_chk.passed
    assert sandbox_chk.code == "RESOURCE_LIMIT_EXCEEDED"


def test_output_flood_abuse_blocked_by_output_byte_budget() -> None:
    dataset, spec = _base_inputs()
    budget = ExperimentBudget(max_wall_time_sec=2.0, max_output_bytes=2048)
    prop = _proposal(
        "prop-output-flood",
        (
            "def on_bar(ctx):\n"
            "    return [{'symbol': 'SYNTH_A', 'side': 'BUY', 'quantity': 1, 'reason': 'x' * 150} for _ in range(50)]\n"
        ),
    )

    evaluator = ExperimentEvaluator(config=SandboxConfig())
    trial = evaluator.evaluate(proposal=prop, spec=spec, dataset=dataset, budget=budget)

    assert trial.status == "FAILED_SANDBOX"
    sandbox_chk = next(c for c in trial.checks if c.name == "sandbox_execution")
    assert not sandbox_chk.passed
    assert sandbox_chk.code == "RESOURCE_LIMIT_EXCEEDED"


def test_code_size_and_ast_node_limits_enforced() -> None:
    budget = ExperimentBudget(max_code_bytes=128, max_ast_nodes=40)
    big_code = "def on_bar(ctx):\n" + "    x = 1 + 2\n" * 30 + "    return []\n"
    res = analyze_strategy_code(big_code, budget)
    assert not res.passed
    assert res.code == "STATIC_POLICY_VIOLATION"


@pytest.mark.parametrize(
    "case_name,malicious_code",
    [
        ("file_open", "def on_bar(ctx):\n    open('/etc/passwd').read()\n    return []\n"),
        ("network_socket", "import socket\ndef on_bar(ctx):\n    socket.create_connection(('1.1.1.1', 80))\n    return []\n"),
        ("network_urllib", "import urllib.request\ndef on_bar(ctx):\n    urllib.request.urlopen('https://example.com')\n    return []\n"),
        ("os_system", "import os\ndef on_bar(ctx):\n    os.system('echo pwned')\n    return []\n"),
        ("subprocess_call", "import subprocess\ndef on_bar(ctx):\n    subprocess.Popen(['ls'])\n    return []\n"),
        ("dunder_escape", "def on_bar(ctx):\n    x = ().__class__.__bases__[0].__subclasses__()\n    return []\n"),
        ("eval_exec", "def on_bar(ctx):\n    eval('1+1')\n    return []\n"),
    ],
)
def test_file_network_process_and_escape_denied_statically_and_at_runtime(
    case_name: str,
    malicious_code: str,
) -> None:
    dataset, spec = _base_inputs()
    prop = _proposal(f"prop-{case_name}", malicious_code)
    evaluator = ExperimentEvaluator(config=SandboxConfig())

    # Layer 1: Static AST policy catches it before spawning a subprocess
    trial_static = evaluator.evaluate(proposal=prop, spec=spec, dataset=dataset)
    assert trial_static.status == "FAILED_STATIC_POLICY"
    assert trial_static.telemetry["counters"]["sandbox_invocations"] == 0

    # Layer 2/3 defense-in-depth: even if static policy is bypassed, runtime worker denies it
    trial_runtime = evaluator.evaluate(
        proposal=prop,
        spec=spec,
        dataset=dataset,
        skip_static_policy=True,
    )
    assert trial_runtime.status == "FAILED_SANDBOX"
    sandbox_chk = next(c for c in trial_runtime.checks if c.name == "sandbox_execution")
    assert not sandbox_chk.passed
    assert sandbox_chk.code in ("SECURITY_DENIAL", "STRATEGY_RUNTIME_ERROR", "STRATEGY_LOAD_ERROR")


def test_host_secrets_and_broker_credentials_not_visible_to_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROKER_API_KEY", "fake-test-broker-secret-value")
    monkeypatch.setenv("LIVE_ACCOUNT_TOKEN", "fake-test-token")

    dataset, spec = _base_inputs()
    # Try to import os at runtime (bypassing static policy) to verify both import denial & clean env
    prop = _proposal(
        "prop-env-probe",
        "import os\ndef on_bar(ctx):\n    _ = os.environ.get('BROKER_API_KEY')\n    return []\n",
    )
    evaluator = ExperimentEvaluator(config=SandboxConfig())
    trial = evaluator.evaluate(
        proposal=prop,
        spec=spec,
        dataset=dataset,
        skip_static_policy=True,
    )
    assert trial.status == "FAILED_SANDBOX"
    sandbox_chk = next(c for c in trial.checks if c.name == "sandbox_execution")
    assert sandbox_chk.code == "SECURITY_DENIAL"
    assert "fake-test-broker-secret-value" not in sandbox_chk.message
