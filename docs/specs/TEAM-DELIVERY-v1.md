# Agent Team Delivery Loop: Specification (v1)

- **Status:** Draft for owner approval. No code is written against it until approved.
- **Owner:** Kenny Hill Jr.
- **Date:** 2026-10-19
- **Extends:** [MIGRATION_SPEC.md](../../MIGRATION_SPEC.md) sections 6, 7, 8 and 9 (deltas in section 10 below)
- **Implements in:** `openclaw-ecc-orchestrator` (runtime) and each application repository's `.orchestration/` (configuration)
- **First user:** Research MCP v2 milestone M0 (`my-research-mcp`)

## 1. Why

The platform can run one work unit by hand, but it cannot deliver a milestone. On 2026-10-19 the pilot needed five runs (`rmcp-m0` to `rmcp-m0e`) to attempt one unit, and the last two attempts produced correct, committed, gate-passing code that was still marked failed:

| Run | Failure | Kind |
|---|---|---|
| rmcp-m0 | old `claude` CLI on PATH rejected a flag | environment |
| rmcp-m0b, rmcp-m0c | runner environment dropped `USER`, so Claude could not find its login | orchestrator defect |
| rmcp-m0d | runner could not learn or write the handoff path | orchestrator defect |
| rmcp-m0e | handoff did not match the schema (the prompt listed field names only) | orchestrator defect |

Each failure ended the unit, because a failed unit cannot return to `ready`, and every recovery meant a new run and starting over. MIGRATION_SPEC 9.3 already requires "one implementation attempt and one repair using verification output"; that was never built. Review and merge were manual steps the operator typed per unit.

The goal of this spec: the owner starts a milestone and gets it back merged and product-checked, with a team of agents doing the work and the loop repairing itself, and the owner is interrupted only for decisions agents must not make.

## 2. Goals and non-goals

| ID | Goal | Measure |
|---|---|---|
| TD-G1 | One command delivers a milestone: every unit coded, reviewed, verified and merged without per-unit operator commands. | M0 of `my-research-mcp` completes from one `ecc drive` with zero operator commands between start and the product report. |
| TD-G2 | Failures repair themselves within budget. | A unit whose first attempt fails a gate, a handoff check, a review or a verification is retried with the failure as input, in the same worktree, without operator action. |
| TD-G3 | Independent agents, not the author, decide quality and merge. | Every merge has an approving review and an approving verification from a model family other than the author's, and a post-merge gate run. |
| TD-G4 | The owner judges the product, not the plumbing. | The owner sees a product report per milestone (PI), plus only the stop conditions in section 7. |
| TD-G5 | Platform defects are caught before a real unit runs. | A preflight round trip exercises every runner's write, commit, handoff and gate path; the four defects in section 1 would each have failed it. |

Non-goals: parallel dispatch (a later version; units run one at a time in v1); API-only runners as authors (Backlog); pushing to a remote or opening GitHub pull requests (no remote exists; "PR" below is the local branch and its diff); changing the cost router.

## 3. The team

Roles are fixed; who plays each role is configuration (`.orchestration/team.json`, section 8).

