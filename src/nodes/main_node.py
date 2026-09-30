"""AgentCore Platform v1.0 — WorkflowTrigger (main) for CMN-C1-704."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from shared.services.events import emitter
from shared.services.events.types import EventType
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from shared.utils.llm_json import extract_json_object

from src.services.slack_workflow_trigger_service import (
    hash_value,
    resolve_workflow,
    trigger_workflow,
    validate_input_fields,
)


class MainNode(FunctionNode):
    """WorkflowTrigger — resolve workflow id + fields, hard-validate against the
    registry/schema, and dispatch the trigger with an idempotency guard.

    Resolution: an injected LLM (``llm.complete`` returning JSON) is used when
    available; otherwise a deterministic keyword resolution over the registry.
    Validation is always deterministic (no LLM override). S-4 audit is emitted
    inline for the trigger side effect.
    """

    # S-1 trust gate: triggers an automation workflow — privileged operation.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def __init__(
        self, registry: dict[str, Any] | None = None, llm: Any | None = None, trigger_client: Any | None = None
    ) -> None:
        self._registry = registry or {}
        self._llm = llm
        self._trigger_client = trigger_client

    def _resolve(self, intent: str) -> dict[str, Any]:
        if self._llm is not None and hasattr(self._llm, "complete"):
            try:
                # BaseLLM.complete() MUST return the canonical envelope
                # {"content": str, "tool_calls": [...], "model": str, ...} — never a bare
                # string. The actual JSON answer is nested in "content"; extract_json_object
                # tolerates prose/markdown-fence wrapping and never raises on malformed input.
                response = self._llm.complete(
                    [
                        {
                            "role": "user",
                            "content": f"Resolve the trigger intent to a workflow_id and input_fields. "
                            f"Registry keys: {list(self._registry)}. Intent: {intent}. Return JSON.",
                        }
                    ]
                )
                content = response.get("content") if isinstance(response, dict) else None
                parsed = extract_json_object(content)
                if parsed.get("workflow_id"):
                    return {
                        "workflow_id": parsed.get("workflow_id"),
                        "input_fields": parsed.get("input_fields", {}),
                        "candidates": parsed.get("candidates", []),
                    }
            except Exception:
                pass  # any LLM/API/network failure degrades to deterministic resolution
        res = resolve_workflow(intent, self._registry)
        return {"workflow_id": res.get("workflow_id"), "input_fields": {}, "candidates": res.get("candidates", [])}

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # Progress (non-terminal) event for the caller. Outside the Marketplace runtime
        # this resolves to a no-op emitter, so it is safe on every entry path.
        emitter().emit_event(
            event_type=EventType.PROGRESS_UPDATE,
            message="Working on the request...",
            metadata={"step": "main"},
        )
        if not self._registry:
            emit_trace_event(
                "trigger_config_error",
                {"correlation_id": state.get("correlation_id"), "reason": "registry_empty"},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["WorkflowTrigger: workflow registry is unset/empty (fail-safe)"],
            }

        intent = state.get("validated_input", state.get("user_input", ""))
        resolved = self._resolve(intent)
        workflow_id = resolved["workflow_id"]
        input_fields = resolved.get("input_fields", {})

        if not workflow_id:
            emit_trace_event(
                "trigger_unresolved",
                {"correlation_id": state.get("correlation_id"), "n_candidates": len(resolved.get("candidates", []))},
                state,
            )
            return {
                "candidates": resolved.get("candidates", []),
                "status": AgentStatus.ERROR.value,
                "error_log": ["WorkflowTrigger: could not resolve to a single registered workflow"],
            }

        validation = validate_input_fields(workflow_id, input_fields, self._registry)
        if not validation["ok"]:
            emit_trace_event(
                "trigger_validation_failed",
                {
                    "correlation_id": state.get("correlation_id"),
                    "missing": validation["missing"],
                    "invalid": validation["invalid"],
                },
                state,
            )
            return {
                "resolved_workflow_id": workflow_id,
                "input_fields": input_fields,
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    f"WorkflowTrigger: input-field validation failed "
                    f"(missing={validation['missing']}, invalid={validation['invalid']})"
                ],
            }

        request_id = state.get("correlation_id") or state.get("session_id") or "req"
        receipt = trigger_workflow(workflow_id, input_fields, request_id, client=self._trigger_client)

        # S-4: audit with field NAMES + hashed values for personal-data confirmation.
        emit_trace_event(
            "workflow_triggered",
            {
                "correlation_id": state.get("correlation_id"),
                "workflow_id": workflow_id,
                "field_names": sorted(input_fields.keys()),
                "field_hashes": {k: hash_value(str(v)) for k, v in input_fields.items()},
                "execution_ref": receipt.get("execution_ref"),
            },
            state,
        )
        return {
            "resolved_workflow_id": workflow_id,
            "input_fields": input_fields,
            "execution_ref": receipt.get("execution_ref"),
            "trigger_receipt": receipt,
            "status": AgentStatus.SUCCESS.value,
        }
