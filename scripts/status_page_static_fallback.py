"""Render a no-JavaScript status snapshot for status.hydracept.com."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datetime import UTC, datetime

from status_page_logic import overall_from_components, is_probe_stale

_MARKER = "<!-- HYDRACEPT_STATUS_STATIC_FALLBACK -->"


def _overall_label(status: str) -> str:
    labels = {
        "operational": "All systems operational",
        "degraded": "Partial degradation",
        "down": "Outage",
        "unknown": "Status unknown",
    }
    return labels.get(status, "Status unknown")


def render_static_fallback_html(status_doc: dict[str, Any]) -> str:
    components = status_doc.get("components") or {}
    component_statuses = {
        key: str((value or {}).get("status") or "unknown")
        for key, value in components.items()
        if isinstance(value, dict)
    }
    stale_after = int(status_doc.get("stale_after_seconds") or 900)
    stale = is_probe_stale(
        str(status_doc.get("generated_at") or ""),
        now=datetime.now(UTC),
        stale_after_seconds=stale_after,
    )
    overall = overall_from_components(component_statuses, stale=stale)  # type: ignore[arg-type]
    generated = status_doc.get("generated_at") or "unknown time"
    lines = [
        f'<p class="static-overall"><strong>{_overall_label(overall)}</strong></p>',
        f'<p class="static-meta">Last probe: {generated}. JavaScript loads live detail and history.</p>',
        "<ul class=\"static-components\">",
    ]
    for key in sorted(component_statuses):
        row = components.get(key) if isinstance(components, dict) else None
        name = str((row or {}).get("display_name") or key)
        status = component_statuses[key]
        detail = str((row or {}).get("detail") or "").strip()
        suffix = f" — {detail}" if detail else ""
        lines.append(f"<li><span>{name}</span>: {status}{suffix}</li>")
    lines.append("</ul>")
    return "\n".join(lines)


def inject_static_fallback(index_html: str, status_doc: dict[str, Any]) -> str:
    if _MARKER not in index_html:
        raise ValueError(f"index.html missing {_MARKER}")
    block = render_static_fallback_html(status_doc)
    return index_html.replace(_MARKER, block)


def inject_from_status_file(index_path: Path, status_path: Path) -> str:
    status_doc = json.loads(status_path.read_text(encoding="utf-8"))
    html = index_path.read_text(encoding="utf-8")
    return inject_static_fallback(html, status_doc)
