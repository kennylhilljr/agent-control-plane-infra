# Migration TODO Ledger

Legend:

- `[ ]` not started
- `[~]` in progress
- `[x]` verified complete
- `[!]` blocked; record the blocker immediately below the item
- **AUTO** fully automatable
- **APPROVAL** automated after an operator confirmation
- **MANUAL** requires operator action

## Phase 0 — Preserve and inventory

- [x] **AUTO** Create sanitized host, runner, provider, plugin, and model inventory.
- [x] **AUTO** Capture OpenClaw agents, bindings, jobs, plugins, devices, and version.
- [x] **AUTO** Capture ECC installation state for Claude, Codex, and Kimi.
- [x] **AUTO** Capture Git state for Agent-Engineers and pilot repositories.
- [ ] **APPROVAL** Checkpoint partial `my-research-mcp-server` modernization work.
- [x] **AUTO** Back up OpenClaw configuration, state databases, and job definitions.
  Verified checkpoint: `/Users/bkh223/AgentPlatformBackups/openclaw-20260924T052012.596577Z`.
- [x] **AUTO** Validate backup checksums and disposable restore.
- [!] **AUTO** Scan reports and repositories for committed secrets.
  Blocked on credential triage: the three new/current repositories pass, but
  Agent-Engineers contains 23 findings. Its ignored `.env`, generated `.env`,
  and generated private key are not Git-tracked but may be live credentials;
  tracked documentation/workflow findings require false-positive review before
  archive or migration.

## Phase 1 — OpenClaw 2.0 upgrade

- [x] **AUTO** Run current-version doctor and upgrade preflight.
  Report: `inventories/openclaw-upgrade-preflight.json`; gateway reachable,
  zero critical security findings, one pre-existing missing transcript.
- [x] **APPROVAL** Upgrade from `2026.2.3-1` to pinned `2026.8.1`.
- [x] **AUTO** Validate configuration migrations and Gateway startup.
- [x] **AUTO** Verify Control UI, sessions, devices, jobs, and plugins.
  Validation: `inventories/openclaw-2026.8.1-validation.json`.
- [x] **AUTO** Execute and verify rollback rehearsal.
  Native archive restored to a fresh staging directory: 344 entries, 232 files.
- [x] **APPROVAL** Select later stable version after release-channel review.
  Selected `2026.9.6` after reviewing the official release notes and runtime requirements.
- [x] **AUTO** Upgrade to selected current stable and repeat verification.
  Validation: `inventories/openclaw-2026.9.6-validation.json`; native rollback
  rehearsal restored 353 entries successfully.

## Phase 2 — ECC installation

- [ ] **MANUAL** Choose Claude ECC scope and hook profile.
- [ ] **APPROVAL** Install ECC once in Claude Code.
- [ ] **AUTO** Verify Claude plugin inventory and ECC doctor.
- [ ] **APPROVAL** Install ECC once in Codex.
- [ ] **AUTO** Verify Codex plugin inventory and ECC audit.
- [ ] **MANUAL** Add Kimi credential to approved secret storage.
- [ ] **APPROVAL** Install ECC project surface for Kimi if retained.
- [ ] **AUTO** Verify no duplicate/manual/legacy ECC installations.

## Phase 3 — Runner certification

- [ ] **AUTO** Diagnose Claude Code non-interactive hang.
- [ ] **AUTO** Certify Claude read/edit/test/commit/cancel workflow.
- [ ] **AUTO** Repair global Codex CLI or install stable wrapper.
- [ ] **AUTO** Certify Codex read/edit/test/commit/review/cancel workflow.
- [ ] **AUTO** Certify Gemini API worker; decide whether CLI auth adds value.
- [ ] **AUTO** Replace retired Groq model with dynamic discovery.
- [ ] **AUTO** Certify Groq low-cost task and review roles.
- [ ] **AUTO** Certify OpenRouter approved fallback models and data policy.
- [ ] **MANUAL** Configure Kimi credential.
- [ ] **AUTO** Benchmark Kimi against Gemini on long-context tasks.
- [ ] **APPROVAL** Retain or retire Kimi based on benchmark.
- [ ] **AUTO** Remove Windsurf and Pi from all active inventories and routes.
- [ ] **AUTO** Disable routine direct OpenAI API coding route.

## Phase 4 — Orchestrator runtime

- [ ] **AUTO** Define and test task, handoff, routing, status, and budget schemas.
- [ ] **AUTO** Implement DAG validation and durable run state.
- [ ] **AUTO** Implement worktree creation, ownership, and safe cleanup.
- [ ] **AUTO** Implement native runner adapters.
- [ ] **AUTO** Implement dynamic model discovery and readiness probes.
- [ ] **AUTO** Implement cost-aware task classification.
- [ ] **AUTO** Implement evidence-based escalation and circuit breakers.
- [ ] **AUTO** Implement process streaming, timeout, and cancellation.
- [ ] **AUTO** Implement quality gates and structured verification results.
- [ ] **AUTO** Implement independent reviewer assignment.
- [ ] **AUTO** Implement conflict prediction and merge queue.
- [ ] **AUTO** Implement OpenClaw progress, approval, and attention events.
- [ ] **AUTO** Test restart/resume and conductor handoff.

## Phase 5 — OpenClaw agents and multiplayer

- [ ] **APPROVAL** Create conductor and specialist agent roster.
- [ ] **AUTO** Assign isolated state, workspaces, models, and tool scopes.
- [ ] **AUTO** Configure model fallbacks and spending limits.
- [ ] **MANUAL** Define human operator identities and roles.
- [ ] **MANUAL** Assign approval rights for secrets, destructive operations, and merges.
- [ ] **AUTO** Verify ownership, presence, assignment, and audit events.
- [ ] **AUTO** Verify users cannot access unintended agents or credentials.
- [ ] **APPROVAL** Configure secure remote access if needed.

## Phase 6 — Pilot

- [ ] **AUTO** Import the research MCP Phase 1 plan.
- [ ] **APPROVAL** Dispatch three independent pilot work units.
- [ ] **AUTO** Verify isolated worktrees and non-overlapping scope.
- [ ] **AUTO** Run required tests and independent reviews.
- [ ] **APPROVAL** Merge pilot units sequentially.
- [ ] **AUTO** Publish time, cost, quality, escalation, and intervention report.
- [ ] **APPROVAL** Approve platform corrections and wider rollout.

## Phase 7 — Retire Agent-Engineers

- [ ] **AUTO** Export routing, audit, budget, and useful prompt concepts.
- [ ] **AUTO** Produce active-dependency report.
- [ ] **APPROVAL** Tag and archive Agent-Engineers.
- [ ] **APPROVAL** Disable daemons, startup items, schedules, and integrations.
- [ ] **MANUAL** Rotate migrated credentials.
- [ ] **AUTO** Verify revoked credentials and absence of active consumers.
- [ ] **AUTO** Remove Agent-Engineers from routing and documentation.
- [ ] **APPROVAL** Decide archival retention and eventual deletion date.

## Phase 8 — Production readiness

- [ ] **AUTO** Add CI, coverage, lint, type, security, secret, and SBOM gates.
- [ ] **AUTO** Publish operator, incident, backup, restore, and upgrade runbooks.
- [ ] **AUTO** Schedule recurring runner doctor and model-catalog refresh.
- [ ] **AUTO** Add one application repository at a time.
- [ ] **APPROVAL** Enable remote/cloud workers after security review.
- [ ] **APPROVAL** Enable experimental Swarm only after DAG reliability target is met.
- [ ] **AUTO** Verify all definition-of-done conditions.
