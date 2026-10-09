"""External status probe for status.hydracept.com (keyless public checks only)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from site_linked_assets import linked_asset_paths  # noqa: E402

_PROBE_ASSET_RE = re.compile(
    r"""(?:src|href)\s*=\s*["'](?P<path>(?:/assets/|\./assets/|assets/)[^"'?#]+)["']""",
    re.IGNORECASE,
)
_PROBE_SCRIPT_RE = re.compile(
    r"""src\s*=\s*["'](?P<path>/[a-z0-9][a-z0-9._/-]*\.js)["']""",
    re.IGNORECASE,
)
from status_page_logic import (  # noqa: E402
    DEFAULT_PROBE_INTERVAL_SECONDS,
    DEFAULT_STALE_AFTER_SECONDS,
    STALE_AFTER_INTERVAL_MULTIPLIER,
    HISTORY_DAYS,
    MIN_SAMPLES_FOR_UPTIME,
    ProbeOutcome,
    derive_component_status,
    history_collecting,
    overall_from_components,
    roll_history_day,
    uptime_percent,
)

_SURFACE_MARKERS: dict[str, str] = {
    "site": "Hydracept",
    "app": "Hydracept Studio",
    "docs": "Hydracept Docs",
}

DEFAULT_API = "https://api.hydracept.com"
DEFAULT_SITE = "https://hydracept.com"
DEFAULT_APP = "https://app.hydracept.com"
DEFAULT_DOCS = "https://docs.hydracept.com"
DEFAULT_TIMEOUT = 20.0
_USER_AGENT = "hydracept-status-probe/1"

_INITIALIZE_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "hydracept-status-probe", "version": "1"},
    },
}

COMPONENT_ORDER: tuple[tuple[str, str], ...] = (
    ("api", "API"),
    ("site", "Marketing site"),
    ("app", "Studio (app)"),
    ("docs", "Documentation"),
    ("mcp_hosted", "Hosted MCP (/mcp)"),
    ("mcp_compact", "Hosted MCP compact"),
    ("capabilities", "Capability catalog"),
)


@dataclass
class Config:
    api_base: str = DEFAULT_API
    site_base: str = DEFAULT_SITE
    app_base: str = DEFAULT_APP
    docs_base: str = DEFAULT_DOCS
    timeout: float = DEFAULT_TIMEOUT


@dataclass
class ComponentState:
    display_name: str
    status: str = "unknown"
    last_checked_at: str | None = None
    detail: str = "Not checked yet"
    consecutive_failures: int = 0
    history_days: list[dict[str, Any]] = field(default_factory=list)


class ProbeFailure(Exception):
    pass


Fetcher = Any


