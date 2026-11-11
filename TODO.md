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
- [x] **AUTO** Refuse destinations overlapping the source, exclude tmp/, and detect mid-backup source changes.
  Issue #25: the error tells the operator to stop the Gateway and retry.
- [x] **AUTO** Check committed inventory evidence for leaks and over-redaction.
  `python3 scripts/check_inventories.py` (run by `scripts/check.sh`) passes on
  every committed `inventories/**/*.json`; `redact` now covers private keys,
  passphrases, cookies, bearer values and plural/camelCase secret names while
  keeping secret counts and token usage. Does not resolve the Agent-Engineers
  credential triage below.
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

**Gate met 2026-10-18:** Claude and Codex (coding) plus Gemini, Groq and Kimi (economical) certified in one run, `inventories/runner-certification-2026-10-18.json`. Certifications expire after 7 days (next: 2026-10-25); keys come from the macOS Keychain through `bin/with-keychain-secrets`.

- [x] **AUTO** Diagnose Claude Code non-interactive hang.
  Not reproduced: after the subscription sign-in (2026-09-24) full turns complete (inference 5.5 s, repo exercise 28.8 s) with stdin closed and `--permission-prompts none`; unit runners are now guarded by health monitoring instead of a wall clock kill; evidence `inventories/runner-certification-2026-09-25.json`.
- [x] **AUTO** Certify Claude read/edit/test/commit/cancel workflow.
  Certified 2026-09-25 (expires 2026-10-02): Claude Code 2.1.281, `haiku` (claude-haiku-4-5), all 7 checks pass; the cancel check is now event triggered (probe prompt in `stream-json` mode, which needs `--verbose`; group cancelled on the first stream event and proven gone). Codex recertified the same way (expires 2026-10-02). Recertified 2026-10-18 (expires 2026-10-25) with Claude Code 2.1.281 first on PATH; a stale `~/.local/bin/claude` 2.1.112 failed with an unknown option until then, and the adapter now enforces a 2.1.281 minimum.
- [x] **AUTO** Repair global Codex CLI or install stable wrapper.
  Installed official `@openai/codex@alpha` (`0.158.0-alpha.7`) in the default
  Node 24 prefix; ChatGPT login and native plugin discovery verified.
- [~] **AUTO** Certify Codex read/edit/test/commit/review/cancel workflow.
  Certified 2026-09-24 (expires 2026-10-01): codex-cli 0.158.0-alpha.7, `gpt-6-luna` from the live catalog, all 7 checks pass incl. failing-unittest fix, commit and process-group cancel; the review role is not yet exercised. Recertified 2026-09-25 (expires 2026-10-02) with the event triggered cancel check (`inventories/runner-certification-2026-09-25.json`). Recertified 2026-10-18 (expires 2026-10-25), `inventories/runner-certification-2026-10-18.json`.
- [x] **AUTO** Certify Gemini API worker; decide whether CLI auth adds value.
  Certified 2026-10-18 on `gemini-3.5-flash-lite` (live catalog, 46 models), `inventories/runner-certification-2026-10-18.json`. Needed a log inspection fix: Gemini's opaque `thoughtSignature` no longer counts as a leaked secret. CLI auth not pursued; the API worker is sufficient.
- [x] **AUTO** Replace retired Groq model with dynamic discovery.
  2026-10-18: live selection picked `openai/gpt-oss-20b` from 11 listed models by pattern (patterns updated; the old `instant`/8b models are gone). Groq's edge required a named User-Agent (HTTP 403, error 1010, before the fix).
- [~] **AUTO** Certify Groq low-cost task and review roles.
  Low-cost task certified 2026-10-18 on `openai/gpt-oss-20b` (free tier; probe budget raised to 512 tokens for this reasoning model), `inventories/runner-certification-2026-10-18.json`. Review role not yet exercised.
- [x] **AUTO** Certify OpenRouter approved fallback models and data policy.
  Resolved by operator decision 2026-10-18: OpenRouter is parked, not certified. The adapter stays in the code, gated off by policy (`policy_not_approved`); the key was removed from the Keychain. Reopen by approving pinned models and a data policy.
