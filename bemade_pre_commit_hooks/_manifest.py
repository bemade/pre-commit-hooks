"""Shared helpers for locating Odoo modules and reading / bumping the version
string in their ``__manifest__.py``.

The version is treated **series-agnostically**: we only ever touch the trailing
``major.minor.patch`` segments and never the Odoo series prefix (e.g. the
``19.0`` in ``19.0.1.2.3``). The rule is:

* patch -> increment the **last** segment
* minor -> increment the **second-to-last** segment, zero everything after
* major -> increment the **third-to-last** segment, zero everything after

That works for both the full Odoo form (``19.0.1.0.0``) and the short form
(``1.0.0``) without the hook needing to know which Odoo series the repo is on.
A minor/major bump requires at least 3 segments so the series prefix is safe.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional

MANIFEST_NAMES = ("__manifest__.py", "__openerp__.py")
VERSION_RE = re.compile(
    r"""(?P<prefix>["']version["']\s*:\s*)(?P<q>["'])(?P<ver>[^"']*)(?P=q)"""
)
_LEVEL_INDEX = {"patch": -1, "minor": -2, "major": -3}


def find_module_root(path: Path) -> Optional[Path]:
    """Walk up from *path* until a directory containing a manifest is found."""
    for parent in [path, *path.parents]:
        if parent.is_dir() and any((parent / m).is_file() for m in MANIFEST_NAMES):
            return parent
    return None


def manifest_path(module_root: Path) -> Optional[Path]:
    for name in MANIFEST_NAMES:
        p = module_root / name
        if p.is_file():
            return p
    return None


def read_version(manifest_text: str) -> Optional[str]:
    m = VERSION_RE.search(manifest_text)
    if m:
        return m.group("ver")
    # Fall back to a full literal-eval if the regex misses an exotic layout.
    try:
        data = ast.literal_eval(manifest_text.strip())
        if isinstance(data, dict) and isinstance(data.get("version"), str):
            return data["version"]
    except Exception:
        pass
    return None


def bump_version_string(version: str, level: str) -> str:
    """Return *version* with the requested *level* incremented.

    Raises ValueError if the version cannot be bumped safely (unknown level,
    non-numeric target segment, or too few segments for a minor/major bump).
    """
    idx = _LEVEL_INDEX.get(level)
    if idx is None:
        raise ValueError(f"unknown bump level {level!r} (patch|minor|major)")
    parts = version.split(".")
    if len(parts) < -idx:
        raise ValueError(
            f"version {version!r} has too few segments for a {level} bump"
        )
    if level in ("minor", "major") and len(parts) < 3:
        raise ValueError(
            f"refusing a {level} bump on {version!r}: need >=3 segments so the "
            f"series prefix is never touched"
        )
    try:
        parts[idx] = str(int(parts[idx]) + 1)
    except ValueError as exc:  # non-numeric segment
        raise ValueError(f"non-numeric segment in version {version!r}") from exc
    for i in range(idx + 1, 0):  # zero everything after the bumped segment
        parts[i] = "0"
    return ".".join(parts)


def set_version(manifest_text: str, new_version: str) -> str:
    """Return *manifest_text* with its version literal replaced by *new_version*,
    preserving the original quote style."""

    def _sub(m: re.Match) -> str:
        return f"{m.group('prefix')}{m.group('q')}{new_version}{m.group('q')}"

    return VERSION_RE.sub(_sub, manifest_text, count=1)


def version_tuple(v: str) -> Optional[tuple]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return None


def is_increase(old: str, new: str) -> bool:
    """True if *new* is a strict version increase over *old*. Falls back to
    plain inequality when either side has non-numeric segments."""
    ot, nt = version_tuple(old), version_tuple(new)
    if ot is not None and nt is not None:
        n = max(len(ot), len(nt))
        ot = ot + (0,) * (n - len(ot))
        nt = nt + (0,) * (n - len(nt))
        return nt > ot
    return new != old
