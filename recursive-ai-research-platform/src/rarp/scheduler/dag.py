"""Typed Research DAG with cycle detection, topological ordering, and state tracking."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from rarp.domain.errors import RARPValidationError
from rarp.domain.types import RunStatus, utc_now_iso


class NodeType(str, Enum):
    PROPOSE = "PROPOSE"
    VALIDATE_DATA = "VALIDATE_DATA"
    EXECUTE_EXPERIMENT = "EXECUTE_EXPERIMENT"
    CRITIQUE = "CRITIQUE"
    REFINE = "REFINE"
    REVIEW_GATE = "REVIEW_GATE"


@dataclass
class DAGNode:
    node_id: str
    node_type: NodeType
    label: str
    status: RunStatus = RunStatus.PENDING
    hypothesis_id: Optional[str] = None
    run_id: Optional[str] = None
    attempt_count: int = 0
    created_at_utc: str = field(default_factory=utc_now_iso)
    updated_at_utc: str = field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["node_type"] = self.node_type.value
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class DAGEdge:
    source_id: str
    target_id: str
    relation: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


class ResearchDAG:
    """Directed acyclic graph tracking research lineage across iterations."""

    def __init__(self, dag_id: str) -> None:
        self.dag_id = dag_id
        self.nodes: Dict[str, DAGNode] = {}
        self.edges: List[DAGEdge] = []

    def add_node(self, node: DAGNode) -> DAGNode:
        if node.node_id in self.nodes:
            raise RARPValidationError(f"Duplicate DAG node_id: {node.node_id}")
        self.nodes[node.node_id] = node
        return node

    def add_edge(self, source_id: str, target_id: str, relation: str = "depends_on") -> DAGEdge:
        if source_id not in self.nodes or target_id not in self.nodes:
            raise RARPValidationError(
                f"Edge endpoints must exist in DAG: {source_id} -> {target_id}"
            )
        if source_id == target_id:
            raise RARPValidationError(f"Self-loop prohibited in DAG: {source_id}")
        edge = DAGEdge(source_id=source_id, target_id=target_id, relation=relation)
        self.edges.append(edge)
        # Validate acyclicity immediately.
        try:
            self.topological_order()
        except RARPValidationError:
            self.edges.pop()
            raise
        return edge

    def transition(
        self,
        node_id: str,
        status: RunStatus,
        run_id: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> DAGNode:
        node = self.nodes[node_id]
        node.status = status
        node.updated_at_utc = utc_now_iso()
        if status in (RunStatus.RUNNING, RunStatus.RETRYING):
            node.attempt_count += 1
        if run_id is not None:
            node.run_id = run_id
        if metadata_update:
            node.metadata.update(metadata_update)
        return node

    def topological_order(self) -> List[str]:
        in_degree: Dict[str, int] = {nid: 0 for nid in self.nodes}
        adjacency: Dict[str, List[str]] = {nid: [] for nid in self.nodes}
        for edge in self.edges:
            adjacency[edge.source_id].append(edge.target_id)
            in_degree[edge.target_id] += 1

        queue: deque[str] = deque(sorted(nid for nid, deg in in_degree.items() if deg == 0))
        order: List[str] = []
        while queue:
            current = queue.popleft()
            order.append(current)
            for nxt in sorted(adjacency[current]):
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        if len(order) != len(self.nodes):
            raise RARPValidationError("Cycle detected in ResearchDAG")
        return order

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dag_id": self.dag_id,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "topological_order": self.topological_order(),
            "nodes": [self.nodes[nid].to_dict() for nid in self.topological_order()],
            "edges": [e.to_dict() for e in self.edges],
        }
