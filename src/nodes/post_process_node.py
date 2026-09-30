"""AgentCore Platform v1.0 — OutputFormat (post_process) for CMN-C1-704."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from shared.services.events import emitter
from shared.services.events.types import EventType
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.slack_workflow_trigger_service import hash_value, scan_credentials


class PostProcessNode(FunctionNode):
    """OutputFormat — build the trigger receipt; S-3 output gate scans for
    credentials and echoes personal-data field values only as confirmation hashes.
    """

    # S-1 trust gate: output formatting on behalf of internal callers.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # Progress (non-terminal) event for the caller. Outside the Marketplace runtime
        # this resolves to a no-op emitter, so it is safe on every entry path.
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Preparing the result...",
            metadata={"step": "post_process"},
        )
        workflow_id = state.get("resolved_workflow_id")
        input_fields = state.get("input_fields", {})
        receipt = {
            "workflow_id": workflow_id,
            "field_names": sorted(input_fields.keys()),
            "field_confirmations": {k: hash_value(str(v)) for k, v in input_fields.items()},
            "execution_ref": state.get("execution_ref"),
        }
        emit_trace_event(
            "trigger_receipt_formatted",
            {"correlation_id": state.get("correlation_id"), "workflow_id": workflow_id},
            state,
        )
        return {"formatted_output": receipt, "status": AgentStatus.SUCCESS.value}

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-3 domain gate: if any credential pattern leaked into the formatted
        output, drop the field and return an audit-only receipt. Runs automatically
        after execute(); always returns a dict, never raises.
        """
        formatted = state.get("formatted_output")
        if isinstance(formatted, dict):
            blob = " ".join(str(v) for v in formatted.values())
            if scan_credentials(blob):
                emit_trace_event(
                    "output_credential_scrubbed",
                    {"correlation_id": state.get("correlation_id")},
                    state,
                )
                return {
                    "formatted_output": {
                        "workflow_id": formatted.get("workflow_id"),
                        "execution_ref": formatted.get("execution_ref"),
                        "note": "output redacted by S-3 credential gate",
                    },
                    "status": state.get("status"),
                }
        return state
