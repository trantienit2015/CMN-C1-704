"""AgentCore Platform v1.0 — graph for CMN-C1-704 (Cat 1, flat backbone).

SlackWorkflowTriggerAgent — a single technical capability (trigger a configured
Slack Workflow Builder workflow). Flat 3-slot AgentBaseGraph backbone; no GraphNode.
"""

from framework.graph.agent_base_graph import AgentBaseGraph

from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State


class Graph(AgentBaseGraph):
    """CMN-C1-704 SlackWorkflowTriggerAgent."""

    @property
    def name(self) -> str:
        return "cmn-c1-704"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize
        registry = self.config.get("workflow_registry", {}) if hasattr(self, "config") else {}
        llm = self.config.get("llm") if hasattr(self, "config") else None
        trigger_client = self.config.get("trigger_client") if hasattr(self, "config") else None
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = MainNode(registry=registry, llm=llm, trigger_client=trigger_client)
        self._nodes["post_process"] = PostProcessNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.
