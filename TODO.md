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

- [x] **MANUAL** Choose Claude ECC scope and hook profile.
  Chosen 2026-09-24: `user` scope, `standard` hook profile.
- [x] **APPROVAL** Install ECC once in Claude Code.
  Native `ecc@ecc` 2.2.2, user scope, enabled; the only installed Claude plugin.
- [x] **AUTO** Verify Claude plugin inventory and ECC doctor.
  Evidence: `inventories/ecc-2.2.2-verification.json`. Plugin list and
  `claude plugin validate` pass; ECC doctor finds no install-state because it
  does not cover native plugins, so no doctor pass is claimed.
- [x] **APPROVAL** Install ECC once in Codex.
  Native `ecc@ecc` 2.2.2 from the `ecc` marketplace, installed and enabled.
- [x] **AUTO** Verify Codex plugin inventory and ECC audit.
  Plugin list shows exactly one enabled `ecc@ecc` 2.2.2. Codex has no plugin
  audit command and ECC doctor does not cover native plugins; no audit pass claimed.
- [ ] **MANUAL** Add Kimi credential to approved secret storage.
- [x] **APPROVAL** Install ECC project surface for Kimi if retained.
  `openclaw-ecc-orchestrator/.kimi-code`, `ecc-universal` 2.2.1, profile `core`;
  hooks skipped by the adapter. ECC doctor for the kimi target: 1 ok, 0 issues.
- [x] **AUTO** Verify no duplicate/manual/legacy ECC installations.
  Native installs are unique and both legacy Skillfish `everything-claude-code`
  directories were archived to
  `/Users/bkh223/AgentPlatformBackups/skillfish-ecc-legacy-20260924T072733Z`.
  Operator approved 2026-09-24: 14 per-skill manual Skillfish ECC copies that
  duplicate native ECC 2.2.2 were archived from each of `~/.claude/skills` and
  `~/.codex/skills` to
  `/Users/bkh223/AgentPlatformBackups/skillfish-ecc-per-skill-20260924T115032Z`
  (checksummed tarballs, MANIFEST.md with rollback). `claude-api` was kept
  because native ECC does not provide it, so it is not a duplicate.

## Phase 3 — Runner certification

- [!] **AUTO** Diagnose Claude Code non-interactive hang.
  Blocker: no hang in 3 bounded runs (stdin closed, `--permission-prompts none`, 3 to 63 s), but every call failed with "Credit balance is too low" (HTTP 400), so a full turn is unobserved; evidence `inventories/runner-certification-2026-09-24.json`.
- [!] **AUTO** Certify Claude read/edit/test/commit/cancel workflow.
  Blocker: Claude Code 2.1.281 installed and logged in, but inference, repo exercise and cancellation fail with the credit error; operator must restore Claude usage (see USER_ACTIONS Credentials 6).
- [x] **AUTO** Repair global Codex CLI or install stable wrapper.
  Installed official `@openai/codex@alpha` (`0.158.0-alpha.7`) in the default
  Node 24 prefix; ChatGPT login and native plugin discovery verified.
- [~] **AUTO** Certify Codex read/edit/test/commit/review/cancel workflow.
  Certified 2026-09-24 (expires 2026-10-01): codex-cli 0.158.0-alpha.7, `gpt-6-luna` from the live catalog, all 7 checks pass incl. failing-unittest fix, commit and process-group cancel; the review role is not yet exercised.
- [!] **AUTO** Certify Gemini API worker; decide whether CLI auth adds value.
  Blocker: `GEMINI_API_KEY` is not in the login shell or launchd environment, so the runner is `not_configured`; Gemini CLI 0.19.4 installed, CLI auth not assessed.
- [!] **AUTO** Replace retired Groq model with dynamic discovery.
  Blocker: live catalog selection by pattern (no hard-coded id) is implemented and unit tested, but `GROQ_API_KEY` is not in the environment, so no live selection ran.
- [!] **AUTO** Certify Groq low-cost task and review roles.
  Blocker: `GROQ_API_KEY` not in the environment; runner `not_configured`.
- [!] **AUTO** Certify OpenRouter approved fallback models and data policy.
  Blocker: `policy_not_approved` (no approved models or data policy; no key in the environment either); public catalog reachable, HTTP 200, 458 models, no key sent.
- [ ] **MANUAL** Configure Kimi credential.
- [ ] **AUTO** Benchmark Kimi against Gemini on long-context tasks.
- [ ] **APPROVAL** Retain or retire Kimi based on benchmark.
- [x] **AUTO** Remove Windsurf and Pi from all active inventories and routes.
  Runtime registry, adapters, catalog and certified-record filter reject both in any case; this repo has no routes and its inventory runner list excludes them (Agent-Engineers is legacy, not edited).
- [x] **AUTO** Disable routine direct OpenAI API coding route.
  Runtime rejects `openai`, `openai-api`, `openai_api`, `openai-api-coding` everywhere; this repo has no routes, `openai` appears only as a credential presence field for rotation.

## Phase 4 — Orchestrator runtime

Runtime lives in `openclaw-ecc-orchestrator` (Python 3.11+, standard library
only, uncommitted as of 2026-09-24). Suite: 527 unittest tests, run on this
Mac and in a Linux sandbox. An independent review found 2 critical, 4 high,
4 medium, and 4 low issues; all were fixed with regression tests before sync.

- [x] **AUTO** Define and test task, handoff, routing, status, and budget schemas.
  `schemas.py` (authoritative) plus 8 JSON Schema files in `schemas/`.
- [x] **AUTO** Implement DAG validation and durable run state.
  `runs/`: atomic snapshot, flock, append-only JSONL log, lease renewal.
- [x] **AUTO** Implement worktree creation, ownership, and safe cleanup.
  `worktrees/`: refuses unique work unless bundled; shared git state guard.
- [~] **AUTO** Implement native runner adapters.
  Probe adapters exist for Claude, Codex, Gemini, Groq, OpenRouter, Kimi;
  live invocation flags are unconfirmed until Phase 3 certification runs.
- [~] **AUTO** Implement dynamic model discovery and readiness probes.
  Implemented and tested with fakes; no live catalog refresh has run yet.
- [x] **AUTO** Implement cost-aware task classification.
- [x] **AUTO** Implement evidence-based escalation and circuit breakers.
- [x] **AUTO** Implement process streaming, timeout, and cancellation.
  Minimal env allowlist, process-group kill, single redaction engine.
- [x] **AUTO** Implement quality gates and structured verification results.
  Allowlist-first command policy; shell wrappers refused.
- [x] **AUTO** Implement independent reviewer assignment.
- [x] **AUTO** Implement conflict prediction and merge queue.
  Approvals via broker only, bound to plan hash and verified head SHA.
- [~] **AUTO** Implement OpenClaw progress, approval, and attention events.
  JSONL event contract and decision inbox done (`docs/openclaw-events.md`).
  Operator CLI done (`docs/cli.md`). OpenClaw plugin built in
  `openclaw-ecc-orchestrator/integrations/openclaw-plugin/` (plain JS, no
  dependencies): 28 unit tests, a Python contract test, and an isolated
  gateway end-to-end approval all pass. NOT installed in the production
  gateway; installation is an APPROVAL step (see the plugin README).
  Open: the runtime needs a standing inbox processor so plugin decisions
  apply without running `approvals approve`; `decided_by` records the shared
  owner profile until per-person OpenClaw sign-in exists (Phase 5).
- [x] **AUTO** Test restart/resume and conductor handoff.
  `tests/test_resume_integration.py` covers success, failure, cancellation,
  reassignment, conflict, budget exhaustion, restart, and conductor change.

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