- [x] **MANUAL** Configure Kimi credential.
  Stored in the macOS Keychain 2026-10-18 (account recharged by the operator). Certified on `kimi-k2.7-code`; the probe sends no temperature (`kimi-k3` accepts only 1).
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
  2026-09-25: health monitoring replaced wall clock kills for runners and gates
  (checks every 120 s of group CPU, output, stream events, worktree and process
  set; cancel only after 5 flat checks, reason `hung`); `budget.minutes` is
  advisory (`long_running` attention); `unit.completed` and `unit.health` events.
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
  gateway end-to-end approval all pass. Installed in the production gateway
  2026-10-18 after an operator-approved backup
  (`~/AgentPlatformBackups/openclaw-20261018T194641.749713Z`; the backup tool
  now records symlinks without following them). `openclaw plugins inspect`
  shows it loaded with `/ecc`, `/ecc-decide`, both gateway methods, the panel
  route and the tail service; only warning is the expected unverified origin
  (`plugins.allow` intentionally unset). Rollback: unset
  `plugins.entries.ecc-orchestrator`, then `plugins.load.paths`.
  Standing inbox processor done 2026-10-18 (`approvals process-inbox
  --watch`, launchd agent `local.openclaw-ecc-orchestrator.inbox-processor`,
  running), so OpenClaw approvals apply without a CLI command.
  Open: the runtime needs a standing inbox processor so plugin decisions
  apply without running `approvals approve`; `decided_by` records the shared
  owner profile until per-person OpenClaw sign-in exists (Phase 5).
- [x] **AUTO** Test restart/resume and conductor handoff.
  `tests/test_resume_integration.py` covers success, failure, cancellation,
  reassignment, conflict, budget exhaustion, restart, and conductor change.
- [x] **AUTO** Verify the OpenClaw round trip end to end.
  2026-10-18 (orchestrator `6d1ecde`): `tests/test_roundtrip_openclaw.py`
  runs the CLI, the plugin engine and the standing inbox processor as
  separate processes (approve to merge, reject, queued decision, refusals,
  forged decision, plugin restart, secret hygiene). Live on the Mac,
  `bin/roundtrip-smoke` passed: run in the live event log, pending in the ECC
  tab, approved through `ecc-orchestrator.decide` (`decided_by`
  `gateway-owner`), applied by the launchd processor, merged into a throwaway
  repository. `/ecc-decide` in the Control UI chat is refused (no sender
  identity in OpenClaw 2026.9.6); `bin/ecc-decide` is the operator path.
  The live run found and fixed a redaction false positive on time-stamped
  branch names.

### TEAM-DELIVERY v8 documentation (issues #4, #5, and #6)

- [x] **AUTO** Draft the authoritative TEAM-DELIVERY v8 guide.
  `docs/TEAM-DELIVERY-v8.md` defines the post-LLD plan readiness gate,
  deterministic lint, standalone architect check, owner approval boundary,
  Provides/Requires declarations, contract-first milestone units, composition
  ownership, active-run hygiene, milestone close, and evidence requirements.
- [x] **AUTO** Add a reusable run-guide template.
  `docs/templates/TEAM-DELIVERY-v8-run-guide.md` separates automated evidence,
  delivery-lead duties, architect review, and operator-only checks and approval.
- [x] **MANUAL** Review and approve TEAM-DELIVERY v8 as owner (approved 2026-10-29).
  The owner-approval gate for TEAM-DELIVERY v8 is satisfied for the reviewed
  revision recorded in `USER_ACTIONS.md` (guide blob `f25f665b1e4d`, run-guide
  template blob `d41f4c443065`). A later change to either file needs a new
  approval. Other `create-run` prerequisites still apply.
- [~] **AUTO** Track cross-repository adoption under issue #6.
  Issue #6 is a tracking issue. Linked runtime and application issues keep
  their own implementation, test, review, and acceptance status; none is
  marked complete by these documentation changes.

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