| Role | Default player | Input | Output | Authority |
|---|---|---|---|---|
| **Coder** | Claude or Codex, chosen per unit by the existing cost router (classify, select, escalate) | Unit description, LLD sections, test ids, scope; on a retry, the previous failure (section 5) | Commits on the unit branch; a schema-valid handoff | Writes only inside the unit worktree and scope |
| **PR reviewer** | The other model family from the coder, at the unit's review tier | The diff (base to verified head), unit description, LLD section, test ids, gate results | Verdict `approved`, `changes_requested` or `rejected` with findings | Read only |
| **Verifier (QA)** | The other model family from the coder | A throwaway checkout of the verified head; the unit's user-facing behavior from the LLD and PRD | Verdict `pass` or `fail` with evidence: commands run, real outputs, findings | Runs commands in the throwaway checkout only; its changes are discarded |
| **Integrator** | The orchestrator (no model) | Approving review and verification bound to the same head | A local merge into `main` after the gates pass on the merge result | Merges locally; never pushes |
| **Security reviewer (ISO)** | The other model family, Tier 2 | Units that touch the policy's `high_risk_paths` (secrets, redaction, HTTP client, stores, auth, security tests) or whose diff trips the security signals of the classifier | Verdict like the PR reviewer, against OWASP Top 10 and the repository's security rules (secrets only in the Keychain, origin-scoped credentials, SSRF and download controls, redaction on every output, no SQL over local files) | Read only; blocking. Runs in addition to the PR reviewer, not instead of it |
| **Architect** | Claude Opus | (a) Milestone start: the plan, the LLD and the ADRs. (b) Units that change a contract other units depend on (`core/specs.py`, `core/models.py`, `sources/base.py`, schemas, migrations). (c) Milestone end: the code against the LLD's names and boundaries | (a) Plan check: units match the LLD, scopes do not overlap, dependencies are right. (b) Verdict on contract changes. (c) Drift report | Read only; (a) and (b) are blocking, (c) feeds the product report |
| **Designer** | Claude Sonnet | Units that touch the UI (`ui/templates`, `ui/static`, UI routes); milestone M3 | Verdict on accessibility (WCAG 2.1 AA basics), consistency with the UI PRD, and the rendered pages (screenshots from a headless browser in the throwaway checkout) | Read only; blocking for UI units |
| **Delivery lead** | Claude Sonnet | A unit that hits a section 5.3 budget or tier stop; milestone end | (a) Triage before the owner is interrupted: retry at a stated tier with a sharper brief, split the unit (proposed plan change), or escalate to the owner with a diagnosis. (b) Milestone retrospective: time, cost, attempts, escalations, interventions per unit (the Phase 6 pilot report) | May re-queue a unit once at its maximum tier; plan changes go to the owner |
| **Product owner** | Claude Opus | `main` at milestone end; the PRD goals and milestone exit criteria; the test plan's milestone gate; the architect's drift report and the delivery lead's retrospective | Product report: each exit criterion met or not, with evidence; verdict `accept` or `reject` | Read only, plus running the test suite and CLI in a throwaway checkout |

Independence rules: the reviewers (PR, security, architect for contract units, designer for UI units) and the verifier are never the coder's model family when two families are certified (MIGRATION_SPEC 9.4); the reviewer and verifier run as separate sessions with separate prompts; the product owner reviews the milestone as a whole, not units.

**Where the personas come from.** The PR reviewer, security reviewer, QA, architect, designer, engineering lead and product manager prompts in `agent-engineers/prompts/` are the starting point (Phase 7: export useful prompt concepts). Their Linear, Slack, GitHub-comment and report-file mechanics are dropped; each persona keeps its checklist and returns the verdict line in section 6.3. The orchestrator, ops, knowledge-base and provider-specific personas are not carried over: the drive loop replaces the orchestrator, OpenClaw's `ops` agent handles notifications, and the LLD plus ADRs are the knowledge base.

**What "verify the user experience and production output" means for a unit.** The verifier does not re-read the tests. It uses the unit the way its consumer will: runs the CLI commands the unit adds, calls the MCP tools through the in-memory client, starts the daemon where the unit provides one, feeds edge inputs, and compares the real outputs (shapes, errors, messages, files written) with the LLD and the PRD requirement ids the unit traces to. Units with no user-facing surface (for example M0-02, identifiers) are verified against their contract: property checks and a sample of real-world inputs.

## 4. Flow

### 4.1 Per unit

```
ready -> CODER -> handoff valid? -> gates pass? -> REVIEWER -> VERIFIER -> INTEGRATOR -> merged
            ^          | no              | no           |            |            |
            |          v                 v              v            v            v
            +------ repair loop (section 5) with the failure as input; same worktree --+
```

