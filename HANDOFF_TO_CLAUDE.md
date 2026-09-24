# Handoff to Claude: ECC + OpenClaw Agent Platform Migration

Continue implementing the approved migration described by `MIGRATION_SPEC.md` and tracked in `TODO.md`. The operator has explicitly approved the full specification and its non-destructive implementation actions. Preserve safety gates for credentials, destructive operations, human identity/roles, merges, and external publication.

## Repositories

- Infrastructure: `/Users/bkh223/Documents/GitHub/agent-control-plane-infra`
- Runtime: `/Users/bkh223/Documents/GitHub/openclaw-ecc-orchestrator`
- Pilot application: `/Users/bkh223/Documents/GitHub/my-research-mcp-server`
- Legacy, read-only until pilot succeeds: `/Users/bkh223/Documents/GitHub/agent-engineers`
- Backups: `/Users/bkh223/AgentPlatformBackups`

Read these first:

1. `MIGRATION_SPEC.md`
2. `TODO.md`
3. `USER_ACTIONS.md`
4. Repository `AGENTS.md` files before editing each repository

## Verified completed work

- OpenClaw upgraded and validated at `2026.9.6`; gateway, UI, sessions, devices, jobs, and plugins are healthy.
- OpenClaw gateway tokens migrated to its protected SQLite secret store. `openclaw secrets audit --check --json` is clean.
- Backups and disposable restore rehearsal pass. See `inventories/openclaw-2026.9.6-validation.json`.
- Codex CLI repaired under native arm64 Node 24.16.0: `codex-cli 0.158.0-alpha.7`, authenticated through ChatGPT.
- Claude Code repaired under native arm64 Node 24.16.0: version `2.1.281`.
- ECC installed natively in Claude as `ecc@ecc` version `2.2.2`, user scope, enabled. Its manifest defaults to hooks enabled with the `standard` profile.
- ECC marketplace added to Codex and native `ecc@ecc` version `2.2.2` installed and enabled.
- Kimi ECC project surface installed in the runtime repo at `.kimi-code/` using `ecc-universal@2.2.1`, profile `core`. Kimi hooks were correctly skipped because the adapter does not support them.
- Infrastructure unit tests previously passed: `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
- Gitleaks passes for the new repositories. Legacy Agent-Engineers has 23 findings requiring credential triage; do not print, move, delete, or commit those secrets.

## Immediate reconciliation work

1. Verify all three ECC installations and record sanitized evidence:
   - `source ~/.nvm/nvm.sh && nvm use default`
   - `claude --version`
   - `claude plugin list --json`
   - `codex --version`
   - `codex plugin list --json`
   - inspect `openclaw-ecc-orchestrator/.kimi-code/ecc-install-state.json`
2. Update `TODO.md` Phase 2 accurately. Kimi credential remains unconfigured and must stay pending.
3. Update `USER_ACTIONS.md`: the Claude user scope, standard hooks, native Codex plugin, and Kimi project surface were approved and installed on 2026-09-24. Remove the stale statement that installation is pending approval.
4. Run secret scans and tests after documentation changes.
5. The old directories below are duplicate manual Skillfish convention skills, not ECC 2.x:
   - `~/.claude/skills/everything-claude-code`
   - `~/.codex/skills/everything-claude-code`
   Verify their `.skillfish.json` markers, archive them under the approved backup root, and move them out of active skill paths only after native ECC verification. Do not use destructive deletion.

## Then continue the specification

Implement the runtime in small, test-driven slices, following Phase 3 and Phase 4 order:

1. Runner readiness probes and certification for Claude, Codex, Gemini, Groq, OpenRouter, and optionally Kimi.
2. Dynamic provider/model discovery. Do not hard-code retired Groq model IDs.
3. Cost-aware routing that automatically chooses economical models for low-risk tasks, with capability/risk-based escalation and independent review for high-risk work.
4. Versioned task, handoff, routing, budget, status, and verification schemas.
5. Durable DAG/run state, isolated Git worktrees, process streaming/cancellation, gates, reviewer assignment, conflict prediction, and merge queue.
6. OpenClaw integration for progress, approvals, attention events, and later multiplayer agent reconciliation.

Use the minimum implementation that satisfies the spec. Add tests before behavior. Do not start the research MCP pilot until runner/runtime gates pass. Do not retire Agent-Engineers until the pilot succeeds and credentials are rotated.

## Important constraints

- Never expose credential values in output, Git, prompts, reports, or handoffs.
- Do not infer Kimi credentials, human operator identities, approval roles, OpenRouter source-code policy, or remote-access topology.
- Keep Windsurf and Pi out of active routes.
- Routine direct OpenAI API coding should remain disabled in favor of subscription-backed Codex.
- Use `apply_patch` for file edits. Preserve unrelated user changes.
- Every mutating operation needs a dry run/preflight where practical and a rollback path.
- Do not commit or push unless the operator explicitly requests it.

## Validation before reporting progress

```bash
cd /Users/bkh223/Documents/GitHub/agent-control-plane-infra
PYTHONPATH=src python3 -m unittest discover -s tests -v
gitleaks dir . --no-banner --redact --exit-code 1

cd /Users/bkh223/Documents/GitHub/openclaw-ecc-orchestrator
gitleaks dir . --no-banner --redact --exit-code 1
git status --short
```

Continue autonomously until a genuinely manual choice, credential entry, destructive action, merge, or external publication is required. Keep `TODO.md` current as the durable ledger.
