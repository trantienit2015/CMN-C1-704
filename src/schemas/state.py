"""AgentCore Platform v1.0 — State schema for CMN-C1-704."""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects
# cause silent corruption. Extend AgentState with agent-specific fields only.
# Do NOT add credentials, secrets, or Pydantic models.

from typing import Any, NotRequired

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """SlackWorkflowTrigger agent state.

    Shared fields (user_input, validated_input, status, session_id, node_history,
    error_log, etc.) are inherited from AgentState. Every agent-specific field is
    NotRequired (state-safety).
    """

    # resolved trigger intent
    resolved_workflow_id: NotRequired[str]
    input_fields: NotRequired[dict[str, Any]]
    candidates: NotRequired[list[str]]
    confidence_flags: NotRequired[list[str]]

    # trigger result
    execution_ref: NotRequired[str]
    trigger_receipt: NotRequired[dict[str, Any]]
