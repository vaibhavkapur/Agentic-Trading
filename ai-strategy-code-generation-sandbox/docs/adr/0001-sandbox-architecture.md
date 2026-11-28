# ADR-0001: Causal Step-by-Step Isolated Subprocess Sandbox with Layered Defenses

- **Status:** Accepted
- **Date:** 2026-11-28
- **Project:** AI Strategy Code Generation Sandbox (`ai-strategy-code-generation-sandbox`)

## Context

Evaluating AI-generated trading strategy code requires defending against three distinct risk classes simultaneously:

1. **Host & credential compromise**: Generated code may attempt filesystem reads, outbound network calls, subprocess execution, secret environment inspection, or Python object-graph escapes (`__subclasses__`).
2. **Resource exhaustion**: Infinite loops, memory bombs, stdout flooding, or AST complexity bombs can stall or crash evaluation workers.
3. **Research integrity failures**: Lookahead (future-data) leakage, nondeterministic behavior, corrupted paper accounting, prompt-injection payloads hidden in datasets, or unreviewed code promotion.

## Decision

We adopt a **host-trusted, step-by-step IPC subprocess architecture** (`SubprocessSandboxRunner` + `_worker.py`) backed by:

1. Pre-execution dataset untrusted-text screening (`data_sanitizer.py`) and static AST policy verification (`static_analyzer.py`).
2. A single isolated child Python process (`python -I -S`) per trial run in a clean temporary directory with zero host environment variables, `RLIMIT_CPU`/`RLIMIT_NOFILE`/`RLIMIT_CORE` (plus `RLIMIT_AS` on Linux), PEP 578 `sys.addaudithook`, restricted `__builtins__`, and `tracemalloc` memory accounting.
3. A **trusted host-side `PaperPortfolioEngine`** that streams only bar `t` and current portfolio state to the worker over stdin and validates/executes returned `OrderIntent` objects in the host process.
4. A pluggable `SandboxRunnerProtocol` so a hardened rootless Docker backend (`Dockerfile` / `docker-compose.yml` / `DockerSandboxRunner`) can be swapped in where a container runtime is available.

## Consequences

### Positive
- Future bars `t+1..T` never enter the worker process's address space during step `t`, eliminating an entire class of memory-inspection lookahead bugs.
- Paper accounting, risk limits, slippage, commissions, and artifact hashing remain 100% outside untrusted code's control.
- Full verification (primary run + determinism replay + 4 leakage probes) runs in ~190 ms median on synthetic fixtures, enabling rapid automated testing without requiring a Docker daemon on every developer workstation.

### Negative / Trade-offs
- Subprocess isolation is weaker than a hardware-virtualized microVM; documented explicitly as an educational/research prototype boundary.
- Docker container execution could not be live-tested on this host because Docker is not installed (`docker_available: false`); the adapter explicitly reports `UNSUPPORTED_BACKEND` instead of silently falling back.
