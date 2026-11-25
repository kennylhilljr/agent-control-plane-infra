# CI

`scripts/check.sh` is the single check command for this repository. It runs the unit tests, then a coverage report with `fail_under = 80` from `pyproject.toml`, a ruff lint (`python3 -m ruff check .`) and a strict mypy type check of `src/` and `scripts/` (`python3 -m mypy`), then a `sh -n` syntax check on the shell scripts. The coverage, ruff and mypy stages use the modules installed for the same `python3` (`python3 -m pip install -e ".[dev]"`). A missing module fails the check, like a missing gitleaks, unless `ALLOW_NO_DEV_TOOLS=1` is set; then the stage prints, for example, "ruff not installed; skipped by ALLOW_NO_DEV_TOOLS=1" and continues. When coverage is installed the unit tests run under it, and the tests' subprocesses are measured too. ShellCheck also runs when `shellcheck` is installed; without it the script prints "shellcheck not installed; skipping" and continues, so install ShellCheck to get that check locally. Next it runs the inventory validator `scripts/check_inventories.py` only when that script exists, and skips the step otherwise. Last comes a gitleaks secret scan, which fails when gitleaks is missing unless `ALLOW_NO_GITLEAKS=1` is set. Local runs and CI call the same script, so a green local check should mean a green CI run.

`scripts/check.sh` and `githooks/` come from #23, and the workflow below should only be installed in `.github/workflows/` after #23 has merged.

The pre-push hook is opt-in. Enable it in a clone with:

```sh
git config core.hooksPath githooks
```

Bots cannot write under `.github/workflows/`, so the operator copies the YAML below to `.github/workflows/check.yml` by hand. The workflow pins its actions to commit SHAs, pins gitleaks to v8.21.2 and checks the archive's SHA-256 before extracting it. `.github/dependabot.yml` asks Dependabot for weekly update PRs for the pinned GitHub Actions and for the pip extras in `pyproject.toml`.

```yaml
name: check

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  check:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.11', '3.13']
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
        with:
          persist-credentials: false
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install check tooling
        run: python -m pip install -e ".[dev]"
      - name: Install gitleaks
        run: |
          curl -fsSLo gitleaks_8.21.2_linux_x64.tar.gz https://github.com/gitleaks/gitleaks/releases/download/v8.21.2/gitleaks_8.21.2_linux_x64.tar.gz
          echo "5bc41815076e6ed6ef8fbecc9d9b75bcae31f39029ceb55da08086315316e3ba  gitleaks_8.21.2_linux_x64.tar.gz" > gitleaks.sha256
          sha256sum -c gitleaks.sha256
          mkdir -p "$RUNNER_TEMP/gitleaks"
          tar -xzf gitleaks_8.21.2_linux_x64.tar.gz -C "$RUNNER_TEMP/gitleaks"
          echo "$RUNNER_TEMP/gitleaks" >> "$GITHUB_PATH"
      - name: Run checks
        run: sh scripts/check.sh
```

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
