# Agent Control Plane Infrastructure

Private operational repository for migrating from Agent-Engineers to an
ECC + OpenClaw multiplayer coding platform.

Start with:

1. [`MIGRATION_SPEC.md`](MIGRATION_SPEC.md) — architecture, automation, phases,
   safety gates, rollback, and acceptance criteria.
2. [`TODO.md`](TODO.md) — durable implementation checklist and status ledger.
3. [`USER_ACTIONS.md`](USER_ACTIONS.md) — the exact actions that require the
   operator's login, secret, approval, or policy decision.

This repository must never contain API keys, OAuth tokens, OpenClaw state
databases, chat transcripts, or generated coding worktrees.

## Current automation

Collect a sanitized Phase 0 snapshot without reading credential values,
messages, transcripts, prompts, or device tokens:

```bash
./bin/agent-platform inventory --json
```

The snapshot is written to `inventories/latest.json`. Run the dependency-free
test suite with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Preview and create an owner-only OpenClaw rollback checkpoint:

```bash
./bin/agent-platform backup --backup-dir ~/AgentPlatformBackups --dry-run --json
./bin/agent-platform backup --backup-dir ~/AgentPlatformBackups --json
```

The backup command excludes live logs, writes SHA-256 checksums, rejects unsafe
archive members, and verifies every file through a disposable extraction.
