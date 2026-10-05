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
    _git(tmp_path, "init", "-q", "-b", "main")
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


# --- documentation-only changes under a module need no bump -----------------
#
# The rule everywhere (odoo-project-guide §7, the client repos' CLAUDE.md) is
# that a bump follows a change in runtime behaviour. A README, a TODO.md or an
# OCA readme/ fragment cannot change behaviour, so demanding a bump there is
# noise -- and on a merge commit that pulls in other people's doc edits it is a
# false positive that has to be SKIPped, which trains people to skip the hook.


@pytest.mark.parametrize(
    "doc",
    [
        "README.md",
        "TODO.md",
        "AGENTS.md",
        "README.rst",
        "readme/DESCRIPTION.md",
        "doc/index.rst",
        "static/description/index.html",
    ],
)
def test_docs_only_change_needs_no_bump(repo, doc):
    path = repo / "mymod" / doc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("prose\n")
    _git(repo, "add", "-A")
    assert main([]) == 0


def test_docs_plus_code_change_still_needs_bump(repo):
    (repo / "mymod" / "README.md").write_text("prose\n")
    (repo / "mymod" / "models.py").write_text("x = 2\n")
    _git(repo, "add", "-A")
    assert main([]) == 1


@pytest.mark.parametrize("path", ["tests/fixture.txt", "i18n/fr.po", "data/x.xml"])
def test_non_prose_files_under_a_module_still_need_bump(repo, path):
    # .txt can be a fixture; translations and data only load on a module
    # update, which is exactly what the bump triggers.
    p = repo / "mymod" / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("content\n")
    _git(repo, "add", "-A")
    assert main([]) == 1


def test_docs_only_exempt_in_against_mode(repo):
    _git(repo, "checkout", "-qb", "feature")
    (repo / "mymod" / "TODO.md").write_text("- [ ] later\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs")
    assert main(["--against", "main"]) == 0


def test_no_doc_exempt_flag_restores_strict_behaviour(repo):
    (repo / "mymod" / "README.md").write_text("prose\n")
    _git(repo, "add", "-A")
    assert main(["--no-doc-exempt"]) == 1


def _commit_mymod_bump(repo, msg):
    (repo / "mymod" / "models.py").write_text("x = 2\n")
    (repo / "mymod" / "__manifest__.py").write_text(
        "{'name': 'My', 'version': '1.0.1'}\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)


def _diverged_target(repo):
    """``staging`` and ``main`` both carry the same mymod bump, landed through
    different commits, so their merge base predates it. A branch cut from
    ``main`` then sees mymod in ``staging...HEAD`` without changing it."""
    _git(repo, "branch", "staging")
    _commit_mymod_bump(repo, "bump on main")
    _git(repo, "checkout", "-q", "staging")
    _commit_mymod_bump(repo, "same bump on staging")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-qb", "feature")


def test_module_identical_to_target_is_not_changed(repo):
    """The stale-merge-base false positive: nothing to bump on the target."""
    _diverged_target(repo)
    (repo / "other").mkdir()
    (repo / "other" / "__manifest__.py").write_text("{'version': '1.0.0'}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "unrelated new module")
    assert main(["--against", "staging"]) == 0


def test_module_differing_from_target_still_needs_bump(repo):
    """The guard only skips identical trees: a real change is still checked."""
    _diverged_target(repo)
    (repo / "mymod" / "models.py").write_text("x = 3\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "real change, no bump")
    assert main(["--against", "staging"]) == 1
