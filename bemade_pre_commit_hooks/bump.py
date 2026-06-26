"""``bemade-bump-version <level> <module-dir>...`` — bump an Odoo module's
manifest version. *level* is one of patch | minor | major.

Edits ``__manifest__.py`` in place and (unless ``--no-stage``) ``git add``s it,
so the bump lands in the commit you're about to make. This is the manual
applier the check enforces; ``odoo-dev bump`` wraps it with module-name
resolution.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ._manifest import (
    bump_version_string,
    find_module_root,
    manifest_path,
    read_version,
    set_version,
)


def _resolve_manifest(module: str) -> Path:
    p = Path(module)
    root = find_module_root(p) if p.exists() else None
    if root is None and p.is_dir():
        root = p
    if root is None:
        raise SystemExit(f"  ✗ no Odoo module found at {module!r}")
    mf = manifest_path(root)
    if mf is None:
        raise SystemExit(f"  ✗ no __manifest__.py in {root}")
    return mf


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("level", choices=["patch", "minor", "major"])
    ap.add_argument("modules", nargs="+", help="module directory(ies) to bump")
    ap.add_argument(
        "--no-stage", action="store_true", help="do not git add the changed manifest"
    )
    args = ap.parse_args(argv)

    for module in args.modules:
        mf = _resolve_manifest(module)
        text = mf.read_text()
        current = read_version(text)
        if current is None:
            raise SystemExit(f"  ✗ no version string in {mf}")
        new_version = bump_version_string(current, args.level)
        mf.write_text(set_version(text, new_version))
        print(f"  ✓ {mf.parent.name}: {current} -> {new_version}")
        if not args.no_stage:
            subprocess.run(["git", "add", str(mf)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
