"""Isolated worker process for executing untrusted strategy code step-by-step.

Security layers applied inside this worker BEFORE executing user code:
1. Launched by host in a clean temporary working directory with zero host env vars.
2. OS resource limits (RLIMIT_CPU, RLIMIT_NOFILE, RLIMIT_AS where supported).
3. Defense-in-depth monkey-patching of socket/urllib/http/open/os/subprocess APIs
   so any attempted network, filesystem, or process access raises SecurityError.
4. Strictly allowlisted __builtins__ and restricted __import__.
5. Causal step-by-step JSONL protocol over stdin/stdout: future bars are never
   present in worker memory.
6. Live memory tracking via tracemalloc against max_memory_mb budget.
"""

from __future__ import annotations

import ast
import builtins
import io
import json
import math
import os
import random
import resource
import socket
import statistics
import subprocess
import sys
import tracemalloc
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


class _SandboxSecurityViolation(RuntimeError):
    pass


class _SandboxMemoryExceeded(MemoryError):
    pass


@dataclass(frozen=True, slots=True)
class _BarView:
    timestamp: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class _PositionView:
    symbol: str
    quantity: float
    avg_cost: float
    market_value: float


class _DeterministicRNG:
    __slots__ = ("_rng",)

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def random(self) -> float:
        return self._rng.random()

    def uniform(self, a: float, b: float) -> float:
        return self._rng.uniform(a, b)

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        return self._rng.gauss(mu, sigma)

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)


class _StrategyContext:
    __slots__ = (
        "_step",
        "_timestamp",
        "_current_bars",
        "_history_by_symbol",
        "_cash",
        "_equity",
        "_positions",
        "_params",
        "_state",
        "_rng",
    )

    def __init__(
        self,
        *,
        step: int,
        timestamp: str,
        current_bars: dict[str, _BarView],
        history_by_symbol: dict[str, list[_BarView]],
        cash: float,
        equity: float,
        positions: dict[str, _PositionView],
        params: dict[str, Any],
        state: dict[str, Any],
        rng: _DeterministicRNG,
    ) -> None:
        self._step = step
        self._timestamp = timestamp
        self._current_bars = MappingProxyType(dict(current_bars))
        self._history_by_symbol = {sym: tuple(bars) for sym, bars in history_by_symbol.items()}
        self._cash = cash
        self._equity = equity
        self._positions = MappingProxyType(dict(positions))
        self._params = MappingProxyType(dict(params))
        self._state = state
        self._rng = rng

    @property
    def step(self) -> int:
        return self._step

    @property
    def timestamp(self) -> str:
        return self._timestamp

    @property
    def current_bars(self) -> Any:
        return self._current_bars

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def positions(self) -> Any:
        return self._positions

    @property
    def params(self) -> Any:
        return self._params

    @property
    def state(self) -> dict[str, Any]:
        return self._state

    @property
    def rng(self) -> _DeterministicRNG:
        return self._rng

    def history(self, symbol: str, lookback: int | None = None) -> tuple[_BarView, ...]:
        bars = self._history_by_symbol.get(symbol, ())
        if lookback is None:
            return bars
        if not isinstance(lookback, int) or lookback <= 0:
            raise ValueError("lookback must be a positive integer")
        return bars[-lookback:]

    def position_qty(self, symbol: str) -> float:
        pos = self._positions.get(symbol)
        return pos.quantity if pos is not None else 0.0


