"""Integration tests for check_bump.main() against a real temp git repo.

The load-bearing one is test_all_files_with_nothing_staged_is_noop: it proves the
hook is safe under `pre-commit run --all-files` (the OCA suite's invocation),
which passes every file but stages nothing.
"""

import subprocess

import pytest

from bemade_pre_commit_hooks.check_bump import main


def _git(repo, *args):
    subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    mod = tmp_path / "mymod"
    mod.mkdir()
    (mod / "__manifest__.py").write_text("{'name': 'My', 'version': '1.0.0'}\n")
    (mod / "models.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_staged_change_without_bump_fails(repo):
    (repo / "mymod" / "models.py").write_text("x = 2\n")
    _git(repo, "add", "mymod/models.py")
    assert main([]) == 1


def test_staged_change_with_bump_passes(repo):
    (repo / "mymod" / "models.py").write_text("x = 2\n")
    (repo / "mymod" / "__manifest__.py").write_text(
        "{'name': 'My', 'version': '1.0.1'}\n"
    )
    _git(repo, "add", "-A")
    assert main([]) == 0


def test_all_files_with_nothing_staged_is_noop(repo):
    # `pre-commit run --all-files` hands the hook every file but stages nothing;
    # argv is ignored and the staged diff is empty -> no module flagged.
    all_files = ["mymod/__manifest__.py", "mymod/models.py"]
    assert main(all_files) == 0
    assert main([]) == 0


def test_argv_is_ignored_only_staged_matters(repo):
    (repo / "mymod" / "models.py").write_text("x = 3\n")
    _git(repo, "add", "mymod/models.py")  # staged change, no bump
    # passing all files OR none: same verdict, driven only by the staged diff.
    assert main(["mymod/__manifest__.py", "mymod/models.py"]) == 1
    assert main([]) == 1


def _add_vendored_module(repo, path="vendored/upstream_mod"):
    """Commit a module at ``path`` so later edits are 'changed, not new'."""
    mod = repo / path
    mod.mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'Up', 'version': '19.0.1.0.0'}\n")
    (mod / "models.py").write_text("y = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "vendor")
    return mod


def test_vendored_change_without_bump_is_exempt(repo):
    """A re-pin rewrites vendored files while upstream's version stays put.

    Demanding a bump there is unsatisfiable: editing the version desyncs
    vendored/ from addons.lock and fails `odoo-dev vendor check`.
    """
    mod = _add_vendored_module(repo)
    (mod / "models.py").write_text("y = 2\n")
    _git(repo, "add", "-A")
    assert main([]) == 0


def test_vendored_exemption_does_not_cover_sibling_prefix(repo):
    """`vendored` must match a whole segment, not swallow `vendored_extra/`."""
    mod = _add_vendored_module(repo, "vendored_extra/mod")
    (mod / "models.py").write_text("y = 2\n")
    _git(repo, "add", "-A")
    assert main([]) == 1


def test_non_vendored_module_still_checked_alongside_vendored(repo):
    """An exempt path must not mask a real failure in the same commit."""
    mod = _add_vendored_module(repo)
    (mod / "models.py").write_text("y = 2\n")
    (repo / "mymod" / "models.py").write_text("x = 9\n")
    _git(repo, "add", "-A")
    assert main([]) == 1


def test_explicit_exclude_replaces_the_default(repo):
    """Supplying --exclude replaces the default, so vendored/ is checked again."""
    mod = _add_vendored_module(repo)
    (mod / "models.py").write_text("y = 2\n")
    _git(repo, "add", "-A")
    assert main(["--exclude", "thirdparty"]) == 1
    assert main(["--exclude", "vendored"]) == 0
