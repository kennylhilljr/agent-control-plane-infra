# Agent guide

This repository holds the migration plan and a small standard-library Python CLI for an ECC + OpenClaw agent platform. The CLI has two subcommands: `inventory` writes a sanitized report of local tools, providers and repositories, and `backup` creates and verifies an OpenClaw state checkpoint. Runtime orchestration lives in a separate repository, `openclaw-ecc-orchestrator`.

Before changing anything, read `MIGRATION_SPEC.md` (target design and section 6 safety invariants), `TODO.md` (the status ledger) and `USER_ACTIONS.md` (decisions reserved for the operator). `HANDOFF_TO_CLAUDE.md` has the latest handoff notes; its absolute paths refer to the operator's machine.

## Layout

- `bin/agent-platform` is a POSIX shell wrapper that puts `src/` on `PYTHONPATH` and runs `python3 -m agent_platform.cli`.
- `src/agent_platform/cli.py` parses arguments and prints the JSON result envelope.
- `src/agent_platform/inventory.py` holds `InventoryCollector` and the `redact` function.
- `src/agent_platform/backup.py` holds `BackupManager`.
- `tests/` has `unittest` test cases for inventory and backup.
- `inventories/` stores sanitized evidence JSON that is committed to Git.

## Setup

Nothing to install. `pyproject.toml` requires Python 3.11.4 or newer, because the backup restore check calls `tarfile` with `filter="data"`. There are no third-party runtime dependencies.

```bash
python3 --version
./bin/agent-platform --help
```

## Tests and checks

Run from the repository root:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tests are standard library `unittest` cases, so the command above needs no packages. pytest also runs them, using the settings in `pyproject.toml`, once the optional `test` extra is installed (`python3 -m pip install -e ".[test]"`). `__pycache__/` and `*.pyc` are ignored by Git.

No formatter, linter or type checker is configured in `pyproject.toml`. The handoff notes ask for a secret scan before reporting progress:

```bash
gitleaks dir . --no-banner --redact --exit-code 1
```

## Code conventions

- Modules start with `from __future__ import annotations` and use type hints.
- Results are frozen dataclasses (`BackupResult`, `CommandResult`).
- Subprocesses run through `run_command` with argument tuples and a timeout. Never build shell command strings.
- `InventoryCollector` takes `locate`, `run` and `home` arguments so tests can use fakes. Tests must not touch the real home directory, real OpenClaw state or the network; use `tempfile` directories and fake runners as the existing tests do.
- Inventory output passes through `redact`. A new collector must return the smallest useful metadata and come with a redaction test.
- JSON is written with `indent=2` and `sort_keys=True`.
- Add regression tests for new inventory fields, redaction cases, archive validation and filesystem behavior.

## Safety rules

- Never print, log, commit or copy credential values. Provider detection records only `credential_configured` booleans.
- Do not commit `.env` files, backups, OpenClaw state, transcripts or worktrees. Check `.gitignore` before adding new output paths.
- Do not run `backup` against the real `~/.openclaw` or run `inventory` against the real machine unless the operator asks. With no `--output`, `inventory` overwrites the tracked `inventories/latest.json`.
- Use `backup --dry-run` before any real backup. Do not add restores, upgrades or cleanup that delete data; every mutation needs a dry run or preflight and a rollback path.
- Treat the legacy Agent-Engineers repository as read-only.
- Do not guess Kimi credentials, operator identities, approval roles, OpenRouter source-code policy or remote-access topology.
- Do not commit, push or merge unless the operator asks.
- Keep `TODO.md` current when work changes migration status.
