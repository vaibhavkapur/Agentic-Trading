"""Typed Pydantic v2 data contracts for the Financial Agent Evaluation Framework.

All external inputs, evidence records, tool contracts, agent trajectories, grading
results, human rubric scorecards, and evaluation reports conform to these schemas.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fin_eval import SCHEMA_VERSION, __version__


def ensure_utc_datetime(value: datetime) -> datetime:
    """Validate that a datetime is timezone-aware and normalize it to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware ISO-8601 UTC (e.g. 2026-02-15T16:00:00Z)")
    return value.astimezone(timezone.utc)


def canonical_json(obj: Any) -> str:
    """Serialize an object deterministically for hashing and signing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_sha256(obj: Any) -> str:
    """Compute a deterministic SHA-256 hex digest of any JSON-serializable object."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


UtcDateTime = Annotated[datetime, Field(description="Timezone-aware ISO-8601 UTC timestamp")]


class StrictModel(BaseModel):
    """Base model forbidding unexpected fields and validating defaults."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class DatasetSplit(str, Enum):
    DEV = "dev"
    HELD_OUT = "held_out"


class TaskCategory(str, Enum):
    FINANCIAL_ARITHMETIC = "financial_arithmetic"
    FILING_QA = "filing_qa"
    TOOL_WORKFLOW = "tool_workflow"
    ABSTENTION_SAFETY = "abstention_safety"
    ADVERSARIAL_RESILIENCE = "adversarial_resilience"


class NumericUnit(str, Enum):
    USD = "USD"
    USD_THOUSANDS = "USD_THOUSANDS"
    USD_MILLIONS = "USD_MILLIONS"
    USD_BILLIONS = "USD_BILLIONS"
    PERCENT = "PERCENT"
    BPS = "BPS"
    RATIO = "RATIO"
    SHARES = "SHARES"
    COUNT = "COUNT"
    DAYS = "DAYS"


class EvidenceSourceType(str, Enum):
    SEC_FILING = "sec_filing"
    MARKET_QUOTE = "market_quote"
    EARNINGS_TRANSCRIPT = "earnings_transcript"
    MACRO_RELEASE = "macro_release"
    RISK_POLICY = "risk_policy"


class FailureType(str, Enum):
    WRONG_ARITHMETIC = "WRONG_ARITHMETIC"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    FABRICATED_CITATION = "FABRICATED_CITATION"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    FABRICATED_TOOL_EXECUTION = "FABRICATED_TOOL_EXECUTION"
    UNSAFE_TOOL_REQUEST = "UNSAFE_TOOL_REQUEST"
    MISSING_REQUIRED_TOOL = "MISSING_REQUIRED_TOOL"
    TOOL_ARG_MISMATCH = "TOOL_ARG_MISMATCH"
    TOOL_CALL_COUNT_EXCEEDED = "TOOL_CALL_COUNT_EXCEEDED"
    STALE_EVIDENCE_USED = "STALE_EVIDENCE_USED"
    MISSED_ABSTENTION = "MISSED_ABSTENTION"
    UNWARRANTED_ABSTENTION = "UNWARRANTED_ABSTENTION"
    PROMPT_INJECTION_COMPROMISE = "PROMPT_INJECTION_COMPROMISE"
    TOOL_ERROR_UNHANDLED = "TOOL_ERROR_UNHANDLED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    LATENCY_EXCEEDED = "LATENCY_EXCEEDED"
    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"


class FaultType(str, Enum):
    TOOL_UNAVAILABLE = "tool_unavailable"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_MALFORMED_RESPONSE = "tool_malformed_response"
    STALE_EVIDENCE = "stale_evidence"
    PROMPT_INJECTION = "prompt_injection"
    RATE_LIMIT = "rate_limit"


class ExpectedNumeric(StrictModel):
    """Reference numeric expectation with explicit unit and error tolerances."""

    field: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_.-]+$")
    value: float
    unit: NumericUnit
    abs_tol: float = Field(default=1e-4, ge=0.0)
    rel_tol: float = Field(default=1e-3, ge=0.0)
    formula_note: str = Field(default="", description="Hand-calculated oracle derivation")


class ExpectedToolCall(StrictModel):
    """Expected tool invocation specification for deterministic tool grading."""

    tool_name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    required_args: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    min_calls: int = Field(default=1, ge=0)
    max_calls: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def _validate_bounds(self) -> ExpectedToolCall:
        if self.min_calls > self.max_calls:
            raise ValueError("min_calls must be <= max_calls")
        return self


class ExpectedCitations(StrictModel):
    """Citation requirements for a gold task."""

    required_evidence_ids: list[str] = Field(default_factory=list)
    min_supported_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    require_exact_or_token_grounding: bool = True


class GoldTask(StrictModel):
    """Canonical versioned financial evaluation task."""

    task_id: str = Field(..., pattern=r"^[A-Z0-9_-]{3,64}$")
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    split: DatasetSplit = DatasetSplit.DEV
    category: TaskCategory
    prompt: str = Field(..., min_length=10)
    as_of_utc: UtcDateTime
    max_evidence_age_seconds: int = Field(default=86400 * 120, ge=0)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(
        default_factory=lambda: [
            "execute_live_order",
            "wire_transfer",
            "export_customer_records",
            "modify_production_db",
        ]
    )
    expected_numeric: list[ExpectedNumeric] = Field(default_factory=list)
    expected_tool_calls: list[ExpectedToolCall] = Field(default_factory=list)
    expected_citations: ExpectedCitations = Field(default_factory=ExpectedCitations)
    abstention_expected: bool = False
    expected_abstention_reasons: list[str] = Field(default_factory=list)
    injection_canaries: list[str] = Field(default_factory=list)
    reference_notes: str = Field(default="")

    @field_validator("as_of_utc")
    @classmethod
    def _validate_as_of_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)

    @model_validator(mode="after")
    def _validate_tool_disjointness(self) -> GoldTask:
        overlap = set(self.allowed_tools).intersection(self.forbidden_tools)
        if overlap:
            raise ValueError(f"Tools cannot be both allowed and forbidden: {sorted(overlap)}")
        return self


class GoldTaskDataset(StrictModel):
    """Versioned collection of gold tasks."""

    schema_version: str = Field(default=SCHEMA_VERSION)
    dataset_id: str = Field(..., pattern=r"^[a-z0-9_-]{3,64}$")
    dataset_version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    split: DatasetSplit
    description: str = Field(default="")
    provenance: str = Field(
        default="Synthetic educational financial fixtures; no real customer records or proprietary data."
    )
    tasks: list[GoldTask] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_unique_ids_and_split(self) -> GoldTaskDataset:
        seen: set[str] = set()
        for task in self.tasks:
            if task.task_id in seen:
                raise ValueError(f"Duplicate task_id in dataset: {task.task_id}")
            seen.add(task.task_id)
            if task.split != self.split:
                raise ValueError(
                    f"Task {task.task_id} has split '{task.split.value}', expected dataset split '{self.split.value}'"
                )
        return self


class EvidenceRecord(StrictModel):
    """Typed evidence record retrieved from mock tools.

    Security invariant: `content` is always treated as UNTRUSTED DATA even when
    sourced from a mock filing or transcript.
    """

    evidence_id: str = Field(..., pattern=r"^EVD-[A-Z0-9_-]{3,64}$")
    source_type: EvidenceSourceType
    ticker: str = Field(..., pattern=r"^[A-Z0-9._-]{1,16}$")
    title: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    published_at_utc: UtcDateTime
    as_of_utc: UtcDateTime
    unit_metadata: dict[str, NumericUnit] = Field(default_factory=dict)
    numeric_facts: dict[str, float] = Field(default_factory=dict)
    is_untrusted_text: Literal[True] = True

    @field_validator("published_at_utc", "as_of_utc")
    @classmethod
    def _validate_timestamps(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


class MockFixtureStore(StrictModel):
    """Versioned offline dataset backing all mock financial tools."""

    schema_version: str = Field(default=SCHEMA_VERSION)
    fixture_version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    provenance: str
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    filing_metrics: dict[str, dict[str, dict[str, dict[str, Any]]]] = Field(
        default_factory=dict,
        description="ticker -> period -> metric -> {value, unit, evidence_id}",
    )
    market_quotes: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="ticker -> {price, currency, as_of_utc, volume, evidence_id}",
    )
    macro_indicators: dict[str, dict[str, dict[str, Any]]] = Field(
        default_factory=dict,
        description="series_id -> period -> {value, unit, as_of_utc, evidence_id}",
    )


class ToolContract(StrictModel):
    """Declarative typed contract for a mock tool."""

    tool_name: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    required_params: list[str] = Field(default_factory=list)
    optional_params: list[str] = Field(default_factory=list)
    is_mutating: bool = False
    is_forbidden_by_policy: bool = False
    cost_usd_per_call: float = Field(default=0.0, ge=0.0)
    simulated_latency_ms: float = Field(default=15.0, ge=0.0)


class ToolExecutionReceipt(StrictModel):
    """Runtime-signed receipt proving a tool call actually occurred in the mock runtime."""

    receipt_id: str
    run_id: str
    task_id: str
    tool_call_id: str
    tool_name: str
    args_hash: str
    output_hash: str
    status: Literal["ok", "error", "blocked_policy"]
    executed_at_utc: UtcDateTime
    latency_ms: float = Field(..., ge=0.0)
    signature: str = Field(..., min_length=16)

    @field_validator("executed_at_utc")
    @classmethod
    def _validate_executed_at(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


class ToolCallRecord(StrictModel):
    """Record of a tool invocation reported in an agent trajectory."""

    tool_call_id: str = Field(..., min_length=1)
    tool_name: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "error", "blocked_policy"]
    output: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    latency_ms: float = Field(default=0.0, ge=0.0)
    receipt_signature: str | None = None


class NumericClaim(StrictModel):
    """Structured numeric claim produced by an agent."""

    field: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_.-]+$")
    value: float
    unit: NumericUnit


class CitationClaim(StrictModel):
    """Structured citation tying an agent claim to an evidence record and quoted span."""

    claim_text: str = Field(..., min_length=1)
    evidence_id: str = Field(..., min_length=1)
    quoted_span: str = Field(..., min_length=1)


class TokenUsage(StrictModel):
    """Token counts for cost accounting."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class AgentTrajectory(StrictModel):
    """Complete structured output and execution trace of an agent on one task."""

    schema_version: str = Field(default=SCHEMA_VERSION)
    run_id: str = Field(..., min_length=3)
    task_id: str = Field(..., pattern=r"^[A-Z0-9_-]{3,64}$")
    agent_id: str = Field(..., min_length=1)
    seed: int
    final_answer: str = Field(default="")
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    citations: list[CitationClaim] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    abstained: bool = False
    abstention_reason: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: float = Field(default=0.0, ge=0.0)
    cost_usd: float = Field(default=0.0, ge=0.0)


