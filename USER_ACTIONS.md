# Operator Actions

This file contains only the actions that cannot or should not be completed
without the operator. Automation must perform all surrounding discovery,
validation, and verification.

## Before migration

1. Review the sanitized preflight report.
2. Choose how to preserve current uncommitted work in
   `my-research-mcp-server`. Recommended: a dedicated migration checkpoint
   branch with separate commits for specification and partial implementation.
3. Confirm the local backup destination. **Confirmed 2026-09-24:**
   `/Users/bkh223/AgentPlatformBackups`, outside Git and protected with
   owner-only permissions.
4. Confirm that Agent-Engineers remains read-only until the pilot succeeds.

## OpenClaw upgrade

1. Approve the pinned upgrade to OpenClaw `2026.8.1` after the dry-run report.
2. Respond to any macOS security, service, or keychain prompts.
3. Confirm that critical historical sessions and scheduled jobs are visible
   after upgrade.
4. Approve or reject the later move from `2026.8.1` to the selected current
   stable release after its release-channel review. **Approved and completed
   2026-09-24:** OpenClaw `2026.9.6`.

## ECC choices

1. Choose Claude installation scope:
   - `user` — recommended when ECC should apply across your repositories;
   - `project` — committed for one repository;
   - `local` — private to one repository.
2. Choose the Claude ECC hook profile after reviewing exactly what it runs.
3. Approve Claude and Codex plugin trust prompts.
4. Do not install ECC through a second method after native installation.
5. **Decided 2026-09-24:** archive the 14 per-skill manual Skillfish ECC copies
   that duplicate native ECC 2.2.2 in `~/.claude/skills` and `~/.codex/skills`;
   keep `claude-api`, which native ECC does not provide. Archived to
   `/Users/bkh223/AgentPlatformBackups/skillfish-ecc-per-skill-20260924T115032Z`.

**Approved and installed 2026-09-24:** Claude `user` scope with the `standard`
hook profile, the native Codex plugin, and Kimi managed project files in
`openclaw-ecc-orchestrator/.kimi-code` (profile `core`; hooks skipped because
the Kimi adapter does not support them). Evidence:
`inventories/ecc-2.2.2-verification.json`. The standard Claude hook profile may
modify source files, manage processes, send transcript-derived text to an
external LLM, probe MCP services, enforce operation policy, and persist
governance/cost records. The Kimi credential is still required; see
Credentials below.

## Credentials

Enter credentials only through the designated secret manager or local protected
prompt. Never paste them into a model conversation, task file, Git issue, or
handoff.

Required decisions/actions:

1. Add or locate the Kimi/Moonshot credential.
2. Approve the OpenClaw credential scopes for each provider.
3. Confirm the approved OpenRouter models and whether proprietary source code may
   be sent to them.
4. After migration, rotate all provider credentials formerly stored in
   Agent-Engineers `.env`.
5. Revoke credentials for retired integrations.
6. Done: Claude Code usage restored on 2026-09-24 by signing in with the Max
   subscription (subscription sign-in). Claude certified on 2026-09-25 (expires
   2026-10-02), all 7 checks pass; evidence
   `inventories/runner-certification-2026-09-25.json`. No action left.
7. Make `GEMINI_API_KEY` and `GROQ_API_KEY` (and, if Kimi is kept,
   `MOONSHOT_API_KEY`) available to the orchestrator process from approved
   secret storage. None is set in the login shell or launchd environment, so
   Gemini, Groq and Kimi certify as `not_configured`. Rerun certification
   afterwards; the Phase 3 gate needs two certified economical workers.

## Multiplayer policy

1. List the trusted human operators.
2. Assign OpenClaw roles and ownership rights.
3. Decide who may approve:
   - secret access;
   - dependency installation;
   - network access;
   - destructive filesystem operations;
   - database migrations;
   - force pushes;
   - pull-request merges;
   - deployments.
4. Decide whether remote access is required. If yes, choose an approved
   Tailscale/TLS topology; do not expose the Gateway directly to the public
   internet.

## Provider retention decisions

1. Retain Claude and Codex as primary coding harnesses.
2. Retain Gemini and Groq as economical workers.
3. Review the Kimi-versus-Gemini benchmark and choose retain or retire.
4. Approve OpenRouter only as a pinned-model fallback/reviewer with an explicit
   data policy.
5. Confirm retirement of Windsurf and Pi.
6. Confirm that direct OpenAI API coding is disabled unless an API-only use case
   is documented.
7. OpenRouter: write the pinned `openrouter.approved_models` list and an explicit
   `data_policy` (including whether proprietary source code may be sent) into
   the orchestrator policy. Until then certification ends `not_configured` with
   reason `policy_not_approved`, even with a key; its public catalog is reachable.
8. Codex: the ChatGPT plan hit its usage limit during certification
   (2026-09-24, reset within minutes). Decide whether the plan's limits suit
   routine coding volume before Phase 6.

## Pilot and retirement

1. Approve the initial three-unit research MCP pilot.
2. Review the pilot's cost, quality, escalation, and intervention report.
3. Approve wider rollout or require corrections.
4. Approve Agent-Engineers service shutdown only after the pilot passes.
5. Approve archival retention and the future deletion date.

## Normal ongoing operation

You should not need to select cheap models. Automatic routing is the default.
Intervene only when:

- a task requests a capability or cost above policy;
- all allowed runners fail;
- a high-risk operation needs approval;
- a merge conflict requires product judgment;
- a provider requires new credentials or terms acceptance;
- the system proposes enabling a beta or experimental feature.