1. **Code.** The coder runs with the unit prompt (section 6.1).
2. **Handoff check.** Missing or invalid handoff with a clean exit: one handoff-only repair turn (section 5.2) before anything else.
3. **Gates.** The orchestrator runs the unit's acceptance commands and required checks in the worktree, plus scope and commit checks.
4. **Review.** The PR reviewer reads the diff; in the same step the security reviewer runs when the unit is high risk, the architect when it changes a shared contract, and the designer when it touches the UI. Every triggered reviewer must approve. `changes_requested` returns to the coder with the findings; `rejected` stops the unit (section 7).
5. **Verify.** The verifier exercises the head in a throwaway checkout. `fail` returns to the coder with the evidence.
6. **Integrate.** With an approving review and a passing verification bound to the same head, the orchestrator approves the merge request as `agent:<reviewer>+<verifier>`, merges into a scratch checkout of `main`, re-runs the gates there, and fast-forwards `main`. A conflict or a gate failure on the merge result returns to the coder with the conflict or the output.
7. Units whose dependencies merged become `ready`; the loop continues.

### 4.2 Per milestone (PI)

**Start.** Before the first unit, the architect checks the plan against the LLD and ADRs (scopes, dependencies, contract ownership). Findings that block go to the owner before any unit runs; that is the one planned interruption, and it costs nothing if the plan is right.

**End.** When every unit of the milestone is merged, three things run in order: the architect's drift check, the delivery lead's retrospective, then the product owner (section 6.4), who reads both. `accept` ends the drive with the report. `reject` stops the drive and sends the report to the owner (section 7); the owner decides whether the findings become new units.

## 5. Repair loops

### 5.1 Attempts and escalation

Each return to the coder is an attempt, counted against the unit's budget (`budget.attempts`, `budget.maximum_cost_usd`, `budget.minutes`). Escalation follows MIGRATION_SPEC 9.3 unchanged: the second attempt is a repair at the same tier using the failure as input; a tier increase happens only after an objective failure (gates, verification) and only within `routing.maximum_tier`; the projected-cost rule still applies.

Every retry:

- runs in the **same worktree and branch**, so earlier commits are kept and the coder continues rather than restarts;
- receives a **failure brief** (section 6.2) built by the orchestrator from evidence, never from the coder's own summary;
- moves the unit `failed -> ready` automatically, recorded with reason `retry:<previous reason>`.

### 5.2 Handoff-only repair

When the runner exited cleanly but the handoff is missing, unreadable or invalid, the orchestrator first runs one short repair turn with the validator's exact errors and the template, instructing the coder to rewrite only the handoff. It is not an attempt and does not escalate. If it fails, the unit takes a normal attempt.

### 5.3 What never retries

| Condition | Why | Goes to |
|---|---|---|
| Runner not signed in, expired login, missing CLI, CLI older than the certified version | Retrying cannot fix it | `needs_user` with the exact command (for example `claude /login`) |
| Permission denied for a tool the unit needs | A platform defect | `needs_user`, flagged as a platform defect with the denied tool |
| Budget or maximum tier reached | Spend control | The delivery lead triages once (section 3); then `needs_user` with the attempt history and the triage |
| Review verdict `rejected` (wrong approach, not fixable by repair) | Needs a decision | `needs_user` with the reviewer's findings |
| Shared git state changed outside the unit | Safety (existing invariant) | `needs_user` |

## 6. Contracts

### 6.1 Coder prompt

The existing unit prompt, plus: the handoff template and rules (done in `12569e8`), the literal handoff path and folder access (done in `8657bc9`), and on a retry the failure brief.

### 6.2 Failure brief

Plain text, at most 6,000 characters, built from evidence:

```
Attempt <n> of <max> for <unit>. The previous attempt failed: <reason>.
Evidence:
- <gate name> exited <code>; last lines: <tail>
- reviewer findings: <list>          (review returns)
- verifier findings and outputs: <list>  (verification returns)
- handoff validation errors: <list>  (handoff failures)
Your earlier commits are on this branch. Inspect them (git log, git diff <base>..HEAD), keep what is right,
fix the cause above, run the acceptance commands, commit, and write the handoff.
```

### 6.3 Reviewer and verifier verdicts

Each ends its reply with one line the orchestrator parses (no file write needed, so read-only runners work):

