# CI

`scripts/check.sh` is the single check command for this repository. It runs the unit tests, then a coverage report with `fail_under = 80` from `pyproject.toml`, a ruff lint (`python3 -m ruff check .`) and a strict mypy type check of `src/` and `scripts/` (`python3 -m mypy`), then a `sh -n` syntax check on the shell scripts. The coverage, ruff and mypy stages use the modules installed for the same `python3` (`python3 -m pip install -e ".[dev]"`). A missing module fails the check, like a missing gitleaks, unless `ALLOW_NO_DEV_TOOLS=1` is set; then the stage prints, for example, "ruff not installed; skipped by ALLOW_NO_DEV_TOOLS=1" and continues. When coverage is installed the unit tests run under it, and the tests' subprocesses are measured too. ShellCheck also runs when `shellcheck` is installed; without it the script prints "shellcheck not installed; skipping" and continues, so install ShellCheck to get that check locally. Next it runs the inventory validator `scripts/check_inventories.py` only when that script exists, and skips the step otherwise. Last comes a gitleaks secret scan, which fails when gitleaks is missing unless `ALLOW_NO_GITLEAKS=1` is set. Local runs and CI call the same script, so a green local check should mean a green CI run.

The pre-push hook is opt-in. Enable it in a clone with:

```sh
git config core.hooksPath githooks
```

`.github/dependabot.yml` asks Dependabot for weekly update PRs for the pinned GitHub Actions and for the pip extras in `pyproject.toml`.

## Workflow

`.github/workflows/check.yml` runs `sh scripts/check.sh` on every push to `main` and every pull request against `main`, on Ubuntu with Python 3.11 and 3.13. It installs the dev tools with `python -m pip install -e ".[dev]"` so the coverage, lint and type stages run instead of failing on a missing module. The workflow token is read-only (`permissions: contents: read`), checkout does not keep the token in the clone (`persist-credentials: false`), and each action is pinned to a full commit SHA with the release tag in a comment. The workflow downloads gitleaks v8.21.2, checks the archive's SHA-256 before extracting it, and deletes the archive before the scan. `tests/test_docs_ci.py` checks these properties, so a change to the workflow that drops one fails the unit tests.

To bump an action, resolve the new tag to its commit (`gh api repos/actions/checkout/git/ref/tags/v4.4.0 --jq .object.sha`; for an annotated tag, follow `.object.url` to the commit) and update both the SHA and the comment.

The job is named `check` in each matrix leg (`check (3.11)` and `check (3.13)`). Making those required status checks on `main` is a branch protection setting the operator changes in the repository settings.

## Later gates

This issue defers the following gates from MIGRATION_SPEC section 12. Each one needs its own change once the tooling is chosen.

- dependency vulnerability scanning
- SBOM generation
- 80% diff coverage on lines added or modified by a pull request (the full suite already has an 80% floor)
- non-decreasing full-suite coverage
- formatter (lint and type checking now run in `scripts/check.sh`)
- schema validation for handoffs, task files, and inventory output
- dry-run no-mutation tests that prove a dry run leaves state untouched
- adversarial tests under `tests/adversarial/`
- secret scanning of CI logs and artifacts
