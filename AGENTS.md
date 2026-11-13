# Agent guide

This repository holds the migration plan and a small standard-library Python CLI for an ECC + OpenClaw agent platform. The CLI has two subcommands: `inventory` writes a sanitized report of local tools, providers and repositories, and `backup` creates and verifies an OpenClaw state checkpoint. Runtime orchestration lives in a separate repository, `openclaw-ecc-orchestrator`.

Before changing code, the CLI, `MIGRATION_SPEC.md` or the safety rules below, read `MIGRATION_SPEC.md` (target design and section 6 safety invariants), `TODO.md` (the status ledger) and `USER_ACTIONS.md` (decisions reserved for the operator). Documentation-only changes (README text and diagrams, typo fixes, `docs/` prose, this file) need no such review: make the change, check it renders, and open the PR. `HANDOFF_TO_CLAUDE.md` has the latest handoff notes; its absolute paths refer to the operator's machine.

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

`scripts/check.sh` is the single check command. Run it before opening a PR; it changes to the repository root itself, so it works from any directory when given its path:

```bash
sh scripts/check.sh
```

It stops at the first failing stage: the unit tests, a `sh -n` syntax check of `bin/agent-platform` and `scripts/*.sh` (plus ShellCheck when it is installed), the inventory validator `scripts/check_inventories.py`, and a gitleaks secret scan. The scan fails when gitleaks is not installed unless `ALLOW_NO_GITLEAKS=1` is set. An opt-in pre-push hook runs the same script; enable it in a clone with `git config core.hooksPath githooks`. `docs/ci.md` describes the stages and has a copyable GitHub Actions workflow that calls the same script.

To run only the unit tests, from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

Each test module puts the repository `src/` directory on `sys.path` itself, so bare discovery and direct runs such as `python3 tests/test_inventory.py` work without a `PYTHONPATH` prefix (the older `PYTHONPATH=src` form still works). The tests are standard library `unittest` cases, so the command above needs no packages. `tests/test_tmpdirs.py` reruns the full suite in fresh subprocesses with `TMPDIR=/tmp` and with `TMPDIR` under a disposable home's `.openclaw/tmp`, so both temporary-directory setups are covered by the suite itself; it never touches real OpenClaw state. pytest also runs them, using the settings in `pyproject.toml`, once the optional `test` extra is installed (`python3 -m pip install -e ".[test]"`). `__pycache__/` and `*.pyc` are ignored by Git.

No formatter, linter or type checker is configured in `pyproject.toml`. The handoff notes ask for a secret scan before reporting progress; `scripts/check.sh` runs it, and it also runs on its own:

```bash
gitleaks dir . --no-banner --redact --exit-code 1
```

Check the committed evidence under `inventories/` (standard library only, read-only):

```bash
python3 scripts/check_inventories.py                            # every inventories/**/*.json
python3 scripts/check_inventories.py inventories/latest.json    # only the named files
```

With no arguments it checks every `inventories/**/*.json` in the repository; file arguments (relative to the working directory) limit it to those files, for example the changed ones. It fails a file that cannot be read, is not UTF-8 or is not strict JSON (`NaN`/`Infinity` constants and duplicate member names are rejected, so a credential cannot hide behind a later duplicate), that `redact` would change, or that holds a string value or member name shaped like a credential (`sk-` or `ghp_` keys that start at a token boundary, meaning the start of the string or a character that is not a letter or digit, and have at least 20 key characters, so `task-list` is not flagged; PEM private key blocks; `Bearer <value>`). It exits 0 when every file is clean and 1 otherwise, and prints a JSON array of `{"file", "pointer", "reason"}` objects, where `pointer` is an RFC 6901 JSON Pointer and `reason` is a fixed string. Values, exception text and file excerpts are never printed, and a file name, directory name or pointer component that looks like a credential is shown as `<redacted>`. `scripts/check.sh` runs it. If it flags committed evidence, report the file and pointer for operator review rather than editing the evidence.

This standalone checker, with its diagnostic array instead of the result envelope, is a deliberate exception to the single-command automation interface in `MIGRATION_SPEC.md` section 7: it is a read-only repository check, not an operational subcommand.

`redact` rules fail closed on key names: a key is lowercased, `_`, `-` and `.` are removed, and it is sensitive when the result contains `apikey`, `privatekey`, `token`, `secret`, `password`, `passphrase`, `cookie`, `bearer`, `credential` or `authorization` anywhere, so `PRIVATEKEYPRESENT` matches and so do `tokenizer`, `secretary` and `credentials`; `monkey` or `public_key_id` do not. Values under sensitive keys become `<redacted>`, with these metadata exceptions:

- keys ending in `_count` or `_tokens` (`plaintext_secret_count`, `input_tokens`) keep int and float values only; bools, strings and containers are redacted;
- keys ending in `_status`, `_configured` or `_present` (`credential_configured`) keep bool and null only;
- the one allowlisted string is `secrets_audit_status` = `clean`, exactly; other strings, case or whitespace variants and other key spellings are redacted;
- a compact name such as `PRIVATEKEYPRESENT` or `secretcount` uses the same suffixes when the part before the suffix is itself sensitive, so `maxtokens` stays redacted;
- any other sensitive key keeps bool values only. URL query parameters get no metadata exceptions.

## Code conventions

- Modules start with `from __future__ import annotations` and use type hints.
- Results are frozen dataclasses (`BackupResult`, `CommandResult`).
- Add regression tests for new inventory fields, redaction cases, archive validation and filesystem behavior.

## Review rules

Review bots read this file on every PR and treat a broken rule as a defect. Each rule below is true of the code on `main`; a change that breaks one must fix the code or update the rule in the same PR.

- Subprocesses in `src/agent_platform/` run through `run_command` in `inventory.py`, with an argument tuple and a timeout (5 seconds by default). Never build shell command strings or pass `shell=True`. Tests may call `subprocess.run` directly with an argument list or tuple; give every new call a timeout.
- Collectors take their dependencies as arguments: `InventoryCollector` takes `locate`, `run` and `home` (plus `repositories`), and tests pass fakes for them instead of searching the real `PATH` or running real tools. Provider detection reads `os.environ` directly and records only `credential_configured` booleans.
- Tests work in `tempfile` folders and never touch the real home folder, the real `~/.openclaw` or the network. A test that needs a home folder or a `TMPDIR` points `HOME` or `TMPDIR` at a temporary folder. Tests never write to `inventories/latest.json`; they may only read the committed evidence under `inventories/`, as the redaction stability and validator tests do.
- Inventory output passes through `redact`. A new collector returns the smallest useful metadata, and every new inventory field has a redaction test.
- With `--json`, every result of a completed `inventory` or `backup` run and every handled failure is built by `build_envelope` in `cli.py` and carries the envelope keys from `MIGRATION_SPEC.md` section 7: `ok`, `operation`, `changed`, `checks`, `warnings`, `required_user_actions` and `rollback_checkpoint`. Extra keys such as `archive`, `manifest`, `output` or `error` are added beside them. `backup` prints the envelope even without `--json`, and `inventory` without `--json` prints the inventory itself. The handled failures are `OSError`, `ValueError` and `SourceChangedDuringBackup`: each exits 1 with a one-line message from `safe_error_message` and no traceback or file contents: in the envelope's `error` key with `--json`, on stderr without it. Other exceptions propagate as a traceback on purpose (`test_unexpected_exceptions_propagate`), and argparse usage errors exit 2 with argparse's own text.
- Backups do not follow symlinks during traversal. The supplied source root itself is resolved first; inside it, a symlink is recorded in the manifest's `symlinks` map with its target and left out of the archive, and symlinked folders are not entered. The top-level `logs/` and `tmp/` folders are skipped, and a backup folder that overlaps the source is refused.
- `verify_archive` rejects absolute member names, names with a `..` part, and symlink, hard link and device members before it extracts anything, then restores into a new folder beside the archive (or under `restore_root` when given), removes that folder (best effort when verification fails) and compares checksums.
- JSON is written with `indent=2` and `sort_keys=True`: inventory files, backup manifests, CLI envelopes and the `scripts/check_inventories.py` findings.

## Safety rules

- Never print, log, commit or copy credential values. Provider detection records only `credential_configured` booleans.
- Do not commit `.env` files, backups, OpenClaw state, transcripts or worktrees. Check `.gitignore` before adding new output paths.
- Do not run `backup` against the real `~/.openclaw` or run `inventory` against the real machine unless the operator asks. With no `--output`, `inventory` overwrites the tracked `inventories/latest.json`.
- Use `backup --dry-run` before any real backup. Do not add restores, upgrades or cleanup that delete data; every mutation needs a dry run or preflight and a rollback path.
- Treat the legacy Agent-Engineers repository as read-only.
- Do not guess Kimi credentials, operator identities, approval roles, OpenRouter source-code policy or remote-access topology.
- Commit and push on a branch and open a PR as your bot. Merge it yourself when it is documentation-only or a low-risk change covered by passing tests; changes to `MIGRATION_SPEC.md`, the safety invariants or anything in `USER_ACTIONS.md` wait for the operator. Never push to `main` directly.
- Keep `TODO.md` current when work changes migration status.
