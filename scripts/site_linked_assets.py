"""Collect content-hashed /assets/* URLs linked from marketing HTML shells."""

from __future__ import annotations

import re
from pathlib import Path

_ASSET_ATTR_RE = re.compile(
    r"""(?:src|href)\s*=\s*["'](?P<path>/assets/[^"'?#]+)["']""",
    re.IGNORECASE,
)


def linked_asset_paths(html: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _ASSET_ATTR_RE.finditer(html):
        path = match.group("path").strip()
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def collect_dist_linked_assets(dist_dir: Path) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for name in ("index.html", "404.html"):
        page = dist_dir / name
        if not page.is_file():
            continue
        for path in linked_asset_paths(page.read_text(encoding="utf-8", errors="replace")):
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return paths