class ModelConfig(StrictModel):
    """Versioned model/agent runtime configuration with fixed safety budgets."""

    schema_version: str = Field(default=SCHEMA_VERSION)
    config_id: str = Field(..., pattern=r"^[a-z0-9_-]{3,64}$")
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    provider: Literal[
        "mock_deterministic",
        "mock_stochastic",
        "mock_faulty",
        "openai_compatible",
    ] = "mock_deterministic"
    model_name: str = Field(..., min_length=1)
    seed: int = Field(default=42, ge=0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=64, le=16384)
    budget_usd: float = Field(default=0.50, gt=0.0)
    max_tool_calls: int = Field(default=10, ge=1, le=50)
    max_latency_ms: float = Field(default=30000.0, gt=0.0)
    input_cost_per_1k_tokens: float = Field(default=0.001, ge=0.0)
    output_cost_per_1k_tokens: float = Field(default=0.002, ge=0.0)
    live_execution_enabled: Literal[False] = False
    external_network_allowed: bool = False
    agent_options: dict[str, Any] = Field(default_factory=dict)


class FaultRule(StrictModel):
    """Single deterministic or seeded failure injection rule."""

    fault_id: str = Field(..., pattern=r"^[A-Z0-9_-]{3,64}$")
    fault_type: FaultType
    target_task_ids: list[str] = Field(default_factory=list, description="Empty means all tasks")
    target_tool: str | None = None
    target_evidence_id: str | None = None
    stale_age_seconds: int | None = Field(default=None, ge=1)
    timeout_ms: float | None = Field(default=None, ge=1.0)
    injection_payload: str | None = None
    probability: float = Field(default=1.0, ge=0.0, le=1.0)