- [x] **AUTO** Import the pilot plan.
  2026-10-18: pilot changed by the operator from `my-research-mcp-server` to
  HomeSentinel v2 milestone M0 (17 units). Plan, policy and operator config
  in `~/Documents/GitHub/homesentinel-v2/.orchestration/` (commit `c4776e1`),
  validated with the orchestrator's schemas and a `create-run` dry run;
  runbook `.orchestration/PILOT-M0.md`. Authors: Claude and Codex (API
  runners cannot author yet; see Backlog).
  2026-10-19: pilot changed back by the operator to the research MCP
  rebuild: Research MCP v2 milestone M0 (16 units), in
  `~/Documents/GitHub/my-research-mcp/.orchestration/` (plan validated
  with the orchestrator's schemas and classifier; runbook
  `.orchestration/PILOT-M0.md`). HomeSentinel v2 M0 stays ready to run next.
  Not yet committed in the new repository.
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
- [x] **AUTO** Schedule recurring runner doctor and model-catalog refresh.
  2026-10-18: launchd agent `local.openclaw-ecc-orchestrator.recertify` runs
  `bin/recertify-weekly` Sundays 09:00 (certification lasts 7 days; each run
  refreshes the live model catalogs) and notifies the outcome. First launchd
  run passed with the gate met. Jobs run from a git worktree at
  `~/.local/share/openclaw-ecc-orchestrator/runtime`, because macOS privacy
  protection blocks launchd jobs from `~/Documents`.
- [ ] **AUTO** Add one application repository at a time.
- [ ] **APPROVAL** Enable remote/cloud workers after security review.
- [ ] **APPROVAL** Enable experimental Swarm only after DAG reliability target is met.
- [ ] **AUTO** Verify all definition-of-done conditions.

## Backlog (useful, not blocking)

Recorded 2026-10-18. Each item has value but none blocks the pilot;
`bin/ecc-decide` covers approvals until the first two land.

- [ ] **AUTO** ECC tab: Approve and Reject buttons that call
  `ecc-orchestrator.decide` from the logged-in Control UI (no copying ids or
  plan prefixes). Value grows with the number of approvals a pilot produces.
- [ ] **AUTO** Plugin option `uiOperatorIdentity` (opt in) so `/ecc-decide`
  typed in an authorized Control UI session records that handle instead of
  failing closed; update the isolated gateway test, which expects the refusal.
- [ ] **AUTO** ECC tab: a Runners section showing certification status,
  expiry and model per runner from the latest recertification summary.
- [ ] **AUTO** API worker so Gemini, Groq and Kimi can author units: turn the
  model's output into a scoped commit in the unit worktree (today dispatch
  launches only the Claude and Codex coding CLIs).
- [x] **AUTO** Agent team delivery loop, built 2026-10-19 in openclaw-ecc-orchestrator
  (`2f41d67` repair loop and preflight, `21499c0` team review and agent
  merges, `6a65f4e` author_providers, `61377f4` catalog-refresh, `f5bc55b`
  `ecc drive`). Specified in
  `docs/specs/TEAM-DELIVERY-v2.md` (approved 2026-10-19; v2 rotates roles across all five providers), which covers the next
  two items plus repair loops, agent merge approval, QA verification,
  security, architect, designer, delivery-lead and product personas, and a
  preflight round trip. Build after owner approval.
- [ ] **AUTO** Team delivery v3 (spec revision first): delivery lead may
  re-queue a unit once past its budget; product report merged as a reviewed
  branch instead of the state dir; parallel dispatch of non-overlapping
  units; designer screenshots from a headless browser.
- [ ] **AUTO** Plan driver: dispatch ready units, run gates and request
  approvals without a CLI command per unit.
- [ ] **AUTO** OpenClaw cost routing: the five scoped agents (Sun_Bot router on
  API Haiku; coder on Codex; researcher and ops on Gemini Flash-Lite;
  architect on Opus) are live as of 2026-10-19. Groq is out of the agent set
  until a paid tier (free tier allows 8K tokens per minute; one call is 10.8K).
- [ ] **AUTO** Local runner for the ECC router once the Mac Studio arrives:
  an Ollama-backed runner with cost 0 for tier 0 and 1 units, still reviewed
  by a cloud family; also a candidate for OpenClaw heartbeats and the ops agent.