def _apply_os_limits(max_cpu_sec: float, max_memory_mb: int) -> dict[str, Any]:
    caps: dict[str, Any] = {
        "rlimit_cpu_applied": False,
        "rlimit_nofile_applied": False,
        "rlimit_as_applied": False,
        "rlimit_core_disabled": False,
        "tracemalloc_enabled": True,
    }
    cpu_int = max(1, int(math.ceil(max_cpu_sec)))
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_int, cpu_int))
        caps["rlimit_cpu_applied"] = True
    except (ValueError, OSError):
        pass

    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        caps["rlimit_core_disabled"] = True
    except (ValueError, OSError):
        pass

    # Cap file descriptors tightly so new files/sockets cannot be opened easily
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(16, hard)
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, min(target, hard)))
        caps["rlimit_nofile_applied"] = True
    except (ValueError, OSError):
        pass

    # RLIMIT_AS works reliably on Linux; on macOS ARM64 virtual reservations may reject small caps
    if sys.platform.startswith("linux"):
        mem_bytes = max(256, max_memory_mb * 2) * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            caps["rlimit_as_applied"] = True
        except (ValueError, OSError):
            pass

    return caps


def _install_audit_hook(allowed_imports: list[str]) -> bool:
    """Install PEP 578 CPython audit hook denying OS, network, FS, and dynamic exec."""
    allowed_set = set(allowed_imports)
    blocked_prefixes = (
        "socket.",
        "http.",
        "urllib.",
        "ftplib.",
        "smtplib.",
        "telnetlib.",
        "subprocess.",
        "os.system",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.exec",
        "os.listdir",
        "os.scandir",
        "os.remove",
        "os.unlink",
        "os.mkdir",
        "os.rename",
        "os.chmod",
        "os.chown",
        "os.truncate",
        "shutil.",
        "ctypes.",
        "winreg.",
        "webbrowser.",
        "tempfile.",
    )
    hook_active = {"loaded": False}

    def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
        if event == "open" or event.startswith(blocked_prefixes):
            raise _SandboxSecurityViolation(f"Audit hook denied forbidden operation '{event}'")
        if event == "import":
            mod_name = str(args[0]) if args else ""
            if mod_name.split(".", 1)[0] not in allowed_set:
                raise _SandboxSecurityViolation(f"Audit hook denied import '{mod_name}'")
        if hook_active["loaded"] and event in ("compile", "exec"):
            raise _SandboxSecurityViolation(f"Audit hook denied dynamic '{event}' inside strategy")

    sys.addaudithook(_audit_hook)
    _install_audit_hook._state = hook_active  # type: ignore[attr-defined]
    return True


def _reject_dunder_ast(code: str) -> None:
    """Defense-in-depth worker-side AST check blocking dunder attribute/name escapes."""
    tree = ast.parse(code, filename="<strategy_proposal>", mode="exec")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("__") or node.attr.endswith("__")
        ):
            raise _SandboxSecurityViolation(
                f"Worker AST guard denied dunder attribute access '{node.attr}'"
            )
        if isinstance(node, ast.Name) and node.id.startswith("__") and node.id.endswith("__"):
            raise _SandboxSecurityViolation(
                f"Worker AST guard denied dunder name access '{node.id}'"
            )


def _install_runtime_denial_hooks() -> None:
    def _deny_network(*args: Any, **kwargs: Any) -> Any:
        raise _SandboxSecurityViolation("Network access is denied in sandbox")

    def _deny_fs(*args: Any, **kwargs: Any) -> Any:
        raise _SandboxSecurityViolation("Filesystem access is denied in sandbox")

    def _deny_proc(*args: Any, **kwargs: Any) -> Any:
        raise _SandboxSecurityViolation("Process execution is denied in sandbox")

    socket.socket = _deny_network  # type: ignore[assignment]
    socket.create_connection = _deny_network  # type: ignore[assignment]
    socket.getaddrinfo = _deny_network  # type: ignore[assignment]
    builtins.open = _deny_fs  # type: ignore[assignment]
    io.open = _deny_fs  # type: ignore[assignment]
    os.open = _deny_fs  # type: ignore[assignment]
    os.remove = _deny_fs  # type: ignore[assignment]
    os.unlink = _deny_fs  # type: ignore[assignment]
    os.mkdir = _deny_fs  # type: ignore[assignment]
    os.makedirs = _deny_fs  # type: ignore[assignment]
    os.listdir = _deny_fs  # type: ignore[assignment]
    os.system = _deny_proc  # type: ignore[assignment]
    os.popen = _deny_proc  # type: ignore[assignment]
    subprocess.Popen = _deny_proc  # type: ignore[assignment]


