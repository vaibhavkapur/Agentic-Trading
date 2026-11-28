"""Macro Intelligence Agent — revision-aware macro release and central bank analysis.

Offline research and educational prototype. Macro interpretations are framed as
hypotheses with verifiable citations, not trading predictions or live signals.
"""

from .config import AgentConfig, BriefPolicyConfig, ModelAdapterConfig, StorageConfig, load_config
from .errors import (
    BudgetExceededError,
    CitationVerificationError,
    ConfigurationError,
    ConflictingReportsError,
    EmbargoViolationError,
    MacroAgentError,
    SchemaValidationError,
    UnitMismatchError,
    UnsupportedInputError,
    UntrustedInstructionError,
)
from .models import (
    AbstentionRecord,
    AgentRunResult,
    Citation,
    ConflictRecord,
    ConsensusEstimate,
    DocumentType,
    ExtractedFigure,
    MacroRelease,
    MetricObservation,
    PolicyLanguageSignal,
    PolicyStance,
    RevisionDiff,
    RunDiagnostics,
    RunMetadata,
    ScenarioBrief,
    ScenarioHypothesis,
    SurpriseCalculation,
    Unit,
    UntrustedInstructionFinding,
)
from .service import MacroIntelligenceService

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "AgentConfig",
    "BriefPolicyConfig",
    "ModelAdapterConfig",
    "StorageConfig",
    "load_config",
    "MacroAgentError",
    "ConfigurationError",
    "SchemaValidationError",
    "EmbargoViolationError",
    "UnitMismatchError",
    "ConflictingReportsError",
    "UntrustedInstructionError",
    "CitationVerificationError",
    "UnsupportedInputError",
    "BudgetExceededError",
    "Unit",
    "DocumentType",
    "PolicyStance",
    "Citation",
    "MetricObservation",
    "ConsensusEstimate",
    "MacroRelease",
    "ExtractedFigure",
    "SurpriseCalculation",
    "PolicyLanguageSignal",
    "RevisionDiff",
    "ConflictRecord",
    "AbstentionRecord",
    "UntrustedInstructionFinding",
    "ScenarioHypothesis",
    "ScenarioBrief",
    "RunDiagnostics",
    "RunMetadata",
    "AgentRunResult",
    "MacroIntelligenceService",
]
