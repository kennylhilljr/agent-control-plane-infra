# CI

`scripts/check.sh` is the single check command for this repository. It runs the unit tests, a shell syntax check and shellcheck on the shell scripts, JSON validation of `inventories/latest.json` when that file is present, and a gitleaks secret scan. Local runs and CI call the same script, so a green local check should mean a green CI run.

`scripts/check.sh` and `githooks/` come from #23, and the workflow below should only be installed in `.github/workflows/` after #23 has merged.

The pre-push hook is opt-in. Enable it in a clone with:

```sh
git config core.hooksPath githooks
```

Bots cannot write under `.github/workflows/`, so the operator copies the YAML below to `.github/workflows/check.yml` by hand. The workflow pins gitleaks to v8.21.2 and checks the archive's SHA-256 before extracting it.

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
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
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
- 80% diff coverage on lines added or modified by a pull request
- non-decreasing full-suite coverage
- formatter, lint, and type checking
- schema validation for handoffs, task files, and inventory output
- dry-run no-mutation tests that prove a dry run leaves state untouched
- adversarial tests under `tests/adversarial/`
- secret scanning of CI logs and artifacts
