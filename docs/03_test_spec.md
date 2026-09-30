# Test Specification

## Test Strategy
- Coverage target: all business-logic paths (per-node success + error/edge) plus one
  full-graph integration; hard % threshold enforced by the CI gate.
- Test types: Unit (per node) / Integration (full graph compile+invoke) / Proof-of-Boundary

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | Type check pass, no Pydantic/dataclass | |
| TC-02 | SecurityViolationError fires on invalid input | Error raised | |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations (S-5 enforcement is done in CI) | |
| TC-04 | InvocationContext via configurable only | Direct access raises error | |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from `execute()` body | 0 duplicates |
| TC-06 | S-2: `_security_gate_input()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-07 | S-3: `_security_gate_output()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-08 | `required_trust_level` enforced | Insufficient trust → refused | |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial when domain checks needed | Domain-specific input checks execute correctly (e.g. PII scan on additional fields, consent validation, business rules) | Hook body non-trivial |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial when domain checks needed | Domain-specific output checks execute correctly (e.g. nested credential scan, PII re-check, content filtering, preservation verification) | Hook body non-trivial |
| TC-11 | S-4: at least one domain `emit_trace_event()` inside each `execute()` | Domain event emitted on every invocation path | ≥1 per node |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures | |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass | |
| PB-3 | Level 2 → External service | Real external service connection | Data retrieved | |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations | |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass | |
| PB-6 | Invoke execution order | `__call__()`: S-1 trust gate → S-4 `node_start` → S-2 `_security_gate_input` → `execute()` → S-3 `_security_gate_output` → S-4 `node_complete` | Order verified | |

## Business Logic Tests (tests/unit/test_nodes.py, tests/integration/test_graph.py)

| TC-ID | Test | Input | Expected Result |
|-------|------|-------|----------------|
| BL-01 | InputValidate normalizes clean request | "start onboarding …" | SUCCESS |
| BL-02 | InputValidate rejects empty | "   " | ERROR |
| BL-03 | S-2 rejects Slack token | text with xoxb- token | ERROR |
| BL-04 | S-2 rejects 個人番号 | text with 12-digit number | ERROR |
| BL-05 | S-2 passes personal name | "onboarding for Tanaka Taro" | pass-through |
| BL-06 | WorkflowTrigger empty registry fail-safe | any | ERROR |
| BL-07 | WorkflowTrigger unresolved intent | unknown | ERROR, no candidates |
| BL-08 | WorkflowTrigger ambiguous | 2 matches | ERROR + candidate list |
| BL-09 | WorkflowTrigger success (LLM fields) | valid intent + fields | SUCCESS + execution_ref |
| BL-10 | OutputFormat hashes personal data | fields | sha256 confirmations |
| BL-11 | S-3 scrubs leaked credential | leaked token in output | field dropped |
| BL-12 | Full graph success | valid intent | SUCCESS, ≥5 node_history |
| BL-13 | Full graph refuses ANONYMOUS caller | INTERNAL required | ERROR/CANCELLED |

## Test Execution Summary
- Local: 16 unit + integration tests pass with the framework package on `PYTHONPATH`.
- PB-6 (`test_pb_invoke_order.py`) and `test_import_isolation.py` are the CI gate of record.
  PB-6 is skipped/adapted locally by design — the local framework mirror lacks the
  `emit_trace_event` stub on `base_node`, so the order assertion cannot run there; this is an
  expected local adaptation, not a test failure. Both pass under the CI wheel
  (`agenticstar-agentcore==1.0.0`) on Linux/UTF-8.

## 1. Deployment path tests

### TC-DEP-01 Marketplace entry point identity — `tests/unit/test_cli_entry_point.py`

| Case | Expected |
|---|---|
| Identity is concrete | `agent_name` / `namespace` are non-empty and not the runner default |
| Identity matches the HTTP entry point | the values equal what `src/api/server.py` passes to `secrets_factory`; where that entry point provisions no secrets, they equal the manifest `namespace` and the lower-cased template id |
| The runner call uses the constants | `run_agent_marketplace` is called with the module constants, not inline literals |

### TC-DEP-02 Standalone entry point boundary — `tests/proof_of_boundary/test_server_llm_injection.py`

| Case | Expected |
|---|---|
| Boots with no credential provisioned | the module imports and the app/agent objects are constructed |
| External bearer never reaches the internal level | resolves to the verified-external level |
| Staging runner credential reaches the internal level | resolves to the internal level |
| Wrong or missing bearer while auth is enabled | rejected with 401 |
