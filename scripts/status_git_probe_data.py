"""Probe state on orphan probe-data branch (single commit, force-pushed)."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROBE_DATA_BRANCH = "probe-data"
STATE_REL = Path("data/probe-state.json")
FETCH_DEPTH = "1"


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def _remote_has_probe_branch(repo_dir: Path, remote: str) -> bool:
    show = _run(["git", "ls-remote", "--heads", remote, PROBE_DATA_BRANCH], cwd=repo_dir, check=False)
    if show.returncode != 0:
        raise SystemExit(
            f"git ls-remote failed for {remote}/{PROBE_DATA_BRANCH}: "
            f"{(show.stderr or show.stdout).strip()}"
        )
    return PROBE_DATA_BRANCH in (show.stdout or "")


def materialize_probe_state(
    repo_dir: Path,
    dest: Path,
    *,
    bootstrap: Path,
    remote: str = "origin",
) -> None:
    """Load state from probe-data branch (shallow) or seed from bootstrap when branch absent."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    branch_on_remote = _remote_has_probe_branch(repo_dir, remote)
    if branch_on_remote:
        fetched = _run(
            ["git", "fetch", "--depth", FETCH_DEPTH, remote, PROBE_DATA_BRANCH],
            cwd=repo_dir,
            check=False,
        )
        if fetched.returncode != 0:
            raise SystemExit(
                f"probe-data exists on {remote} but fetch failed: "
                f"{(fetched.stderr or fetched.stdout).strip()}"
            )
        show = _run(
            ["git", "show", f"{remote}/{PROBE_DATA_BRANCH}:{STATE_REL.as_posix()}"],
            cwd=repo_dir,
            check=False,
        )
        if show.returncode != 0 or not show.stdout.strip():
            raise SystemExit(
                f"probe-data branch on {remote} is missing {STATE_REL.as_posix()} or it is empty"
            )
        dest.write_text(show.stdout, encoding="utf-8")
        return
    if not bootstrap.is_file():
        raise SystemExit(f"probe bootstrap missing: {bootstrap}")
    dest.write_bytes(bootstrap.read_bytes())


def push_probe_state(repo_dir: Path, state_file: Path, *, remote: str = "origin") -> None:
    """Replace probe-data with one orphan commit (no unbounded history)."""
    if not state_file.is_file():
        raise SystemExit(f"missing state file: {state_file}")
    repo_dir = repo_dir.resolve()
    worktree = repo_dir.parent / f".probe-data-wt-{os.getpid()}"
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
    try:
        _run(["git", "worktree", "prune"], cwd=repo_dir, check=False)
        _run(["git", "branch", "-D", PROBE_DATA_BRANCH], cwd=repo_dir, check=False)
        _run(
            ["git", "worktree", "add", "-b", PROBE_DATA_BRANCH, "--orphan", str(worktree)],
            cwd=repo_dir,
        )
        for child in worktree.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        (worktree / "data").mkdir(parents=True, exist_ok=True)
        shutil.copy2(state_file, worktree / STATE_REL)
        bot = [
            "-c",
            "user.name=github-actions[bot]",
            "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        ]
        _run(["git", *bot, "add", STATE_REL.as_posix()], cwd=worktree)
        diff = _run(["git", "diff", "--staged", "--quiet"], cwd=worktree, check=False)
        if diff.returncode == 0:
            return
        _run(["git", *bot, "commit", "-m", "chore(status): probe state"], cwd=worktree)
        pushed = _run(
            ["git", "push", "--force", remote, f"HEAD:{PROBE_DATA_BRANCH}"],
            cwd=worktree,
            check=False,
        )
        if pushed.returncode != 0:
            detail = (pushed.stderr or pushed.stdout or "git push --force failed").strip()
            raise SystemExit(detail)
    finally:
        _run(["git", "worktree", "remove", "--force", str(worktree)], cwd=repo_dir, check=False)
        shutil.rmtree(worktree, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", type=Path, default=Path("."))
    parser.add_argument("--bootstrap", type=Path, help="Seed when probe-data branch has no state")
    parser.add_argument("--dest", type=Path, help="Write fetched or seeded state here")
    parser.add_argument("--state", type=Path, help="State file to push to probe-data")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    repo = args.repo_dir.resolve()
    if args.dest and args.bootstrap:
        materialize_probe_state(repo, args.dest.resolve(), bootstrap=args.bootstrap.resolve())
        return 0
    if args.push and args.state:
        push_probe_state(repo, args.state.resolve())
        return 0
    parser.error("specify --dest with --bootstrap, or --push with --state")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
