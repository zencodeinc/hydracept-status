"""Status probe checks against stubbed HTTP (no live network in CI)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("status_probe", ROOT / "scripts" / "status_probe.py")
assert _SPEC and _SPEC.loader
probe = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = probe
_SPEC.loader.exec_module(probe)

_JSON = "application/json"
_HTML = "text/html; charset=utf-8"
_HOSTED = ["hydracept_run", "hydracept_status"]
_COMPACT = [f"tool_{i}" for i in range(9)]


def _fetch(url: str, method: str = "GET", **kwargs):  # noqa: ANN001
    if url.endswith("/healthz"):
        return 200, _JSON, b'{"status":"ok"}'
    if url.endswith("/v1/capabilities"):
        return 200, _JSON, b'{"capabilities":[{"key":"text.general.fast.v1"}]}'
    if url.endswith("/v1/agent-context"):
        return (
            200,
            _JSON,
            json.dumps(
                {
                    "mcp": {
                        "toolsBySurface": {
                            "hosted": _HOSTED,
                            "hostedCompact": _COMPACT,
                        }
                    }
                }
            ).encode(),
        )
    if "/mcp" in url and method == "POST":
        body = json.loads((kwargs.get("body") or b"{}").decode())
        method_name = body.get("method")
        req_id = body.get("id", 1)
        if method_name == "tools/list":
            tools = _HOSTED if "/mcp/full" in url else _COMPACT
            result = {"tools": [{"name": name} for name in tools]}
        else:
            result = {}
        line = json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})
        return 200, "text/event-stream", f"event: message\ndata: {line}\n\n".encode()
    if url.endswith("/") and method == "GET":
        padding = "x" * 500
        return (
            200,
            _HTML,
            (
                f"<html><body>Hydracept Hydracept Studio Hydracept Docs {padding}</body>"
                f'<link rel="stylesheet" href="/assets/index-deadbeef.css"></html>'
            ).encode(),
        )
    if "/assets/" in url:
        return 200, "text/css", b"x" * 400
    return 404, _JSON, b"{}"


def test_run_probes_all_ok() -> None:
    cfg = probe.Config()
    outcomes = probe.run_probes(cfg, fetch=_fetch)
    assert all(outcome.ok for outcome in outcomes.values())


def test_wrong_healthz_not_ok() -> None:
    def bad_fetch(url: str, method: str = "GET", **kwargs):  # noqa: ANN001
        if url.endswith("/healthz"):
            return 200, _JSON, b'{"status":"broken"}'
        return _fetch(url, method, **kwargs)

    outcome = probe.probe_api_health(probe.Config(), bad_fetch)
    assert not outcome.ok


def test_http_500_is_not_operational() -> None:
    def fail_fetch(url: str, method: str = "GET", **kwargs):  # noqa: ANN001
        if url.endswith("/healthz"):
            return 500, _JSON, b"{}"
        return _fetch(url, method, **kwargs)

    doc = probe.update_status_document(
        None,
        probe.run_probes(probe.Config(), fetch=fail_fetch),
    )
    assert doc["components"]["api"]["status"] == "degraded"


def test_dns_failure_surfaces_as_probe_failure() -> None:
    def broken(url: str, method: str = "GET", **kwargs):  # noqa: ANN001
        raise probe.ProbeFailure("dns failed")

    outcome = probe.probe_api_health(probe.Config(), broken)
    assert not outcome.ok
    assert "dns" in outcome.detail.lower()
