"""AgentCore Platform v1.0 — InputValidate (pre_process) for CMN-C1-704."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from shared.services.events import emitter
from shared.services.events.types import EventType
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.slack_workflow_trigger_service import scan_credentials


class PreProcessNode(FunctionNode):
    """InputValidate — S-1 trust gate + S-2 domain input scan.

    Automation-triggering agent: callers are internal systems/operators, so the
    node requires INTERNAL trust. The framework @final _security_gate_input() runs
    the generic PII scan; the domain scan (Slack tokens / Bearer / JWT / 個人番号)
    is added via _extra_security_gate_input(), which returns an ERROR-override dict
    on violation and never raises.
    """

    # S-1 trust gate: triggers workflows on behalf of internal callers.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # Progress (non-terminal) event for the caller. Outside the Marketplace runtime
        # this resolves to a no-op emitter, so it is safe on every entry path.
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Checking the request...",
            metadata={"step": "pre_process"},
        )
        user_input = state.get("user_input", "")
        if not user_input or not user_input.strip():
            emit_trace_event(
                "input_rejected",
                {"correlation_id": state.get("correlation_id"), "reason": "empty"},
                state,
            )
            return {"status": AgentStatus.ERROR.value, "error_log": ["InputValidate: empty trigger request"]}

        emit_trace_event(
            "trigger_request_received",
            {"correlation_id": state.get("correlation_id")},
            state,
        )
        return {
            "validated_input": user_input.strip(),
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-2 domain scan: embedded credentials / My-Number are auto-rejected.
        Runs automatically before execute(); always returns a dict, never raises.
        Personal names (the legitimate onboarding payload) are NOT rejected here.
        """
        text = state.get("user_input", "") or ""
        hits = scan_credentials(text)
        if hits:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"S-2: forbidden pattern in trigger request: {sorted(set(hits))}"],
            }
        return state
