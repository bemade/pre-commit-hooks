"""Check that every changed Odoo module bumped its ``__manifest__.py`` version.

Read-only — it never modifies files. Two modes:

* **pre-commit (default):** the staged change vs ``HEAD``. pre-commit passes the
  staged filenames as argv; a module is "changed" if any of them lives under it,
  and its staged manifest version must be a strict increase over HEAD's.
* **CI (``--against <ref>``):** the whole branch vs a base ref (e.g.
  ``origin/19.0``). Changed files come from ``git diff --name-only <ref>...HEAD``
  and the HEAD manifest version must beat the version on ``<ref>``.

A brand-new module (no manifest at the comparison ref) is exempt — its initial
version stands.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from ._manifest import find_module_root, is_increase, manifest_path, read_version


def _git_text(revspec: str) -> Optional[str]:
    """``git show <revspec>`` -> text, or None if the path is absent there."""
    try:
        return subprocess.run(
            ["git", "show", revspec],
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None


def _changed_files(against: Optional[str], argv_files: List[str]) -> List[str]:
    if against:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{against}...HEAD"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout
        return [line for line in out.splitlines() if line.strip()]
    if argv_files:
        return argv_files
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "files", nargs="*", help="changed files (pre-commit passes these)"
    )
    ap.add_argument(
        "--against",
        metavar="REF",
        help="base ref to diff against (CI mode), e.g. origin/19.0",
    )
    args = ap.parse_args(argv)

    changed = _changed_files(args.against, args.files)

    modules: dict = {}
    for f in changed:
        root = find_module_root(Path(f))
        if root is None:
            continue
        mf = manifest_path(root)
        if mf is not None:
            modules[root] = mf

    old_ref = args.against or "HEAD"
    failures = []
    for root, mf in sorted(modules.items()):
        rel = str(mf)
        old_text = _git_text(f"{old_ref}:{rel}")
        if old_text is None:
            continue  # new module at the comparison ref -> initial version stands

        if args.against:
            new_text = _git_text(f"HEAD:{rel}")
        else:
            new_text = _git_text(f":{rel}")  # the staged (index) version
            if new_text is None:
                try:
                    new_text = Path(rel).read_text()
                except OSError:
                    new_text = None
        if new_text is None:
            continue

        old_v = read_version(old_text)
        new_v = read_version(new_text)
        if old_v is None or new_v is None:
            failures.append((root, "could not read version", old_v, new_v))
        elif not is_increase(old_v, new_v):
            failures.append((root, "version not bumped", old_v, new_v))

    if failures:
        sys.stderr.write(
            "\n  ✗ module changed without a version bump\n\n"
            "  Bump each module's __manifest__.py version "
            "(`odoo-dev bump <module> <patch|minor|major>`\n"
            "  or `bemade-bump-version <level> <module-dir>`):\n\n"
        )
        for root, why, old_v, new_v in failures:
            sys.stderr.write(f"    - {root}: {why} (was {old_v!r}, now {new_v!r})\n")
        sys.stderr.write("\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
