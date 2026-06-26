# bemade/pre-commit-hooks

Shared [pre-commit](https://pre-commit.com) and CI hooks for Bemade's Odoo
repositories. Today it ships one rule: **every change to a module must bump that
module's `__manifest__.py` version.**

## Why

On odoo.sh the manifest `version` is what *triggers* a module upgrade on deploy —
push code without bumping the version and your change silently does not apply.
On our GitLab/k8s repos the deploy finalizer drives upgrades itself, but we keep
the same rule everywhere for uniformity and so the version is a reliable "this
changed" signal. The hook **only checks** — it never edits files or reads the
commit message. You choose the bump level (patch / minor / major) yourself,
guided by semver: fix → patch, feature → minor, breaking → major.

## What it does

`check-manifest-version-bump` blocks a commit when a module has staged changes
but its `__manifest__.py` version is not a strict increase over `HEAD`. The same
tool runs in CI against the target branch to catch anything that slipped past
the local hook (e.g. `git commit -n`).

## Use it (local pre-commit)

In a project repo's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/bemade/pre-commit-hooks
    rev: v0.1.0
    hooks:
      - id: check-manifest-version-bump
```

Then `pre-commit install`. (`odoo-dev setup` wires both up for you.)

## Use it (CI backstop)

Diff the merge request against its target branch:

```bash
pip install bemade-pre-commit-hooks   # or: pipx run --spec ...
bemade-check-version-bump --against origin/19.0
```

Exit code 1 (with the offending modules listed) fails the job. Works the same in
GitLab CI and GitHub Actions — it only needs the target branch fetched.

## Bump a version

```bash
bemade-bump-version <patch|minor|major> path/to/module [more/modules ...]
```

Edits the manifest in place and stages it. `odoo-dev bump <module> <level>`
wraps this with module-name resolution.

## Versioning convention

The version is treated **series-agnostically** — only the trailing
`major.minor.patch` segments move, never the Odoo series prefix:

| version       | patch         | minor         | major         |
|---------------|---------------|---------------|---------------|
| `19.0.1.2.3`  | `19.0.1.2.4`  | `19.0.1.3.0`  | `19.0.2.0.0`  |
| `1.2.3`       | `1.2.4`       | `1.3.0`       | `2.0.0`       |

A minor/major bump requires at least three segments so the series prefix is
never touched.

## License

LGPL-3.0-or-later · Bemade Inc.
