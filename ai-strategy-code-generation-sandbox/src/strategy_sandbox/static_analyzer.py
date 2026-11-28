"""Static AST security policy analyzer for generated strategy code.

Defense-in-depth Layer 1: inspect untrusted Python source before spawning
the isolated worker subprocess. Rejects disallowed imports, dangerous builtins,
dunder attribute traversal, excessive code size, and AST node bombs.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .contracts import CheckResult, ExperimentBudget
from .errors import StaticPolicyError

DEFAULT_ALLOWED_IMPORTS: frozenset[str] = frozenset({"math", "statistics"})

BANNED_CALL_NAMES: frozenset[str] = frozenset(
    {
        "__import__",
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "breakpoint",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "dir",
        "memoryview",
        "type",
        "super",
        "object",
        "help",
        "exit",
        "quit",
    }
)


@dataclass(frozen=True)
class PolicyViolation:
    rule: str
    line: int
    message: str


def analyze_strategy_code(
    code: str,
    budget: ExperimentBudget,
    allowed_imports: set[str] | frozenset[str] | list[str] = DEFAULT_ALLOWED_IMPORTS,
) -> CheckResult:
    """Perform static AST verification on generated strategy source code."""
    allowed = set(allowed_imports)
    violations: list[PolicyViolation] = []

    encoded = code.encode("utf-8")
    if len(encoded) > budget.max_code_bytes:
        violations.append(
            PolicyViolation(
                rule="code_size_limit",
                line=1,
                message=f"Code size {len(encoded)} bytes exceeds limit {budget.max_code_bytes} bytes.",
            )
        )
        return _build_result(violations, node_count=0, code_bytes=len(encoded))

    try:
        tree = ast.parse(code, filename="<strategy_proposal>", mode="exec")
    except SyntaxError as exc:
        violations.append(
            PolicyViolation(
                rule="syntax_error",
                line=exc.lineno or 1,
                message=f"SyntaxError: {exc.msg}",
            )
        )
        return _build_result(violations, node_count=0, code_bytes=len(encoded))

    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > budget.max_ast_nodes:
        violations.append(
            PolicyViolation(
                rule="ast_node_limit",
                line=1,
                message=f"AST node count {node_count} exceeds limit {budget.max_ast_nodes}.",
            )
        )

    has_on_bar = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "on_bar":
            has_on_bar = True

        elif isinstance(node, ast.AsyncFunctionDef):
            violations.append(
                PolicyViolation(
                    rule="async_disallowed",
                    line=node.lineno,
                    message="Async functions are not permitted in the restricted strategy API.",
                )
            )

        elif isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split(".", 1)[0]
                if root_mod not in allowed:
                    violations.append(
                        PolicyViolation(
                            rule="disallowed_import",
                            line=node.lineno,
                            message=f"Import '{alias.name}' is not in allowlist {sorted(allowed)}.",
                        )
                    )

        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                violations.append(
                    PolicyViolation(
                        rule="relative_import_disallowed",
                        line=node.lineno,
                        message="Relative imports are prohibited.",
                    )
                )
            else:
                root_mod = (node.module or "").split(".", 1)[0]
                if root_mod not in allowed:
                    violations.append(
                        PolicyViolation(
                            rule="disallowed_import",
                            line=node.lineno,
                            message=f"Import from '{node.module}' is not in allowlist {sorted(allowed)}.",
                        )
                    )

        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr.endswith("__"):
                violations.append(
                    PolicyViolation(
                        rule="dunder_attribute_access",
                        line=node.lineno,
                        message=f"Access to dunder attribute '{node.attr}' is prohibited.",
                    )
                )

        elif isinstance(node, ast.Name):
            if node.id.startswith("__") and node.id.endswith("__"):
                violations.append(
                    PolicyViolation(
                        rule="dunder_name_access",
                        line=node.lineno,
                        message=f"Direct access to dunder name '{node.id}' is prohibited.",
                    )
                )
            elif node.id in BANNED_CALL_NAMES and isinstance(node.ctx, ast.Load):
                violations.append(
                    PolicyViolation(
                        rule="banned_builtin",
                        line=node.lineno,
                        message=f"Use of banned builtin/name '{node.id}' is prohibited.",
                    )
                )

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_CALL_NAMES:
                violations.append(
                    PolicyViolation(
                        rule="banned_call",
                        line=node.lineno,
                        message=f"Call to '{node.func.id}()' is prohibited.",
                    )
                )

    if not has_on_bar:
        violations.append(
            PolicyViolation(
                rule="missing_entrypoint",
                line=1,
                message="Strategy code must define a top-level function 'def on_bar(ctx):'.",
            )
        )

    return _build_result(violations, node_count=node_count, code_bytes=len(encoded))


def _build_result(
    violations: list[PolicyViolation],
    *,
    node_count: int,
    code_bytes: int,
) -> CheckResult:
    # Deduplicate identical (rule, line, message) entries preserving order
    seen: set[tuple[str, int, str]] = set()
    unique: list[PolicyViolation] = []
    for v in violations:
        key = (v.rule, v.line, v.message)
        if key not in seen:
            seen.add(key)
            unique.append(v)

    if unique:
        return CheckResult(
            name="static_policy",
            passed=False,
            code="STATIC_POLICY_VIOLATION",
            message=f"Static policy rejected code with {len(unique)} violation(s): {unique[0].message}",
            details={
                "code_bytes": code_bytes,
                "ast_node_count": node_count,
                "violation_count": len(unique),
                "violations": [
                    {"rule": v.rule, "line": v.line, "message": v.message} for v in unique[:20]
                ],
            },
        )

    return CheckResult(
        name="static_policy",
        passed=True,
        code="OK",
        message=f"Static policy passed ({code_bytes} bytes, {node_count} AST nodes).",
        details={"code_bytes": code_bytes, "ast_node_count": node_count},
    )


def assert_static_policy(
    code: str,
    budget: ExperimentBudget,
    allowed_imports: set[str] | frozenset[str] | list[str] = DEFAULT_ALLOWED_IMPORTS,
) -> CheckResult:
    """Analyze strategy code and raise StaticPolicyError on any violation."""
    result = analyze_strategy_code(code, budget, allowed_imports=allowed_imports)
    if not result.passed:
        raise StaticPolicyError(result.message, details=result.details)
    return result
