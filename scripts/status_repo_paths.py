"""Resolve paths for status page tests in monorepo or exported public repo."""

from __future__ import annotations

from pathlib import Path


def status_repo_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    candidates = [here.parent, *here.parents]
    for parent in candidates:
        if (parent / "status_display.mjs").is_file() and (parent / "scripts" / "status_probe.py").is_file():
            return parent
        if (parent / "apps" / "status" / "public" / "status_display.mjs").is_file():
            return parent
    raise RuntimeError("could not locate status repo root")


def status_public_dir(root: Path | None = None) -> Path:
    root = root or status_repo_root()
    if (root / "status_display.mjs").is_file():
        return root
    return root / "apps" / "status" / "public"


def status_scripts_dir(root: Path | None = None) -> Path:
    return (root or status_repo_root()) / "scripts"


def status_bootstrap_state_path(root: Path | None = None) -> Path:
    root = root or status_repo_root()
    exported = root / "bootstrap" / "probe-state.json"
    if exported.is_file():
        return exported
    return status_public_dir(root) / "status.json"
