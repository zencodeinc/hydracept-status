"""CLI integration: persisted state across probe runs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import status_repo_paths as paths  # noqa: E402

PROBE = paths.status_scripts_dir(ROOT) / "status_probe.py"


def _run_probe(state: Path, scenario: str) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            str(PROBE),
            "--state",
            str(state),
            "--write",
            str(state),
            "--mock-scenario",
            scenario,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={"HYDRACEPT_DEPLOY_SMOKE_API_KEY": "", **dict(__import__("os").environ)},
    )
    assert proc.returncode == 0
    return json.loads(state.read_text(encoding="utf-8"))


def test_cli_three_down_runs_reach_down(tmp_path: Path) -> None:
    state = tmp_path / "probe-state.json"
    shutil_copy_bootstrap(state)
    for _ in range(3):
        doc = _run_probe(state, "down")
    assert doc["components"]["api"]["status"] == "down"
    assert doc["components"]["api"]["consecutive_failures"] >= 3
    assert doc["overall"] == "down"


def test_cli_partial_failure_degraded_not_operational(tmp_path: Path) -> None:
    state = tmp_path / "probe-state.json"
    shutil_copy_bootstrap(state)
    doc = _run_probe(state, "partial")
    assert doc["components"]["api"]["status"] == "degraded"
    assert doc["overall"] == "degraded"


def test_cli_accumulates_history_samples(tmp_path: Path) -> None:
    state = tmp_path / "probe-state.json"
    shutil_copy_bootstrap(state)
    _run_probe(state, "ok")
    doc = _run_probe(state, "ok")
    total = sum(
        int(row.get("samples_total") or 0)
        for row in doc["components"]["api"].get("history_days") or []
    )
    assert total >= 2
    assert doc["components"]["api"].get("history_collecting") is True


def test_mcp_mismatch_not_operational(tmp_path: Path) -> None:
    state = tmp_path / "probe-state.json"
    shutil_copy_bootstrap(state)
    doc = _run_probe(state, "mcp_mismatch")
    assert doc["components"]["mcp_hosted"]["status"] == "degraded"
    assert doc["components"]["mcp_hosted"]["status"] != "operational"


def shutil_copy_bootstrap(state: Path) -> None:
    bootstrap = paths.status_bootstrap_state_path(ROOT)
    state.write_text(bootstrap.read_text(encoding="utf-8"), encoding="utf-8")
