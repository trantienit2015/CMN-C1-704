"""AgentCore Platform v1.0 — deterministic Slack Workflow Builder trigger tool for CMN-C1-704.

Pure, deterministic helpers: workflow-registry resolution, input-field schema validation,
credential/個人番号 scanning, and trigger dispatch through an injectable client. No secrets are
read from os.environ here; the caller passes a resolved token / client. No network I/O when no
client is injected (dry-run receipt) so the agent is runnable and testable without a live
Slack workspace.
"""

from __future__ import annotations

from typing import Any, Protocol

import hashlib
import re

# Deterministic patterns that must never appear in a trigger request payload.
_CREDENTIAL_PATTERNS = [
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack bot/app/user tokens
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{10,}"),  # bearer tokens
    re.compile(r"eyJ[A-Za-z0-9._-]{20,}"),  # JWT
]
# 個人番号 (My Number) — 12 consecutive digits, optionally space/hyphen grouped.
_MYNUMBER_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12}(?!\d)")


def scan_credentials(text: str) -> list[str]:
    """Return the names of credential/PII patterns found in ``text`` (empty = clean)."""
    hits: list[str] = []
    for pat in _CREDENTIAL_PATTERNS:
        if pat.search(text or ""):
            hits.append("credential_token")
            break
    if _MYNUMBER_PATTERN.search((text or "").replace(" ", "").replace("-", "")):
        # only flag a genuine 12-digit run, not arbitrary text
        digits = re.sub(r"\D", "", text or "")
        if re.search(r"\d{12}", digits):
            hits.append("my_number")
    return hits


def hash_value(value: str) -> str:
    """Stable short hash for personal-data confirmation in audit/output."""
    return "sha256:" + hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]


def resolve_workflow(intent: str, registry: dict[str, Any]) -> dict[str, Any]:
    """Semantic-ish resolution of intent → workflow id against the configured registry.

    Deterministic keyword match against registry entries. Ambiguous (multiple matches) →
    return candidate list without guessing. Workflows not in the registry are unreachable.
    """
    if not registry:
        return {"error": "registry_empty", "workflow_id": None, "candidates": []}
    low = (intent or "").lower()
    matches = []
    for wid, spec in registry.items():
        keywords = [wid.lower()] + [k.lower() for k in spec.get("keywords", [])]
        if any(k in low for k in keywords):
            matches.append(wid)
    if len(matches) == 1:
        return {"workflow_id": matches[0], "candidates": []}
    if len(matches) > 1:
        return {"workflow_id": None, "candidates": matches}
    return {"workflow_id": None, "candidates": []}


def validate_input_fields(workflow_id: str, input_fields: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    """Validate inferred input_fields against the workflow's declared schema.

    Returns {ok: bool, missing: [...], invalid: [...]}.
    """
    spec = (registry or {}).get(workflow_id, {})
    schema = spec.get("input_schema", {})
    required = [f for f, meta in schema.items() if meta.get("required")]
    missing = [f for f in required if f not in (input_fields or {})]
    invalid = []
    for f, val in (input_fields or {}).items():
        meta = schema.get(f)
        if meta is None:
            invalid.append(f)  # field not in schema
            continue
        expected = meta.get("type")
        if expected == "string" and not isinstance(val, str):
            invalid.append(f)
        elif expected == "int" and not isinstance(val, int):
            invalid.append(f)
    return {"ok": not missing and not invalid, "missing": missing, "invalid": invalid}


class TriggerClient(Protocol):
    """Surface the injected dispatch client must expose.

    Declared here so the injected object is checked against a real contract
    rather than passed as an untyped value.
    """

    def trigger(self, *, workflow_id: str, input_fields: dict[str, Any], request_id: str) -> dict[str, Any]: ...


def trigger_workflow(
    workflow_id: str, input_fields: dict[str, Any], request_id: str, client: "TriggerClient | None" = None
) -> dict[str, Any]:
    """Dispatch the workflow trigger. If ``client`` is injected it is used (with idempotency
    on request_id); otherwise a deterministic dry-run receipt is returned.
    """
    # Keep the attribute guard: an injected object that does not expose trigger()
    # falls through to the dry-run receipt rather than raising.
    if client is not None and hasattr(client, "trigger"):
        return client.trigger(workflow_id=workflow_id, input_fields=input_fields, request_id=request_id)
    # dry-run deterministic execution reference
    exec_ref = "exec:" + hashlib.sha256(f"{workflow_id}:{request_id}".encode("utf-8")).hexdigest()[:16]
    return {"execution_ref": exec_ref, "workflow_id": workflow_id, "dry_run": True}
