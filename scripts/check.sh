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

echo "==> unit tests"
# Skip .pyc files: a test edited within the same second at the same size
# would otherwise run from stale bytecode.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests || fail "unit tests"

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
