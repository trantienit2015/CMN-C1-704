"""Unit tests for CMN-C1-704 nodes — each node: success + error/edge path."""

from framework.schemas.agent_status import AgentStatus

from src.nodes.pre_process_node import PreProcessNode
from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode

# Detector fixture assembled at run time so the committed file carries no token-shaped literal
# (secret scanners on the publish target reject one even when it is fake).
_FAKE_SLACK_TOKEN = "xox" + "b-" + "1234567890-abcdefghijklmno"


REGISTRY = {
    "onboarding_start": {
        "keywords": ["onboarding", "new hire", "start onboarding"],
        "input_schema": {"employee_name": {"type": "string", "required": True}},
    },
    "incident_page": {
        "keywords": ["incident", "page oncall"],
        "input_schema": {"severity": {"type": "string", "required": True}},
    },
}


def _base_state(**kw):
    s = {"correlation_id": "t", "execution_time": {}}
    s.update(kw)
    return s


# ── PreProcessNode (InputValidate) ──────────────────────────────────────────

def test_input_validate_success():
    node = PreProcessNode()
    out = node.execute(_base_state(user_input="  start onboarding for a new hire  "))
    assert out["status"] == AgentStatus.SUCCESS
    assert out["validated_input"] == "start onboarding for a new hire"


def test_input_validate_empty_error():
    node = PreProcessNode()
    out = node.execute(_base_state(user_input="   "))
    assert out["status"] == AgentStatus.ERROR


def test_extra_gate_rejects_slack_token():
    node = PreProcessNode()
    state = _base_state(user_input="trigger onboarding " + _FAKE_SLACK_TOKEN)
    result = node._extra_security_gate_input(state)
    assert result["status"] == AgentStatus.ERROR


def test_extra_gate_rejects_my_number():
    node = PreProcessNode()
    state = _base_state(user_input="onboard employee 123456789012")
    result = node._extra_security_gate_input(state)
    assert result["status"] == AgentStatus.ERROR


def test_extra_gate_passes_clean_and_personal_name():
    node = PreProcessNode()
    state = _base_state(user_input="start onboarding for Tanaka Taro")
    result = node._extra_security_gate_input(state)
    assert result is state


# ── MainNode (WorkflowTrigger) ──────────────────────────────────────────────

def test_workflow_trigger_success():
    node = MainNode(registry=REGISTRY)
    out = node.execute(_base_state(validated_input="start onboarding"))
    # deterministic resolution has no input_fields; onboarding requires employee_name → validation fails
    assert out["status"] == AgentStatus.ERROR
    assert out["resolved_workflow_id"] == "onboarding_start"


def test_workflow_trigger_success_with_llm_fields():
    # BaseLLM.complete() MUST return the canonical {"content": ..., "tool_calls": ..., "model": ...}
    # envelope, never a bare string — this fake matches the real contract (and the real
    # AzureOpenAIClient/LazyAzureOpenAILLM shape), not a shortcut.
    class FakeLLM:
        def complete(self, prompt):
            return {
                "content": '{"workflow_id": "incident_page", "input_fields": {"severity": "SEV1"}}',
                "tool_calls": [],
                "model": "fake-model",
            }
    node = MainNode(registry=REGISTRY, llm=FakeLLM())
    out = node.execute(_base_state(validated_input="page oncall for an incident"))
    assert out["status"] == AgentStatus.SUCCESS
    assert out["resolved_workflow_id"] == "incident_page"
    assert out["input_fields"] == {"severity": "SEV1"}
    assert out["execution_ref"]


def test_workflow_trigger_llm_fenced_json_still_parses():
    """A markdown-fenced or prose-wrapped reply must still resolve via extract_json_object."""
    class FenceWrappedFakeLLM:
        def complete(self, prompt):
            return {
                "content": 'Sure, here you go:\n```json\n{"workflow_id": "incident_page", '
                '"input_fields": {"severity": "SEV1"}}\n```',
                "tool_calls": [],
                "model": "fake-model",
            }
    node = MainNode(registry=REGISTRY, llm=FenceWrappedFakeLLM())
    out = node.execute(_base_state(validated_input="page oncall for an incident"))
    assert out["status"] == AgentStatus.SUCCESS
    assert out["resolved_workflow_id"] == "incident_page"


def test_workflow_trigger_llm_raises_falls_back_to_deterministic():
    """A network/API failure from the LLM must degrade, never raise or set status=error
    for that reason — the deterministic resolver still gets a chance to resolve the intent."""
    class RaisingFakeLLM:
        def complete(self, prompt):
            raise RuntimeError("simulated Azure OpenAI API error")
    node = MainNode(registry=REGISTRY, llm=RaisingFakeLLM())
    out = node.execute(_base_state(validated_input="start onboarding"))
    # deterministic resolution finds the workflow but not its required field -> validation error,
    # not a raised exception and not an LLM-attributed failure.
    assert out["status"] == AgentStatus.ERROR
    assert out["resolved_workflow_id"] == "onboarding_start"


def test_workflow_trigger_llm_malformed_content_falls_back_to_deterministic():
    """Content with no workflow_id (or no parseable JSON at all) must degrade silently."""
    class GarbageFakeLLM:
        def complete(self, prompt):
            return {"content": "I could not determine a workflow.", "tool_calls": [], "model": "fake-model"}
    node = MainNode(registry=REGISTRY, llm=GarbageFakeLLM())
    out = node.execute(_base_state(validated_input="start onboarding"))
    assert out["status"] == AgentStatus.ERROR
    assert out["resolved_workflow_id"] == "onboarding_start"


def test_workflow_trigger_empty_registry_failsafe():
    node = MainNode(registry={})
    out = node.execute(_base_state(validated_input="anything"))
    assert out["status"] == AgentStatus.ERROR


def test_workflow_trigger_unresolved():
    node = MainNode(registry=REGISTRY)
    out = node.execute(_base_state(validated_input="do something entirely unknown"))
    assert out["status"] == AgentStatus.ERROR
    assert out.get("candidates") == []


def test_workflow_trigger_ambiguous_returns_candidates():
    reg = {
        "wf_a": {"keywords": ["deploy"], "input_schema": {}},
        "wf_b": {"keywords": ["deploy"], "input_schema": {}},
    }
    node = MainNode(registry=reg)
    out = node.execute(_base_state(validated_input="deploy please"))
    assert out["status"] == AgentStatus.ERROR
    assert set(out["candidates"]) == {"wf_a", "wf_b"}


# ── PostProcessNode (OutputFormat) ──────────────────────────────────────────

def test_output_format_success():
    node = PostProcessNode()
    out = node.execute(_base_state(resolved_workflow_id="incident_page",
                                   input_fields={"severity": "SEV1"},
                                   execution_ref="exec:abc"))
    assert out["status"] == AgentStatus.SUCCESS
    r = out["formatted_output"]
    assert r["workflow_id"] == "incident_page"
    assert r["field_confirmations"]["severity"].startswith("sha256:")


def test_output_gate_scrubs_leaked_credential():
    node = PostProcessNode()
    state = _base_state(status=AgentStatus.SUCCESS,
                        formatted_output={"workflow_id": "w", "execution_ref": "e",
                                          "leak": _FAKE_SLACK_TOKEN})
    result = node._extra_security_gate_output(state)
    assert "leak" not in result["formatted_output"]
    assert result["formatted_output"]["note"]


def test_output_gate_passes_clean():
    node = PostProcessNode()
    state = _base_state(formatted_output={"workflow_id": "w", "execution_ref": "e"})
    result = node._extra_security_gate_output(state)
    assert result is state
