"""Stage static status.hydracept.com assets for GitHub Pages."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLIC = ROOT / "apps" / "status" / "public"
STATIC_BASENAMES = (
    "index.html",
    "app.js",
    "styles.css",
    "status_display.mjs",
    "status_copy.mjs",
    "CNAME",
    "incidents.json",
    "hydracept-mark.png",
    "favicon.ico",
    "favicon-32.png",
)


def build(
    out_dir: Path,
    *,
    state_file: Path | None = None,
    public_dir: Path | None = None,
) -> list[Path]:
    src_root = public_dir or Path(os.environ.get("HYDRACEPT_STATUS_PUBLIC_DIR", DEFAULT_PUBLIC))
    if not src_root.is_dir():
        raise SystemExit(f"missing status public dir: {src_root}")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in STATIC_BASENAMES:
        src = src_root / name
        if not src.is_file():
            continue
        dest = out_dir / name
        shutil.copy2(src, dest)
        written.append(dest)
    for src in sorted(src_root.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(src_root)
        if rel.parts[0] == "tests" or rel.name in STATIC_BASENAMES:
            continue
        if rel.name == "status.json":
            continue
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        written.append(dest)
    if state_file is not None:
        if not state_file.is_file():
            raise SystemExit(f"probe state file missing: {state_file}")
        dest = out_dir / "status.json"
        shutil.copy2(state_file, dest)
        written.append(dest)
        index_src = src_root / "index.html"
        if index_src.is_file():
            import sys

            scripts_dir = Path(__file__).resolve().parent
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from status_page_static_fallback import inject_from_status_file

            out_index = out_dir / "index.html"
            out_index.write_text(
                inject_from_status_file(index_src, state_file),
                encoding="utf-8",
            )
            if out_index not in written:
                written.append(out_index)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("_site"))
    parser.add_argument("--state", type=Path, help="Probe state JSON copied to status.json")
    parser.add_argument("--public-dir", type=Path, help="Override static source directory")
    args = parser.parse_args()
    paths = build(args.out, state_file=args.state, public_dir=args.public_dir)
    print(f"Wrote {len(paths)} file(s) under {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
