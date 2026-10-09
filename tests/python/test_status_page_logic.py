"""Status page honesty: state machine, stale handling, mutation guards."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import status_page_logic as logic  # noqa: E402
import status_repo_paths as paths  # noqa: E402

_PROBE_SPEC = importlib.util.spec_from_file_location("status_probe", _SCRIPTS / "status_probe.py")
assert _PROBE_SPEC and _PROBE_SPEC.loader
probe_mod = importlib.util.module_from_spec(_PROBE_SPEC)
sys.modules[_PROBE_SPEC.name] = probe_mod
_PROBE_SPEC.loader.exec_module(probe_mod)


def test_degraded_before_down_requires_consecutive_failures() -> None:
    status, failures = logic.derive_component_status(probe_ok=False, consecutive_failures=0)
    assert status == "degraded"
    assert failures == 1
    status, failures = logic.derive_component_status(probe_ok=False, consecutive_failures=1)
    assert status == "degraded"
    assert failures == 2
    status, failures = logic.derive_component_status(probe_ok=False, consecutive_failures=2)
    assert status == "down"
    assert failures == 3


def test_recovery_resets_consecutive_failures() -> None:
    status, failures = logic.derive_component_status(probe_ok=True, consecutive_failures=5)
    assert status == "operational"
    assert failures == 0


def test_stale_forces_unknown_display() -> None:
    assert logic.display_component_status("operational", stale=True) == "unknown"
    assert logic.display_component_status("down", stale=True) == "unknown"


def test_display_never_upgrades_failures() -> None:
    for stored in ("degraded", "down", "unknown"):
        shown = logic.display_component_status(stored, stale=False)
        logic.assert_honest_display(stored, shown)


def test_mutation_broken_probe_never_operational_after_three_failures() -> None:
    doc: dict | None = None
    for _ in range(3):
        outcomes = {key: probe_mod.ProbeOutcome(False, "simulated outage") for key, _ in probe_mod.COMPONENT_ORDER}
        doc = probe_mod.update_status_document(doc, outcomes, now=datetime(2026, 10, 9, 12, 0, tzinfo=UTC))
    for row in doc["components"].values():
        assert row["status"] in {"degraded", "down"}
        assert row["status"] != "operational"


def test_partial_failure_stays_degraded_not_operational() -> None:
    doc = probe_mod.update_status_document(
        None,
        {
            "api": probe_mod.ProbeOutcome(True, "ok"),
            "site": probe_mod.ProbeOutcome(False, "wrong html"),
            "app": probe_mod.ProbeOutcome(True, "ok"),
            "docs": probe_mod.ProbeOutcome(True, "ok"),
            "mcp_hosted": probe_mod.ProbeOutcome(True, "ok"),
            "mcp_compact": probe_mod.ProbeOutcome(True, "ok"),
            "capabilities": probe_mod.ProbeOutcome(True, "ok"),
        },
        now=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
    )
    assert doc["components"]["site"]["status"] == "degraded"
    assert doc["overall"] == "degraded"


def test_simulated_outage_flips_overall_down() -> None:
    doc: dict | None = None
    fail = {key: probe_mod.ProbeOutcome(False, "outage") for key, _ in probe_mod.COMPONENT_ORDER}
    for _ in range(3):
        doc = probe_mod.update_status_document(doc, fail, now=datetime(2026, 10, 9, 12, 0, tzinfo=UTC))
    assert doc["overall"] == "down"


def test_app_js_is_self_contained_and_honest() -> None:
    public = paths.status_public_dir(ROOT)
    js = (public / "app.js").read_text(encoding="utf-8")
    display = (public / "status_display.mjs").read_text(encoding="utf-8")
    assert "status_display.mjs" in js
    assert "if (stale) return \"unknown\"" in display
    assert "server_time" not in display or "Never uses probe-written" in display
    assert "google-analytics" not in js
    assert "googletagmanager" not in js


def test_status_json_bootstrap_is_valid() -> None:
    payload = json.loads(paths.status_bootstrap_state_path(ROOT).read_text(encoding="utf-8"))
    assert payload["overall"] == "unknown"
    assert len(payload["components"]) == 7