class FailureInjectionProfile(StrictModel):
    """Versioned failure injection suite configuration."""

    schema_version: str = Field(default=SCHEMA_VERSION)
    profile_id: str = Field(..., pattern=r"^[a-z0-9_-]{3,64}$")
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(default="")
    rules: list[FaultRule] = Field(default_factory=list)


class CheckResult(StrictModel):
    """Result from a single deterministic grader check."""

    check_name: str
    passed: bool
    score: float = Field(..., ge=0.0, le=1.0)
    failure_types: list[FailureType] = Field(default_factory=list)
    details: str = Field(default="")
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class TaskEvaluationResult(StrictModel):
    """Full evaluation outcome for a single task execution."""

    task_id: str
    task_version: str
    split: DatasetSplit
    category: TaskCategory
    run_id: str
    seed: int
    overall_score: float = Field(..., ge=0.0, le=1.0)
    passed: bool
    check_results: list[CheckResult]
    failure_types: list[FailureType] = Field(default_factory=list)
    receipt_verified: bool
    cost_usd: float = Field(..., ge=0.0)
    latency_ms: float = Field(..., ge=0.0)
    token_usage: TokenUsage
    faults_triggered: list[str] = Field(default_factory=list)
    human_rubric_template_id: str = Field(default="fin-eval-rubric-v1")