```
ECC_REVIEW {"verdict": "approved|changes_requested|rejected", "head": "<sha>", "findings": [{"severity": "blocker|major|minor", "where": "<path:line>", "what": "<text>"}]}
ECC_REVIEW is used by the PR, security, architect and designer reviews (each tagged with its role in the record).
ECC_VERIFY {"verdict": "pass|fail", "head": "<sha>", "checks": [{"what": "<behavior>", "how": "<command or call>", "expected": "<text>", "actual": "<text>", "ok": true}], "findings": [...]}
```

A verdict whose `head` differs from the verified head is discarded. An unparsable reply gets one re-ask; a second failure counts as `changes_requested` with the finding "reviewer output unparsable". `approved` with any `blocker` finding is treated as `changes_requested`.

### 6.4 Product report

Written to `.orchestration/reports/<run>-<milestone>-product-v1.md` on a report branch, merged like a unit (so it is reviewed), and summarized in the drive result. One row per exit criterion and goal measure that the milestone owns, with evidence (command, output excerpt, or file and line), and a verdict `accept` or `reject`.

## 7. Stop conditions (the only times the owner is interrupted)

1. A section 5.3 condition.
2. The product owner rejects a milestone.
3. The drive's own ceilings: `--max-cost-usd` (default: the policy's `max_cost_usd_total`) or `--max-hours`.

Everything else, including review and merge approval, is decided by agents. Each stop notifies through the OpenClaw event stream (existing `attention.required` events), which the inbox processor delivers.

## 8. Configuration

`.orchestration/team.json` in the application repository:

```json
{
  "schema_version": "1.0",
  "merge_approval": "agents",
  "reviewer": {"family": "other_than_author", "tier": "unit_review_tier"},
  "verifier": {"family": "other_than_author", "model_class": "standard", "timeout_minutes": 30},
  "security_reviewer": {"family": "other_than_author", "tier": 2, "when": "high_risk_paths_or_security_signals"},
  "architect": {"runner": "claude", "model": "opus", "when": ["milestone_start", "contract_units", "milestone_end"],
                "contract_paths": ["src/research_mcp/core/specs.py", "src/research_mcp/core/models.py",
                                   "src/research_mcp/sources/base.py", "src/research_mcp/platform/migrations/**"]},
  "designer": {"runner": "claude", "model": "sonnet", "when_paths": ["src/research_mcp/ui/**"]},
  "delivery_lead": {"runner": "claude", "model": "sonnet", "when": ["budget_stop", "milestone_end"]},
  "product_owner": {"runner": "claude", "model": "opus", "at": "milestone_end"},
  "handoff_repair_turns": 1,
  "preflight": "required"
}
```

Personas use the coding CLIs on the owner's subscriptions, so each review is a short turn at no per-token cost; `independent family` means Codex reviews Claude's work and the reverse. `merge_approval` is `agents` or `human`. `human` keeps today's broker flow for repositories that want it; `my-research-mcp` uses `agents`.

## 9. Preflight round trip

`ecc drive` starts with a preflight per certified coding runner, in a throwaway worktree of a throwaway branch: write a file, commit it, write a schema-valid handoff to the real handoff path, and run `uv --version` and `git status` as gate commands, all through the exact runner command, environment and permissions the units use. Any failure stops the drive before a real unit runs, with the runner's error. It takes about a minute and costs one short turn per runner.

## 10. Changes to MIGRATION_SPEC

| Section | Today | With this spec |
|---|---|---|
| 6 invariant 7 | Tests and gates block merges | Unchanged, and gates also run on the merge result |
| 7 `review` | Assign a different-provider reviewer (recorded by hand) | The orchestrator runs the reviewer |
| 7 `merge` and Phase 5 "approval rights for merges" | Human approval through the broker | Per repository: `merge_approval: agents` approves when an independent review and verification pass on the same head; `human` keeps the broker flow |
| 9.3 | One attempt and one repair (not implemented) | Implemented as section 5 |
| 16 definition of done | Independent review blocks unsafe merges | Plus: a milestone completes from one drive; preflight passes |

