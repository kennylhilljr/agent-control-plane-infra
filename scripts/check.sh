#!/bin/sh
set -eu

# Run the local verification stages in order and stop at the first failure.

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH='' cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT"

fail() {
    echo "$1 failed" >&2
    exit 1
}

# The lint, type check and coverage stages use the ruff, mypy and coverage
# modules of the same python3 (install them with: pip install -e ".[dev]").
# A missing module fails its stage unless ALLOW_NO_DEV_TOOLS=1 is set, which
# skips it instead.
have_module() {
    python3 -c "import $1" >/dev/null 2>&1
}

missing_tool() {
    if [ "${ALLOW_NO_DEV_TOOLS:-}" = "1" ]; then
        echo "$1 not installed; skipped by ALLOW_NO_DEV_TOOLS=1"
        return 0
    fi
    echo "$2 failed: python3 cannot import $1; run python3 -m pip install -e \".[dev]\" or set ALLOW_NO_DEV_TOOLS=1 to skip" >&2
    exit 1
}

echo "==> unit tests"
# Skip .pyc files: a test edited within the same second at the same size
# would otherwise run from stale bytecode.
if have_module coverage; then
    python3 -m coverage erase || fail "unit tests"
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" python3 -m coverage run --parallel-mode -m unittest discover -s tests || fail "unit tests"
else
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s tests || fail "unit tests"
fi

echo "==> coverage"
if have_module coverage; then
    # Parallel data files from the test run and its subprocesses are merged
    # first. The threshold is fail_under in pyproject.toml.
    python3 -m coverage combine -q || fail "coverage"
    python3 -m coverage report || fail "coverage"
else
    missing_tool coverage coverage
fi

echo "==> lint"
if have_module ruff; then
    python3 -m ruff check . || fail "lint"
else
    missing_tool ruff lint
fi

echo "==> type check"
if have_module mypy; then
    python3 -m mypy || fail "type check"
else
    missing_tool mypy "type check"
fi

echo "==> shell syntax"
sh -n bin/agent-platform || fail "shell syntax"
for f in scripts/*.sh; do
    case "$f" in "scripts/*.sh") continue ;; esac
    sh -n "$f" || fail "shell syntax"
done
if command -v shellcheck >/dev/null 2>&1; then
    # The wrapper uses the intentional 'CDPATH= cd' idiom, which SC1007
    # flags as a possible typo.
    shellcheck --exclude=SC1007 bin/agent-platform || fail "shell syntax"
    for f in scripts/*.sh; do
        case "$f" in "scripts/*.sh") continue ;; esac
        shellcheck "$f" || fail "shell syntax"
    done
else
    echo "shellcheck not installed; skipping"
fi

echo "==> inventory validator"
if [ -f scripts/check_inventories.py ]; then
    python3 scripts/check_inventories.py || fail "inventory validator"
else
    echo "scripts/check_inventories.py not present; skipping"
fi

echo "==> secret scan"
if command -v gitleaks >/dev/null 2>&1; then
    gitleaks dir . --no-banner --redact --exit-code 1 || fail "secret scan"
elif [ "${ALLOW_NO_GITLEAKS:-}" = "1" ]; then
    echo "gitleaks not installed; skipped by ALLOW_NO_GITLEAKS=1"
else
    echo "secret scan failed: gitleaks is not installed; install it or set ALLOW_NO_GITLEAKS=1 to skip" >&2
    exit 1
fi
