"""Integration test for CMN-C1-704 — full graph compile + invoke (Cat 1)."""

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph


REGISTRY = {
    "incident_page": {
        "keywords": ["incident", "page oncall"],
        "input_schema": {"severity": {"type": "string", "required": True}},
    },
}


class FakeLLM:
    def complete(self, prompt):
        # BaseLLM.complete() MUST return the canonical envelope, never a bare string.
        return {
            "content": '{"workflow_id": "incident_page", "input_fields": {"severity": "SEV1"}}',
            "tool_calls": [],
            "model": "fake-model",
        }


def _agent(**cfg):
    agent = Graph(config={"max_retry": 1, **cfg})
    agent.compile()
    return agent


def test_full_graph_success():
    agent = _agent(workflow_registry=REGISTRY, llm=FakeLLM())
    ctx = InvocationContext(session_id="it-1", caller_trust_level=TrustLevel.INTERNAL, caller_id="ops")
    result = agent.invoke("page oncall for an incident", ctx=ctx)
    assert result.get("status") in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
    nh = result.get("node_history") or []
    assert len(nh) >= 5, f"expected >=5 node_history entries, got {nh}"


def test_full_graph_insufficient_trust_refused():
    agent = _agent(workflow_registry=REGISTRY, llm=FakeLLM())
    ctx = InvocationContext(session_id="it-2", caller_trust_level=TrustLevel.ANONYMOUS, caller_id="x")
    result = agent.invoke("page oncall for an incident", ctx=ctx)
    # INTERNAL-required nodes must refuse an ANONYMOUS caller
    assert result.get("status") in (AgentStatus.ERROR, AgentStatus.ERROR.value,
                                    AgentStatus.CANCELLED, AgentStatus.CANCELLED.value)