Credentials, destructive cleanup and external publication keep their human gates.

## 11. Acceptance tests

Unit and integration tests run with fake runners (the existing test override). Live checks run on the Mac.

| ID | Test | Level |
|---|---|---|
| AT-TD-01 | A failed unit within budget returns to `ready` automatically with reason `retry:<reason>`; outside budget it goes to `needs_user` | unit |
| AT-TD-02 | A retry reuses the worktree and branch; earlier commits are present at start | integration |
| AT-TD-03 | The failure brief contains the gate tail, reviewer findings, verifier evidence or handoff errors as applicable, and is at most 6,000 characters | unit |
| AT-TD-04 | Handoff-only repair runs once on a clean exit with an invalid handoff, is not counted as an attempt, and the unit proceeds when it succeeds | integration |
| AT-TD-05 | "Not logged in", a missing CLI and a denied tool go to `needs_user` without consuming an attempt | unit |
| AT-TD-06 | Reviewer and verifier are a different family from the author; verdict lines parse; a wrong head is discarded; unparsable output is re-asked once | unit |
| AT-TD-07 | `changes_requested` and verifier `fail` return to the coder with the findings; `rejected` stops | integration |
| AT-TD-08 | With `merge_approval: agents`, an approving review and passing verification on the same head merge without operator input; gates run on the merge result; a failing merge gate returns to the coder | integration |
| AT-TD-09 | With `merge_approval: human`, behavior is unchanged from today | integration |
| AT-TD-10 | Dependents become ready after a merge and the drive continues to the end of the plan | integration |
| AT-TD-11 | The product owner runs once at milestone end; `accept` ends the drive; `reject` stops it with the report | integration |
| AT-TD-12 | Preflight fails on each of the four defects of section 1 when reintroduced, and passes on the fixed platform | integration |
| AT-TD-14 | The security reviewer runs exactly for units touching `high_risk_paths` or tripping security signals; its block returns the unit to the coder | integration |
| AT-TD-15 | The architect runs at milestone start (a blocking plan finding stops the drive before any unit), for contract units, and at milestone end (drift report reaches the product owner) | integration |
| AT-TD-16 | The designer runs only for UI units | unit |
| AT-TD-17 | A budget stop is triaged once by the delivery lead before the owner is interrupted; the retrospective lists time, cost, attempts and escalations per unit | integration |
| AT-TD-13 | Drive ceilings (`--max-cost-usd`, `--max-hours`) stop the drive cleanly | unit |
| OC-TD-01 | Live: `my-research-mcp` M0 completes from one `ecc drive` on the Mac; record time, cost, attempts, escalations and interventions (the Phase 6 pilot report) | owner check |

## 12. Build order

1. This spec approved (owner).
2. Orchestrator: retry loop and failure brief (5.1, 6.2), handoff-only repair (5.2), stop classification (5.3), preflight (9). Tests AT-TD-01 to 05, 12.
3. Orchestrator: persona runner (one mechanism for every reviewer, the verifier, the architect, the designer, the delivery lead and the product owner, with prompts adapted from agent-engineers), verdict parsing (6.3), agent merge approval (8). Tests AT-TD-06 to 09, 14 to 16.
4. Orchestrator: `ecc drive` loop, milestone start and end steps, ceilings (4.2, 6.4, 7). Tests AT-TD-10, 11, 13, 15, 17.
5. `my-research-mcp`: add `team.json`; update PILOT-M0 to one `ecc drive` command.
6. Live: OC-TD-01.

Steps 2 to 4 are built by hand under this spec and its tests, because the drive cannot build itself; from step 6 on, platform changes go through the drive like any other repository.

## 13. Already fixed during the pilot (kept)

| Commit | Fix |
|---|---|
| `6f96ea8` | Runner environment keeps `USER` and `LOGNAME`; Claude runner may run `uv` and `tools/ci.sh` |
| `8657bc9` | Literal handoff path in the prompt; `--add-dir` for the handoff folder |
| `12569e8` | Schema-valid handoff template and rules in the prompt |