def _make_safe_builtins(allowed_imports: list[str]) -> dict[str, Any]:
    allowed_modules: dict[str, Any] = {
        "math": math,
        "statistics": statistics,
    }
    permitted = {name: allowed_modules[name] for name in allowed_imports if name in allowed_modules}

    def _restricted_import(
        name: str,
        globals_: Any = None,
        locals_: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ) -> Any:
        if level != 0 or name not in permitted:
            raise _SandboxSecurityViolation(f"Import '{name}' is denied in sandbox")
        return permitted[name]

    def _denied_open(*args: Any, **kwargs: Any) -> Any:
        raise _SandboxSecurityViolation("Filesystem access via open() is denied in sandbox")

    def _denied_eval(*args: Any, **kwargs: Any) -> Any:
        raise _SandboxSecurityViolation("Dynamic code execution is denied in sandbox")

    return {
        "__import__": _restricted_import,
        "open": _denied_open,
        "eval": _denied_eval,
        "exec": _denied_eval,
        "compile": _denied_eval,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "divmod": divmod,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "frozenset": frozenset,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "pow": pow,
        "range": range,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "KeyError": KeyError,
        "IndexError": IndexError,
        "ZeroDivisionError": ZeroDivisionError,
        "RuntimeError": RuntimeError,
    }


def _send(out_stream: Any, payload: dict[str, Any]) -> None:
    out_stream.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n")
    out_stream.flush()


