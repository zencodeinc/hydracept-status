"""Load and recover persisted probe state (honest on corrupt files)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from status_page_logic import DEFAULT_PROBE_INTERVAL_SECONDS, DEFAULT_STALE_AFTER_SECONDS

MAX_STATE_BYTES = 2_000_000
KNOWN_COMPONENT_KEYS = frozenset(
    {
        "api",
        "site",
        "app",
        "docs",
        "mcp_hosted",
        "mcp_compact",
        "capabilities",
    }
)
VALID_STATUSES = frozenset({"operational", "degraded", "down", "unknown"})


def _validate_state(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("state root must be an object")
    if payload.get("version") != 1:
        raise ValueError("unsupported state version")
    components = payload.get("components")
    if not isinstance(components, dict):
        raise ValueError("components must be an object")
    missing = KNOWN_COMPONENT_KEYS - set(components.keys())
    if missing:
        raise ValueError(f"missing components: {sorted(missing)}")
    for key, row in components.items():
        if key not in KNOWN_COMPONENT_KEYS:
            raise ValueError(f"unknown component key {key!r}")
        if not isinstance(row, dict):
            raise ValueError(f"component {key} must be an object")
        status = row.get("status", "unknown")
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status for {key}: {status!r}")
    return payload


def load_probe_state(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (previous state or None, recovery metadata when state was reset)."""
    if not path.is_file():
        return None, None
    raw = path.read_bytes()
    if len(raw) > MAX_STATE_BYTES:
        return None, {
            "reason": "state file too large",
            "detail": f"{len(raw)} bytes exceeds {MAX_STATE_BYTES}",
        }
    if not raw.strip():
        return None, {"reason": "empty state file", "detail": "file had no JSON content"}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, {"reason": "invalid JSON", "detail": str(exc)}
    try:
        validated = _validate_state(payload)
    except ValueError as exc:
        return None, {"reason": "invalid schema", "detail": str(exc)}
    validated.setdefault("probe_interval_seconds", DEFAULT_PROBE_INTERVAL_SECONDS)
    validated.setdefault("stale_after_seconds", DEFAULT_STALE_AFTER_SECONDS)
    return validated, None


def apply_state_recovery(document: dict[str, Any], recovery: dict[str, Any] | None) -> dict[str, Any]:
    if not recovery:
        return document
    document = dict(document)
    document["state_recovered"] = True
    document["state_recovery"] = {
        "reason": recovery.get("reason"),
        "detail": recovery.get("detail"),
    }
    return document
