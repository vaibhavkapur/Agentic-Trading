"""Host-side isolated sandbox runners (subprocess isolated + optional Docker adapter).

Runs untrusted strategy code in an isolated child process with:
- Zero host environment variables (no secrets, tokens, or broker credentials)
- Fresh empty temporary working directory
- Process-group isolation and hard wall-clock watchdog termination
- Output byte cap, step cap, CPU rlimit, FD cap, and traced memory budget
- Causal step-by-step protocol integrated with trusted PaperPortfolioEngine
"""

from __future__ import annotations

import json
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from .contracts import (
    DatasetManifest,
    ExperimentBudget,
    OrderIntent,
    SandboxExecutionResult,
    StrategySpec,
)
from .paper_engine import PaperPortfolioEngine, group_bars_by_timestamp

_WORKER_SCRIPT = Path(__file__).resolve().parent / "_worker.py"


class SandboxRunnerProtocol(Protocol):
    backend_name: str

    def run(
        self,
        *,
        code: str,
        dataset: DatasetManifest,
        spec: StrategySpec,
        budget: ExperimentBudget,
        allowed_imports: list[str],
    ) -> tuple[SandboxExecutionResult, PaperPortfolioEngine]:
        ...


def _kill_process_group(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def _readline_bounded(
    stream_fd: int,
    *,
    deadline: float,
    max_bytes: int,
    remaining_total_bytes: int,
) -> tuple[bytes | None, bool, bool]:
    """Read a single newline-terminated line with wall-clock deadline and byte cap.

    Returns (line_bytes_or_none, timed_out, output_limit_exceeded).
    """
    buf = bytearray()
    cap = min(max_bytes, remaining_total_bytes)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, True, False
        ready, _, _ = select.select([stream_fd], [], [], min(remaining, 0.05))
        if not ready:
            continue
        chunk = os.read(stream_fd, 1)
        if not chunk:
            return (bytes(buf) if buf else None), False, False
        buf.extend(chunk)
        if len(buf) > cap:
            return None, False, True
        if chunk == b"\n":
            return bytes(buf), False, False


class SubprocessSandboxRunner:
    """Resource-bounded, environment-scrubbed local subprocess sandbox runner."""

    backend_name = "subprocess_isolated"

    def run(
        self,
        *,
        code: str,
        dataset: DatasetManifest,
        spec: StrategySpec,
        budget: ExperimentBudget,
        allowed_imports: list[str],
    ) -> tuple[SandboxExecutionResult, PaperPortfolioEngine]:
        engine = PaperPortfolioEngine(spec)
        grouped_steps = group_bars_by_timestamp(dataset)
        orders_by_step: list[list[OrderIntent]] = []

        if len(grouped_steps) > budget.max_steps:
            return (
                SandboxExecutionResult(
                    succeeded=False,
                    exit_code=None,
                    error_code="RESOURCE_LIMIT_EXCEEDED",
                    error_message=f"Dataset step count {len(grouped_steps)} exceeds budget max_steps {budget.max_steps}.",
                    wall_time_sec=0.0,
                    steps_executed=0,
                ),
                engine,
            )

        start_time = time.monotonic()
        deadline = start_time + budget.max_wall_time_sec
        total_output_bytes = 0
        peak_traced_mem = 0
        caps: dict[str, Any] = {}

        # Strictly clean environment: zero host secrets, API keys, or broker credentials
        clean_env = {
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": str(spec.seed),
            "LC_ALL": "C",
        }

        with tempfile.TemporaryDirectory(prefix="strategy_sandbox_") as tmpdir:
            proc = subprocess.Popen(
                [sys.executable, "-I", "-S", str(_WORKER_SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=tmpdir,
                env=clean_env,
                start_new_session=True,
                close_fds=True,
            )

            assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
            stdout_fd = proc.stdout.fileno()

            try:
                init_payload = {
                    "code": code,
                    "seed": spec.seed,
                    "allowed_imports": allowed_imports,
                    "max_cpu_time_sec": budget.max_cpu_time_sec,
                    "max_memory_mb": budget.max_memory_mb,
                    "max_steps": budget.max_steps,
                    "params": spec.params,
                }
                proc.stdin.write(
                    (json.dumps(init_payload, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
                )
                proc.stdin.flush()

                raw_ready, timed_out, out_exceeded = _readline_bounded(
                    stdout_fd,
                    deadline=deadline,
                    max_bytes=budget.max_output_bytes,
                    remaining_total_bytes=budget.max_output_bytes - total_output_bytes,
                )
                if timed_out:
                    _kill_process_group(proc)
                    return self._fail(
                        engine,
                        start_time=start_time,
                        timed_out=True,
                        exit_code=proc.returncode,
                        error_code="SANDBOX_TIMEOUT",
                        error_message=f"Strategy initialization exceeded wall-time budget ({budget.max_wall_time_sec}s).",
                        output_bytes=total_output_bytes,
                        peak_mem=peak_traced_mem,
                        steps_executed=0,
                        caps=caps,
                    )
                if out_exceeded:
                    _kill_process_group(proc)
                    return self._fail(
                        engine,
                        start_time=start_time,
                        exit_code=proc.returncode,
                        error_code="RESOURCE_LIMIT_EXCEEDED",
                        error_message=f"Strategy output exceeded max_output_bytes ({budget.max_output_bytes}).",
                        output_bytes=budget.max_output_bytes,
                        peak_mem=peak_traced_mem,
                        steps_executed=0,
                        caps=caps,
                    )
                if raw_ready is None:
                    _kill_process_group(proc)
                    stderr_snippet = proc.stderr.read(512).decode("utf-8", errors="replace").strip()
                    code_str = self._classify_signal_exit(proc.returncode)
                    return self._fail(
                        engine,
                        start_time=start_time,
                        exit_code=proc.returncode,
                        error_code=code_str,
                        error_message=stderr_snippet or f"Worker terminated unexpectedly (exit={proc.returncode}).",
                        output_bytes=total_output_bytes,
                        peak_mem=peak_traced_mem,
                        steps_executed=0,
                        caps=caps,
                    )

                total_output_bytes += len(raw_ready)
                ready_msg = json.loads(raw_ready.decode("utf-8"))
                caps = ready_msg.get("caps", {})
                if not ready_msg.get("ok"):
                    _kill_process_group(proc)
                    return self._fail(
                        engine,
                        start_time=start_time,
                        exit_code=proc.returncode,
                        error_code=str(ready_msg.get("error_code", "SANDBOX_EXECUTION_ERROR")),
                        error_message=str(ready_msg.get("error_message", "Worker rejected strategy.")),
                        output_bytes=total_output_bytes,
                        peak_mem=peak_traced_mem,
                        steps_executed=0,
                        caps=caps,
                    )

                for step_idx, (ts, current_bars) in enumerate(grouped_steps):
                    step_msg = {
                        "cmd": "step",
                        "step": step_idx,
                        "timestamp": ts.isoformat().replace("+00:00", "Z"),
                        "cash": engine.cash,
                        "equity": engine.mark_to_market_equity(current_bars),
                        "positions": engine.current_positions_snapshot(current_bars),
                        "bars": {
                            sym: {
                                "timestamp": b.timestamp.isoformat().replace("+00:00", "Z"),
                                "symbol": b.symbol,
                                "open": b.open,
                                "high": b.high,
                                "low": b.low,
                                "close": b.close,
                                "volume": b.volume,
                            }
                            for sym, b in sorted(current_bars.items())
                        },
                    }
                    try:
                        proc.stdin.write(
                            (json.dumps(step_msg, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
                        )
                        proc.stdin.flush()
                    except BrokenPipeError:
                        _kill_process_group(proc)
                        return self._fail(
                            engine,
                            start_time=start_time,
                            exit_code=proc.returncode,
                            error_code=self._classify_signal_exit(proc.returncode),
                            error_message="Worker closed stdin pipe prematurely.",
                            output_bytes=total_output_bytes,
                            peak_mem=peak_traced_mem,
                            steps_executed=step_idx,
                            caps=caps,
                        )

                    raw_resp, timed_out, out_exceeded = _readline_bounded(
                        stdout_fd,
                        deadline=deadline,
                        max_bytes=budget.max_output_bytes,
                        remaining_total_bytes=budget.max_output_bytes - total_output_bytes,
                    )
                    if timed_out:
                        _kill_process_group(proc)
                        return self._fail(
                            engine,
                            start_time=start_time,
                            timed_out=True,
                            exit_code=proc.returncode,
                            error_code="SANDBOX_TIMEOUT",
                            error_message=f"Strategy execution exceeded wall-time budget ({budget.max_wall_time_sec}s) at step {step_idx}.",
                            output_bytes=total_output_bytes,
                            peak_mem=peak_traced_mem,
                            steps_executed=step_idx,
                            caps=caps,
                        )
                    if out_exceeded:
                        _kill_process_group(proc)
                        return self._fail(
                            engine,
                            start_time=start_time,
                            exit_code=proc.returncode,
                            error_code="RESOURCE_LIMIT_EXCEEDED",
                            error_message=f"Strategy output exceeded max_output_bytes ({budget.max_output_bytes}) at step {step_idx}.",
                            output_bytes=budget.max_output_bytes,
                            peak_mem=peak_traced_mem,
                            steps_executed=step_idx,
                            caps=caps,
                        )
                    if raw_resp is None:
                        _kill_process_group(proc)
                        stderr_snippet = proc.stderr.read(512).decode("utf-8", errors="replace").strip()
                        return self._fail(
                            engine,
                            start_time=start_time,
                            exit_code=proc.returncode,
                            error_code=self._classify_signal_exit(proc.returncode),
                            error_message=stderr_snippet or f"Worker terminated at step {step_idx} (exit={proc.returncode}).",
                            output_bytes=total_output_bytes,
                            peak_mem=peak_traced_mem,
                            steps_executed=step_idx,
                            caps=caps,
                        )

                    total_output_bytes += len(raw_resp)
                    resp = json.loads(raw_resp.decode("utf-8"))
                    peak_traced_mem = max(peak_traced_mem, int(resp.get("peak_memory_bytes", 0)))

                    if not resp.get("ok"):
                        _kill_process_group(proc)
                        return self._fail(
                            engine,
                            start_time=start_time,
                            exit_code=proc.returncode,
                            error_code=str(resp.get("error_code", "SANDBOX_EXECUTION_ERROR")),
                            error_message=str(resp.get("error_message", "Strategy raised an error.")),
                            output_bytes=total_output_bytes,
                            peak_mem=peak_traced_mem,
                            steps_executed=step_idx,
                            caps=caps,
                        )

                    step_orders: list[OrderIntent] = []
                    for raw_ord in resp.get("orders", []):
                        try:
                            step_orders.append(OrderIntent.model_validate(raw_ord))
                        except ValidationError as exc:
                            _kill_process_group(proc)
                            return self._fail(
                                engine,
                                start_time=start_time,
                                exit_code=proc.returncode,
                                error_code="CONTRACT_VALIDATION_ERROR",
                                error_message=f"Invalid order contract at step {step_idx}: {exc.errors()[0]['msg']}",
                                output_bytes=total_output_bytes,
                                peak_mem=peak_traced_mem,
                                steps_executed=step_idx,
                                caps=caps,
                            )

                    orders_by_step.append(step_orders)
                    engine.process_step(
                        step=step_idx,
                        timestamp=ts,
                        current_bars=current_bars,
                        orders=step_orders,
                    )

                # Graceful shutdown
                try:
                    proc.stdin.write(b'{"cmd":"shutdown"}\n')
                    proc.stdin.flush()
                    proc.stdin.close()
                except OSError:
                    pass
                try:
                    raw_done, _, _ = _readline_bounded(
                        stdout_fd,
                        deadline=min(deadline + 0.5, time.monotonic() + 0.5),
                        max_bytes=4096,
                        remaining_total_bytes=4096,
                    )
                    if raw_done:
                        done_msg = json.loads(raw_done.decode("utf-8"))
                        peak_traced_mem = max(peak_traced_mem, int(done_msg.get("peak_memory_bytes", 0)))
                except Exception:
                    pass
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    _kill_process_group(proc)

                return (
                    SandboxExecutionResult(
                        succeeded=True,
                        exit_code=proc.returncode,
                        timed_out=False,
                        wall_time_sec=round(time.monotonic() - start_time, 6),
                        peak_traced_memory_bytes=peak_traced_mem,
                        output_bytes=total_output_bytes,
                        steps_executed=len(grouped_steps),
                        orders_by_step=orders_by_step,
                        isolation_capabilities={
                            **caps,
                            "clean_env": True,
                            "isolated_temp_cwd": True,
                            "python_isolated_flag": True,
                            "network_disabled_in_worker": True,
                            "filesystem_disabled_in_worker": True,
                        },
                    ),
                    engine,
                )
            finally:
                if proc.poll() is None:
                    _kill_process_group(proc)

    @staticmethod
    def _classify_signal_exit(exit_code: int | None) -> str:
        if exit_code is None:
            return "SANDBOX_EXECUTION_ERROR"
        if exit_code < 0:
            sig = -exit_code
            if sig in (signal.SIGXCPU, signal.SIGKILL):
                return "RESOURCE_LIMIT_EXCEEDED"
        return "SANDBOX_EXECUTION_ERROR"

    @staticmethod
    def _fail(
        engine: PaperPortfolioEngine,
        *,
        start_time: float,
        exit_code: int | None,
        error_code: str,
        error_message: str,
        output_bytes: int,
        peak_mem: int,
        steps_executed: int,
        caps: dict[str, Any],
        timed_out: bool = False,
    ) -> tuple[SandboxExecutionResult, PaperPortfolioEngine]:
        return (
            SandboxExecutionResult(
                succeeded=False,
                exit_code=exit_code,
                timed_out=timed_out,
                error_code=error_code,
                error_message=error_message,
                wall_time_sec=round(time.monotonic() - start_time, 6),
                peak_traced_memory_bytes=peak_mem,
                output_bytes=output_bytes,
                steps_executed=steps_executed,
                isolation_capabilities=caps,
            ),
            engine,
        )


class DockerSandboxRunner:
    """Optional rootless Docker container runner adapter.

    Explicitly detects whether Docker is installed and reachable; fails cleanly
    with UNSUPPORTED_BACKEND if Docker is unavailable in the host environment.
    """

    backend_name = "docker_rootless"

    def __init__(self, image: str = "ai-strategy-code-generation-sandbox:latest") -> None:
        self.image = image

    @staticmethod
    def is_available() -> bool:
        return shutil.which("docker") is not None

    def run(
        self,
        *,
        code: str,
        dataset: DatasetManifest,
        spec: StrategySpec,
        budget: ExperimentBudget,
        allowed_imports: list[str],
    ) -> tuple[SandboxExecutionResult, PaperPortfolioEngine]:
        engine = PaperPortfolioEngine(spec)
        if not self.is_available():
            return (
                SandboxExecutionResult(
                    succeeded=False,
                    exit_code=None,
                    error_code="UNSUPPORTED_BACKEND",
                    error_message=(
                        "Docker CLI/daemon is not available in this environment. "
                        "Use 'subprocess_isolated' backend or install rootless Docker/Podman."
                    ),
                    wall_time_sec=0.0,
                    isolation_capabilities={"docker_available": False},
                ),
                engine,
            )
        # When Docker is installed, run the same _worker.py protocol inside
        # docker run --rm -i --network=none --read-only --cap-drop=ALL ...
        return (
            SandboxExecutionResult(
                succeeded=False,
                exit_code=None,
                error_code="UNSUPPORTED_BACKEND",
                error_message="Docker image execution requires pre-building the local container image via Dockerfile.",
                wall_time_sec=0.0,
                isolation_capabilities={"docker_available": True, "image": self.image},
            ),
            engine,
        )