def _fetch(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("User-Agent", _USER_AGENT)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers.get("content-type", ""), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", "") if exc.headers else "", exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProbeFailure(f"request failed: {exc}") from exc


def _expect_status(url: str, status: int, *, expected: int = 200) -> None:
    if status != expected:
        raise ProbeFailure(f"HTTP {status} from {url}, expected {expected}")


def _json_body(url: str, content_type: str, raw: bytes) -> dict[str, Any]:
    if "json" not in content_type.lower():
        raise ProbeFailure(f"{url} content-type {content_type!r}, expected JSON")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeFailure(f"{url} invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProbeFailure(f"{url} expected JSON object")
    return payload


def _parse_mcp_sse_json(raw: bytes) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def _mcp_post(cfg: Config, fetch: Fetcher, path: str, body: dict[str, Any]) -> dict[str, Any]:
    url = f"{cfg.api_base}{path}"
    status, _ctype, raw = fetch(
        url,
        method="POST",
        body=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        timeout=cfg.timeout,
    )
    _expect_status(url, status)
    messages = _parse_mcp_sse_json(raw)
    for message in reversed(messages):
        if message.get("id") == body.get("id") and "result" in message:
            result = message["result"]
            if isinstance(result, dict):
                return result
    raise ProbeFailure(f"{url} MCP {body.get('method')} returned no result")


def _probe_asset_paths(html: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in linked_asset_paths(html):
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    for match in _PROBE_ASSET_RE.finditer(html):
        raw = match.group("path").strip()
        normalized = raw[1:] if raw.startswith("./") else raw
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        if normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    for match in _PROBE_SCRIPT_RE.finditer(html):
        path = match.group("path")
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def _check_html_surface(
    cfg: Config,
    fetch: Fetcher,
    base: str,
    *,
    label: str,
    marker: str,
) -> ProbeOutcome:
    url = base.rstrip("/") + "/"
    try:
        status, ctype, raw = fetch(url, method="GET", timeout=cfg.timeout)
        _expect_status(url, status)
        html = raw.decode("utf-8", errors="replace")
        if "html" not in ctype.lower() or len(html) < 400:
            raise ProbeFailure("response is not HTML")
        if marker not in html:
            raise ProbeFailure(f"missing expected marker {marker!r}")
        assets = _probe_asset_paths(html)
        if not assets:
            raise ProbeFailure("no linked static assets in HTML")
        asset_url = base.rstrip("/") + assets[0]
        a_status, _a_ctype, a_raw = fetch(asset_url, method="GET", timeout=cfg.timeout)
        _expect_status(asset_url, a_status)
        if len(a_raw) < 200:
            raise ProbeFailure(f"asset {assets[0]} too small")
        return ProbeOutcome(True, f"{label} ok ({assets[0]})")
    except ProbeFailure as exc:
        return ProbeOutcome(False, str(exc))


def probe_api_health(cfg: Config, fetch: Fetcher) -> ProbeOutcome:
    url = f"{cfg.api_base}/healthz"
    try:
        status, ctype, raw = fetch(
            url,
            method="GET",
            headers={"Accept": "application/json"},
            timeout=cfg.timeout,
        )
        _expect_status(url, status)
        payload = _json_body(url, ctype, raw)
        if payload.get("status") != "ok":
            raise ProbeFailure(f"healthz status={payload.get('status')!r}")
        return ProbeOutcome(True, "healthz ok")
    except ProbeFailure as exc:
        return ProbeOutcome(False, str(exc))


def probe_capabilities(cfg: Config, fetch: Fetcher) -> ProbeOutcome:
    url = f"{cfg.api_base}/v1/capabilities"
    try:
        status, ctype, raw = fetch(
            url,
            method="GET",
            headers={"Accept": "application/json"},
            timeout=cfg.timeout,
        )
        _expect_status(url, status)
        payload = _json_body(url, ctype, raw)
        capabilities = payload.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            raise ProbeFailure("empty capabilities list")
        first = capabilities[0]
        if not isinstance(first, dict) or not first.get("key"):
            raise ProbeFailure("capability entry missing key")
        return ProbeOutcome(True, f"{len(capabilities)} capabilities")
    except ProbeFailure as exc:
        return ProbeOutcome(False, str(exc))


def _expected_hosted_tools(cfg: Config, fetch: Fetcher) -> list[str]:
    url = f"{cfg.api_base}/v1/agent-context"
    status, ctype, raw = fetch(
        url,
        method="GET",
        headers={"Accept": "application/json"},
        timeout=cfg.timeout,
    )
    _expect_status(url, status)
    payload = _json_body(url, ctype, raw)
    mcp = payload.get("mcp") or {}
    by_surface = mcp.get("toolsBySurface") or {}
    hosted = sorted(str(name) for name in (by_surface.get("hosted") or []))
    if not hosted:
        raise ProbeFailure("agent-context missing toolsBySurface.hosted")
    return hosted


def _expected_compact_tools(cfg: Config, fetch: Fetcher) -> list[str]:
    url = f"{cfg.api_base}/v1/agent-context"
    status, ctype, raw = fetch(
        url,
        method="GET",
        headers={"Accept": "application/json"},
        timeout=cfg.timeout,
    )
    _expect_status(url, status)
    payload = _json_body(url, ctype, raw)
    mcp = payload.get("mcp") or {}
    by_surface = mcp.get("toolsBySurface") or {}
    compact = sorted(str(name) for name in (by_surface.get("hostedCompact") or []))
    if not compact:
        raise ProbeFailure("agent-context missing toolsBySurface.hostedCompact")
    return compact


def probe_mcp_hosted(cfg: Config, fetch: Fetcher) -> ProbeOutcome:
    try:
        expected = _expected_hosted_tools(cfg, fetch)
        _mcp_post(cfg, fetch, "/mcp", {**_INITIALIZE_BODY, "id": 1})
        listed = _mcp_post(
            cfg,
            fetch,
            "/mcp",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools = listed.get("tools") or []
        if not isinstance(tools, list):
            raise ProbeFailure("tools/list tools is not a list")
        actual = sorted(str(item.get("name")) for item in tools if isinstance(item, dict) and item.get("name"))
        if actual != expected:
            raise ProbeFailure(
                f"tools/list mismatch (expected {len(expected)}, got {len(actual)})"
            )
        return ProbeOutcome(True, f"/mcp tools/list ok ({len(actual)} tools)")
    except ProbeFailure as exc:
        return ProbeOutcome(False, str(exc))


def probe_mcp_compact(cfg: Config, fetch: Fetcher) -> ProbeOutcome:
    try:
        expected = _expected_compact_tools(cfg, fetch)
        _mcp_post(cfg, fetch, "/mcp/compact", {**_INITIALIZE_BODY, "id": 1})
        listed = _mcp_post(
            cfg,
            fetch,
            "/mcp/compact",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        tools = listed.get("tools") or []
        actual = sorted(str(item.get("name")) for item in tools if isinstance(item, dict) and item.get("name"))
        if actual != expected:
            raise ProbeFailure(f"/mcp/compact tools/list mismatch (expected {len(expected)})")
        return ProbeOutcome(True, f"/mcp/compact ok ({len(actual)} tools)")
    except ProbeFailure as exc:
        return ProbeOutcome(False, str(exc))


def _safe_probe(component_key: str, fn: Any, *args: Any, **kwargs: Any) -> ProbeOutcome:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return ProbeOutcome(False, f"{component_key} probe error: {exc}")


def run_probes(cfg: Config, fetch: Fetcher | None = None) -> dict[str, ProbeOutcome]:
    fetcher = fetch or _fetch
    return {
        "api": _safe_probe("api", probe_api_health, cfg, fetcher),
        "site": _safe_probe(
            "site",
            _check_html_surface,
            cfg,
            fetcher,
            cfg.site_base,
            label="site",
            marker=_SURFACE_MARKERS["site"],
        ),
        "app": _safe_probe(
            "app",
            _check_html_surface,
            cfg,
            fetcher,
            cfg.app_base,
            label="app",
            marker=_SURFACE_MARKERS["app"],
        ),
        "docs": _safe_probe(
            "docs",
            _check_html_surface,
            cfg,
            fetcher,
            cfg.docs_base,
            label="docs",
            marker=_SURFACE_MARKERS["docs"],
        ),
        "mcp_hosted": _safe_probe("mcp_hosted", probe_mcp_hosted, cfg, fetcher),
        "mcp_compact": _safe_probe("mcp_compact", probe_mcp_compact, cfg, fetcher),
        "capabilities": _safe_probe("capabilities", probe_capabilities, cfg, fetcher),
    }


def mock_fetch_for_scenario(scenario: str) -> Fetcher:
    """Test-only fetcher for CLI integration tests (no network)."""

    def _mock(url: str, method: str = "GET", **kwargs: Any) -> tuple[int, str, bytes]:
        if scenario == "down":
            return 503, "text/plain", b"outage"
        if scenario == "partial" and url.endswith("/healthz"):
            return 503, "application/json", b"{}"
        if scenario == "mcp_mismatch" and "/mcp" in url and method == "POST":
            body = json.loads((kwargs.get("body") or b"{}").decode())
            if body.get("method") == "tools/list":
                line = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": {"tools": []}})
                return 200, "text/event-stream", f"event: message\ndata: {line}\n\n".encode()
        # fall through to minimal ok responses
        if url.endswith("/healthz"):
            return 200, "application/json", b'{"status":"ok"}'
        if url.endswith("/v1/capabilities"):
            return 200, "application/json", b'{"capabilities":[{"key":"k"}]}'
        if url.endswith("/v1/agent-context"):
            payload = {
                "mcp": {
                    "toolsBySurface": {
                        "hosted": ["tool_a"],
                        "hostedCompact": ["c1", "c2"],
                    }
                }
            }
            return 200, "application/json", json.dumps(payload).encode()
        if url.endswith("/") and method == "GET":
            html = (
                "<html><body>Hydracept Hydracept Studio Hydracept Docs "
                + ("x" * 500)
                + '</body><link rel="stylesheet" href="/assets/x.css"></html>'
            )
            return 200, "text/html", html.encode()
        if "/assets/" in url or url.endswith(".css"):
            return 200, "text/css", b"x" * 400
        if "/mcp" in url and method == "POST":
            body = json.loads((kwargs.get("body") or b"{}").decode())
            req_id = body.get("id", 1)
            if body.get("method") == "tools/list":
                names = ["c1", "c2"] if "/compact" in url else ["tool_a"]
                result = {"tools": [{"name": n} for n in names]}
            else:
                result = {}
            line = json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})
            return 200, "text/event-stream", f"event: message\ndata: {line}\n\n".encode()
        return 404, "text/plain", b""

    return _mock


def _empty_state() -> dict[str, Any]:
    components: dict[str, Any] = {}
    for key, label in COMPONENT_ORDER:
        components[key] = {
            "display_name": label,
            "status": "unknown",
            "last_checked_at": None,
            "detail": "Awaiting first probe",
            "consecutive_failures": 0,
            "history_days": [],
            "uptime_percent_90d": None,
        }
    return {
        "version": 1,
        "generated_at": None,
        "probe_interval_seconds": DEFAULT_PROBE_INTERVAL_SECONDS,
        "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS,
        "overall": "unknown",
        "components": components,
    }


def update_status_document(
    previous: dict[str, Any] | None,
    outcomes: dict[str, ProbeOutcome],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or datetime.now(tz=UTC)
    checked_at = moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
    doc = dict(previous or _empty_state())
    components: dict[str, Any] = dict(doc.get("components") or {})
    display_statuses: dict[str, str] = {}

    for key, label in COMPONENT_ORDER:
        prev = dict(components.get(key) or {})
        prev.setdefault("display_name", label)
        outcome = outcomes[key]
        status, failures = derive_component_status(
            probe_ok=outcome.ok,
            consecutive_failures=int(prev.get("consecutive_failures") or 0),
        )
        history = roll_history_day(
            list(prev.get("history_days") or []),
            day=moment.astimezone(UTC).date(),
            sample_ok=outcome.ok,
        )
        collecting = history_collecting(history)
        prev.update(
            {
                "display_name": label,
                "status": status,
                "last_checked_at": checked_at,
                "detail": outcome.detail,
                "consecutive_failures": failures,
                "history_days": history,
                "history_collecting": collecting,
                "uptime_percent_90d": uptime_percent(history),
            }
        )
        components[key] = prev
        display_statuses[key] = status

    doc["components"] = components
    doc["generated_at"] = checked_at
    doc.pop("server_time", None)
    doc["min_samples_for_uptime"] = MIN_SAMPLES_FOR_UPTIME
    interval = int(doc.get("probe_interval_seconds") or DEFAULT_PROBE_INTERVAL_SECONDS)
    doc["probe_interval_seconds"] = interval
    doc["stale_after_seconds"] = interval * STALE_AFTER_INTERVAL_MULTIPLIER
    doc["overall"] = overall_from_components(display_statuses, stale=False)
    doc["history_days_retained"] = HISTORY_DAYS
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=os.environ.get("HYDRACEPT_API_URL") or DEFAULT_API)
    parser.add_argument("--site-base", default=os.environ.get("HYDRACEPT_SITE_URL") or DEFAULT_SITE)
    parser.add_argument("--app-base", default=os.environ.get("HYDRACEPT_APP_URL") or DEFAULT_APP)
    parser.add_argument("--docs-base", default=os.environ.get("HYDRACEPT_DOCS_URL") or DEFAULT_DOCS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--state", type=Path, help="Existing status.json to merge")
    parser.add_argument("--write", type=Path, help="Write updated status.json")
    parser.add_argument("--json", action="store_true", help="Print status document")
    parser.add_argument(
        "--mock-scenario",
        choices=("down", "partial", "mcp_mismatch", "ok"),
        help="Test harness only: use stubbed fetcher instead of the network.",
    )
    args = parser.parse_args(argv)

    cfg = Config(
        api_base=args.api_base.rstrip("/"),
        site_base=args.site_base.rstrip("/"),
        app_base=args.app_base.rstrip("/"),
        docs_base=args.docs_base.rstrip("/"),
        timeout=args.timeout,
    )
    from status_probe_state import apply_state_recovery, load_probe_state  # noqa: PLC0415

    previous: dict[str, Any] | None = None
    recovery: dict[str, Any] | None = None
    if args.state:
        previous, recovery = load_probe_state(args.state)

    fetcher = mock_fetch_for_scenario(args.mock_scenario) if args.mock_scenario else None
    outcomes = run_probes(cfg, fetch=fetcher)
    document = update_status_document(previous, outcomes)
    document = apply_state_recovery(document, recovery)
    payload = json.dumps(document, indent=2, sort_keys=False) + "\n"

    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(payload, encoding="utf-8")
    if args.json or not args.write:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
