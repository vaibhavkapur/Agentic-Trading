"""Research DAG, budget scheduler, causal backtester, and idempotent workers."""

from __future__ import annotations

from rarp.scheduler.backtester import (
    BacktesterAdapter,
    BacktestResult,
    ReferenceBacktester,
    SplitMetrics,
    TS14BacktesterAdapter,
)
from rarp.scheduler.budget import BudgetSnapshot, BudgetTracker, StopDecision
from rarp.scheduler.dag import DAGEdge, DAGNode, NodeType, ResearchDAG
from rarp.scheduler.worker import ExperimentWorker, WorkerExecutionResult

__all__ = [
    "BacktestResult",
    "BacktesterAdapter",
    "BudgetSnapshot",
    "BudgetTracker",
    "DAGEdge",
    "DAGNode",
    "ExperimentWorker",
    "NodeType",
    "ReferenceBacktester",
    "ResearchDAG",
    "SplitMetrics",
    "StopDecision",
    "TS14BacktesterAdapter",
    "WorkerExecutionResult",
]
