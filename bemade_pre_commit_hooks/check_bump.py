"""Check that every changed Odoo module bumped its ``__manifest__.py`` version.

Read-only — it never modifies files. Two modes:

* **pre-commit (default):** the staged change vs ``HEAD`` (``git diff --cached``).
  A module is "changed" if any staged file lives under it, and its staged
  manifest version must be a strict increase over HEAD's. The check **computes
  its own diff** and ignores any filenames passed on argv — the hook is wired
  ``pass_filenames: false`` precisely so that ``pre-commit run --all-files``
  (which the OCA suite uses) doesn't hand it every file and make every module
  look "changed". With nothing staged it is a harmless no-op.
* **CI (``--against <ref>``):** the whole branch vs a base ref (e.g.
  ``origin/19.0``). Changed files come from ``git diff --name-only <ref>...HEAD``
  and the HEAD manifest version must beat the version on ``<ref>``. A module
  whose tree is identical at ``<ref>`` and ``HEAD`` is skipped: with
  criss-cross merges the merge base can predate a change both sides carry.

A brand-new module (no manifest at the comparison ref) is exempt — its initial
version stands.

Paths under ``vendored/`` are exempt by default. Vendored addons are upstream
code materialized from a lockfile (``addons.lock``): their versions belong to
upstream, and re-pinning one to a newer upstream commit routinely changes its
files while its version stays put. Demanding a bump there is unsatisfiable —
editing the version would put ``vendored/`` out of sync with the lockfile and
fail ``odoo-dev vendor check``, which is the real gate on those paths. Override
with ``--exclude`` (repeatable; supplying any replaces the default).

**Documentation-only changes need no bump.** A bump follows a change in runtime
behaviour; a README, a ``TODO.md``, an OCA ``readme/`` fragment or the rendered
``static/description/index.html`` cannot change behaviour, so a module whose
only changed files are prose is not "changed". The exempt set is deliberately
narrow (``*.md``, ``*.rst``, ``readme/``, ``doc/``, ``static/description/``):
``.txt`` can be a test fixture, and ``i18n/*.po`` or ``data/*.xml`` only load
on a module *update* — which is precisely what the bump triggers. Disable with
``--no-doc-exempt``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from ._manifest import find_module_root, is_increase, manifest_path, read_version

#: Path prefixes skipped unless ``--exclude`` overrides them. See module docstring.
DEFAULT_EXCLUDES = ("vendored",)

#: Prose that cannot change runtime behaviour, relative to the module root.
#: See the module docstring for what is deliberately NOT here.
DOC_SUFFIXES = (".md", ".rst")
DOC_DIRS = (("readme",), ("doc",), ("static", "description"))


def _is_doc(path: Path, module_root: Path) -> bool:
    """True if ``path`` is documentation within ``module_root``."""
    if path.suffix.lower() in DOC_SUFFIXES:
        return True
    rel = path.relative_to(module_root).parts
    return any(rel[: len(d)] == d for d in DOC_DIRS)


def _is_excluded(path: Path, excludes) -> bool:
    """True if ``path`` sits under any of the ``excludes`` directory prefixes.

    Matches whole path segments, so ``vendored`` does not swallow
    ``vendored_extra/``.
    """
    parts = path.parts
    for prefix in excludes:
        want = tuple(p for p in Path(prefix).parts if p not in ("", "."))
        if want and parts[: len(want)] == want:
            return True
    return False


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


def _changed_files(against: Optional[str]) -> List[str]:
    """Files changed in the relevant diff — always computed here, never taken
    from argv (so ``--all-files`` can't make every file look "changed")."""
    if against:
        revspec = f"{against}...HEAD"
        cmd = ["git", "diff", "--name-only", revspec]
    else:
        cmd = ["git", "diff", "--cached", "--name-only"]  # staged vs HEAD
    out = subprocess.run(cmd, capture_output=True, check=True, text=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def _same_tree(ref: str, root) -> bool:
    """True if ``root`` is byte-identical at ``ref`` and ``HEAD``."""
    return subprocess.run(
        ["git", "diff", "--quiet", ref, "HEAD", "--", str(root)],
        capture_output=True,
    ).returncode == 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "files",
        nargs="*",
        help="accepted for pre-commit compatibility but IGNORED — the diff is "
        "always computed internally (see module docstring)",
    )
    ap.add_argument(
        "--against",
        metavar="REF",
        help="base ref to diff against (CI mode), e.g. origin/19.0",
    )
    ap.add_argument(
        "--no-doc-exempt",
        action="store_true",
        help="require a bump even when a module's only changed files are "
        "documentation (*.md, *.rst, readme/, doc/, static/description/)",
    )
    ap.add_argument(
        "--exclude",
        metavar="PREFIX",
        action="append",
        default=[],
        help="directory prefix to skip, repeatable. Defaults to "
        f"{'/, '.join(DEFAULT_EXCLUDES)}/; supplying any replaces the default.",
    )
    args = ap.parse_args(argv)
    excludes = args.exclude or list(DEFAULT_EXCLUDES)

    changed = _changed_files(args.against)

    modules: dict = {}
    for f in changed:
        path = Path(f)
        if _is_excluded(path, excludes):
            continue
        root = find_module_root(path)
        if root is None:
            continue
        if not args.no_doc_exempt and _is_doc(path, root):
            continue
        mf = manifest_path(root)
        if mf is not None:
            modules[root] = mf

    if args.against:
        # A module identical on the target and HEAD has nothing to bump, even
        # when ``<ref>...HEAD`` lists it: with criss-cross merges (a feature
        # branch cut from production, merged into staging) the merge base can
        # predate a change both branches already carry.
        modules = {
            root: mf for root, mf in modules.items()
            if not _same_tree(args.against, root)
        }

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