class ConfidenceInterval(StrictModel):
    """Statistical confidence interval for a reported metric."""

    mean: float
    lower: float
    upper: float
    confidence_level: float = Field(default=0.95, gt=0.0, lt=1.0)
    method: Literal["wilson", "t_interval", "bootstrap", "exact_single"]
    n_samples: int = Field(..., ge=1)
    std_dev: float = Field(default=0.0, ge=0.0)


class MetricSummary(StrictModel):
    """Aggregated evaluation metrics with confidence intervals, cost, and latency."""

    num_tasks: int = Field(..., ge=1)
    num_runs: int = Field(..., ge=1)
    total_evaluations: int = Field(..., ge=1)
    pass_rate: ConfidenceInterval
    mean_score: ConfidenceInterval
    numeric_accuracy: float = Field(..., ge=0.0, le=1.0)
    citation_faithfulness: float = Field(..., ge=0.0, le=1.0)
    tool_reliability: float = Field(..., ge=0.0, le=1.0)
    abstention_accuracy: float = Field(..., ge=0.0, le=1.0)
    receipt_verification_rate: float = Field(..., ge=0.0, le=1.0)
    total_cost_usd: float = Field(..., ge=0.0)
    mean_cost_per_task_usd: float = Field(..., ge=0.0)
    mean_latency_ms: float = Field(..., ge=0.0)
    p95_latency_ms: float = Field(..., ge=0.0)
    total_tokens: int = Field(..., ge=0)
    failure_type_counts: dict[str, int] = Field(default_factory=dict)


class BaselineComparison(StrictModel):
    """Comparison of an evaluation run against a saved reference baseline."""

    baseline_report_id: str
    pass_rate_delta: float
    mean_score_delta: float
    tolerance: float = Field(..., ge=0.0)
    within_tolerance: bool
    regressions: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    notes: str = Field(default="")


class RuntimeEnvironment(StrictModel):
    """Captured runtime metadata for reproducibility."""

    python_version: str
    platform: str
    framework_version: str = Field(default=__version__)
    schema_version: str = Field(default=SCHEMA_VERSION)
    installed_packages: dict[str, str] = Field(default_factory=dict)


class EvaluationReport(StrictModel):
    """Versioned machine-readable evaluation report."""

    report_id: str = Field(..., min_length=8)
    schema_version: str = Field(default=SCHEMA_VERSION)
    framework_version: str = Field(default=__version__)
    created_at_utc: UtcDateTime
    dataset_id: str
    dataset_version: str
    dataset_split: DatasetSplit
    fixture_version: str
    config_id: str
    config_version: str
    failure_injection_profile_id: str
    seeds: list[int] = Field(..., min_length=1)
    runtime_environment: RuntimeEnvironment
    model_config_snapshot: ModelConfig
    summary: MetricSummary
    task_results: list[TaskEvaluationResult]
    diagnostic_counters: dict[str, int] = Field(default_factory=dict)
    baseline_comparison: BaselineComparison | None = None

    @field_validator("created_at_utc")
    @classmethod
    def _validate_created_at(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


class RubricDimensionScore(StrictModel):
    """Single dimension score in a human evaluation rubric (1-5 anchored scale)."""

    dimension: Literal[
        "financial_accuracy",
        "citation_faithfulness",
        "tool_discipline",
        "risk_and_abstention",
        "clarity_and_auditability",
    ]
    score: int = Field(..., ge=1, le=5)
    rationale: str = Field(..., min_length=5)


class HumanRubricScorecard(StrictModel):
    """Structured human reviewer scorecard paired with deterministic evaluation."""

    rubric_version: str = Field(default="1.0.0")
    task_id: str
    run_id: str
    reviewer_id: str = Field(..., min_length=2)
    reviewed_at_utc: UtcDateTime
    dimensions: list[RubricDimensionScore] = Field(..., min_length=5, max_length=5)
    overall_recommendation: Literal["approve", "revise", "reject"]
    notes: str = Field(default="")

    @field_validator("reviewed_at_utc")
    @classmethod
    def _validate_reviewed_at(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)

    @model_validator(mode="after")
    def _validate_unique_dimensions(self) -> HumanRubricScorecard:
        dims = [d.dimension for d in self.dimensions]
        if len(set(dims)) != 5:
            raise ValueError("HumanRubricScorecard must contain all 5 unique rubric dimensions")
        return self


class LLMJudgeAssessment(StrictModel):
    """Optional advisory LLM-as-judge record that can NEVER override deterministic fails."""

    judge_model: str
    task_id: str
    run_id: str
    advisory_score: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    can_override_deterministic_fail: Literal[False] = False
