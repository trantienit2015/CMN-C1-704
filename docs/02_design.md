# Template Design Specification — CMN-C1-704

## Position in AgentCore Architecture

- **Agent Class**: `Graph` (in `src/graph/graph.py`)
- **L1 Base**: AgentBaseGraph (Cat 1 — flat 3-slot backbone; no GraphNode)
- **Three-Layer Separation**:
  - State: flat `State(AgentState)`; all agent-specific fields `NotRequired`
  - Node: `FunctionNode.execute(self, state) -> dict` override only
  - Graph: `register_nodes()`; `add_edges()` NOT overridden

## Architecture Overview

```
initialize → pre_process(InputValidate) → main(WorkflowTrigger) → post_process(OutputFormat) → finalize
```

### Node Configuration

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | trust level, session | — | — | InitializeNode (default) |
| pre_process (InputValidate) | S-1 INTERNAL trust + S-2 credential/個人番号 scan | user_input | validated_input | FunctionNode |
| main (WorkflowTrigger) | LLM resolve workflow_id + fields; deterministic registry + schema validation; trigger dispatch; S-4 audit | validated_input | resolved_workflow_id, input_fields, execution_ref, trigger_receipt | FunctionNode |
| post_process (OutputFormat) | S-3 credential scan; hash personal-data confirmations | resolved_workflow_id, input_fields | formatted_output | FunctionNode |
| finalize | response_metadata | — | — | FinalizeNode (default) |

### Node mapping vs IDEA backbone

- IDEA step 1 (InputValidate) and step 5 (OutputFormat) are the framework S-1/S-2 and S-3 gates,
  realized via `_extra_security_gate_input()` / `_extra_security_gate_output()` on the first/last
  nodes — not separate graph nodes.
- IDEA step 2 (RequestParse) + step 3 (WorkflowValidate + InputFieldValidate) + step 4
  (trigger + S-4 audit) collapse into `WorkflowTrigger` (`main`): the LLM resolution, the two
  deterministic validators (registry + field schema), and the trigger dispatch run in
  `main`'s execute chain. There is no standalone AuditLogNode — S-4 is inline.

### State Definition (agent-specific fields, all `NotRequired`)

| Field | Type | Purpose |
|-------|------|---------|
| resolved_workflow_id | str | resolved workflow id |
| input_fields | dict | resolved input field values |
| candidates | list[str] | ambiguous-resolution candidate list |
| confidence_flags | list[str] | resolution confidence markers |
| execution_ref | str | trigger execution reference |
| trigger_receipt | dict | full trigger receipt |

**State Constraints:** flat TypedDict; no credentials/JWT/Pydantic; InvocationContext via
`config["configurable"]` only.

## Framework Utilization / Security (5-layer)

- **S-1** — `required_trust_level = INTERNAL` on every node (automation-triggering).
- **S-2** — `PreProcessNode._extra_security_gate_input()` rejects Slack tokens (xoxb-/xapp-),
  Bearer/JWT, and 個人番号 (12-digit My-Number). Personal names pass through (legitimate payload).
- **S-3** — `PostProcessNode._extra_security_gate_output()` credential-pattern scan; personal-data
  values echoed only as `sha256:` confirmation hashes.
- **S-4** — `emit_trace_event()` in every node; the trigger event logs field NAMES + hashed values
  + execution ref — APPI consent-flow evidence.
- **S-5** — framework credential scan; secret `slack_workflow_token` via `ctx.secrets.require()` /
  `bound_secrets`, never `os.environ`, never in State.

### Determinism guardrails

- Registry unset/empty → fail-safe error (no default-allow).
- Ambiguous resolution → candidate list, no guess.
- Field schema / registry validation is deterministic; the LLM never overrides a hard block.
- Idempotency: the trigger tool keys on request-id (correlation_id) to avoid duplicate triggers.

## Import Isolation

- [x] No Level 0 (`agenticstar`) import.
- [x] Import targets: `framework/`, `shared/`, `src.` only.

## Design Decision Record

| Decision | Chosen | Rationale |
|----------|--------|-----------|
| L1 base type | AgentBaseGraph | Cat 1 single capability, flat backbone |
| Composition pattern | Standalone (no GraphNode) | one capability, not a domain workflow |
| Trust level | INTERNAL | triggers automation on behalf of internal callers |
| Resolution | injectable LLM + deterministic fallback | runnable/testable without a live LLM |

## 1. Deployment entry points

The agent is reachable through two entry points, and both resolve their runtime inputs the same way.

| Entry point | File | Used by |
|---|---|---|
| Standalone HTTP | `src/api/server.py` | staging rehearsal, direct invocation |
| Marketplace one-shot Pod | `cli.py` | the platform runner (container `CMD`) |

Both read runtime parameters from `config/config.yaml` — the manifest carries discovery metadata
only — and both scope secrets to the same location (`namespace=cmn`, `agent_name=cmn-c1-704`), so a
secret provisioned for one path resolves identically on the other.

**Deployment-provided LLM client.** The three Azure OpenAI connection values
(`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` — the bare resource endpoint — and
`AZURE_OPENAI_DEPLOYMENT`) are resolved through the agent's own secret provider, never from the
process environment. Both entry points build the client only when all three resolve and pass it in
as `config["llm"]`; when any is absent the key stays unset and the graph keeps its deterministic
path. The manifest declares the three secrets and the provider extra.

**Progress events.** Each pipeline stage emits a non-terminal progress event at its start, so a
caller sees the run advancing. Outside the Marketplace runtime the emitter resolves to a no-op, so
the same code is safe on every path. Terminal events belong to the platform runner and are never
emitted by this agent.

**Caller authentication at the standalone entry point.** A caller that no upstream middleware
vouched for stays anonymous unless it presents a deployment-level credential: the external bearer
token grants the verified-external level, and a separate staging-only runner credential is the only
way to reach the internal level. Trust established upstream is never changed.

**Marketplace Pod trust ceiling (present-state constraint).** AgentCore 1.0.3's Marketplace one-shot
Pod runtime (`shared/bootstrap/marketplace_app.py`) stamps every invocation's caller trust as
`VERIFIED_EXTERNAL` unconditionally — there is no elevation path. Since this agent's `S-1` gate
requires `INTERNAL` on every node, the Marketplace Pod entry point currently rejects every
invocation it receives; this is a known platform-level constraint, not a bug in this template.
Lowering `required_trust_level` to force compatibility is out of scope — that change needs a
platform decision, not a per-template code fix. Until the platform closes this gap, the Marketplace
Pod path is not a viable deployment target for this agent; the standalone HTTP entry point above is
the supported path today.
