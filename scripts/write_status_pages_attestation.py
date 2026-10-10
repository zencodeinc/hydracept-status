"""Write Pages domain attestation in the public hydracept-status repo (same-repo Pages API)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from status_pages_domain_gate import (  # noqa: E402
    ATTESTATION_PATH,
    build_attestation_document,
    fetch_latest_github_pages_deployment,
    fetch_pages_for_repo,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(ATTESTATION_PATH),
        help="Attestation JSON path (committed on main in public repo)",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", "").strip(),
        help="owner/repo (defaults to GITHUB_REPOSITORY in Actions)",
    )
    args = parser.parse_args()
    repo = args.repo
    if not repo or "/" not in repo:
        raise SystemExit("Set --repo or GITHUB_REPOSITORY (public hydracept-status Actions job)")
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    pages = fetch_pages_for_repo(repo, token=token)
    pages_deployment = fetch_latest_github_pages_deployment(repo, token=token)
    doc = build_attestation_document(pages, repo=repo, pages_deployment=pages_deployment)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote attestation to {args.out} (protected_domain_state=verified, cname={doc['pages']['cname']!r})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