def main() -> int:
    # Keep direct handles to stdin/stdout; neutralize print() inside untrusted code
    in_stream = sys.stdin
    out_stream = sys.stdout

    init_line = in_stream.readline()
    if not init_line:
        return 2

    init_msg = json.loads(init_line)
    code: str = init_msg["code"]
    seed: int = int(init_msg["seed"])
    allowed_imports: list[str] = list(init_msg.get("allowed_imports", ["math", "statistics"]))
    max_cpu_sec: float = float(init_msg["max_cpu_time_sec"])
    max_memory_mb: int = int(init_msg["max_memory_mb"])
    max_steps: int = int(init_msg["max_steps"])
    params: dict[str, Any] = dict(init_msg.get("params", {}))
    max_memory_bytes = max_memory_mb * 1024 * 1024

    tracemalloc.start()
    caps = _apply_os_limits(max_cpu_sec=max_cpu_sec, max_memory_mb=max_memory_mb)
    _install_runtime_denial_hooks()
    caps["pep578_audit_hook_enabled"] = _install_audit_hook(allowed_imports)

    safe_globals: dict[str, Any] = {"__builtins__": _make_safe_builtins(allowed_imports)}

    try:
        _reject_dunder_ast(code)
        compiled = compile(code, "<strategy_proposal>", "exec")
        exec(compiled, safe_globals, safe_globals)
        _install_audit_hook._state["loaded"] = True  # type: ignore[attr-defined]
    except _SandboxSecurityViolation as exc:
        _send(out_stream, {"ok": False, "error_code": "SECURITY_DENIAL", "error_message": str(exc), "caps": caps})
        return 11
    except MemoryError as exc:
        _send(out_stream, {"ok": False, "error_code": "RESOURCE_LIMIT_EXCEEDED", "error_message": f"Memory limit exceeded: {exc}", "caps": caps})
        return 12
    except Exception as exc:
        _send(out_stream, {"ok": False, "error_code": "STRATEGY_LOAD_ERROR", "error_message": f"{type(exc).__name__}: {exc}", "caps": caps})
        return 13

    on_bar = safe_globals.get("on_bar")
    if not callable(on_bar):
        _send(
            out_stream,
            {
                "ok": False,
                "error_code": "MISSING_ENTRYPOINT",
                "error_message": "Strategy code does not expose callable on_bar(ctx).",
                "caps": caps,
            },
        )
        return 14

    _send(out_stream, {"ok": True, "ready": True, "caps": caps})

    history_by_symbol: dict[str, list[_BarView]] = {}
    strategy_state: dict[str, Any] = {}
    rng = _DeterministicRNG(seed)
    steps_run = 0

    for raw_line in in_stream:
        if not raw_line.strip():
            continue
        msg = json.loads(raw_line)
        if msg.get("cmd") == "shutdown":
            _, peak = tracemalloc.get_traced_memory()
            _send(out_stream, {"ok": True, "done": True, "peak_memory_bytes": peak})
            return 0

        steps_run += 1
        if steps_run > max_steps:
            _send(
                out_stream,
                {
                    "ok": False,
                    "error_code": "RESOURCE_LIMIT_EXCEEDED",
                    "error_message": f"Step budget exceeded ({max_steps}).",
                },
            )
            return 12

        step_idx = int(msg["step"])
        timestamp = str(msg["timestamp"])
        current_bars: dict[str, _BarView] = {}
        for sym, b in msg["bars"].items():
            view = _BarView(
                timestamp=str(b["timestamp"]),
                symbol=str(b["symbol"]),
                open=float(b["open"]),
                high=float(b["high"]),
                low=float(b["low"]),
                close=float(b["close"]),
                volume=float(b["volume"]),
            )
            current_bars[sym] = view
            history_by_symbol.setdefault(sym, []).append(view)

        positions: dict[str, _PositionView] = {}
        for sym, p in msg["positions"].items():
            positions[sym] = _PositionView(
                symbol=str(p["symbol"]),
                quantity=float(p["quantity"]),
                avg_cost=float(p["avg_cost"]),
                market_value=float(p["market_value"]),
            )

        ctx = _StrategyContext(
            step=step_idx,
            timestamp=timestamp,
            current_bars=current_bars,
            history_by_symbol=history_by_symbol,
            cash=float(msg["cash"]),
            equity=float(msg["equity"]),
            positions=positions,
            params=params,
            state=strategy_state,
            rng=rng,
        )

        try:
            raw_orders = on_bar(ctx)
            current_mem, peak_mem = tracemalloc.get_traced_memory()
            if peak_mem > max_memory_bytes or current_mem > max_memory_bytes:
                raise _SandboxMemoryExceeded(
                    f"Traced memory {peak_mem} bytes exceeded budget {max_memory_bytes} bytes."
                )

            if raw_orders is None:
                normalized_orders: list[dict[str, Any]] = []
            elif isinstance(raw_orders, (list, tuple)):
                normalized_orders = []
                for item in raw_orders:
                    if not isinstance(item, dict):
                        raise TypeError(f"Order must be a dict, got {type(item).__name__}")
                    normalized_orders.append(
                        {
                            "symbol": str(item.get("symbol", "")),
                            "side": str(item.get("side", "")).upper(),
                            "quantity": float(item.get("quantity", 0.0)),
                            "order_type": str(item.get("order_type", "MARKET")).upper(),
                            "reason": str(item.get("reason", ""))[:160],
                        }
                    )
            else:
                raise TypeError(f"on_bar(ctx) must return list[dict] or None, got {type(raw_orders).__name__}")

            _send(
                out_stream,
                {
                    "ok": True,
                    "step": step_idx,
                    "orders": normalized_orders,
                    "peak_memory_bytes": peak_mem,
                },
            )
        except _SandboxSecurityViolation as exc:
            _send(out_stream, {"ok": False, "error_code": "SECURITY_DENIAL", "error_message": str(exc)})
            return 11
        except (_SandboxMemoryExceeded, MemoryError) as exc:
            _send(out_stream, {"ok": False, "error_code": "RESOURCE_LIMIT_EXCEEDED", "error_message": str(exc)})
            return 12
        except Exception as exc:
            _send(
                out_stream,
                {
                    "ok": False,
                    "error_code": "STRATEGY_RUNTIME_ERROR",
                    "error_message": f"{type(exc).__name__}: {exc}",
                },
            )
            return 15

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
