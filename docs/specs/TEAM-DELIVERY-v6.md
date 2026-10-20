# Agent Team Delivery Loop: Specification (v6)

- **Status:** Approved by the owner on 2026-10-19. v6 makes build skills part of every unit, for every provider (owner decision, 2026-10-20). Supersedes [v5](TEAM-DELIVERY-v5.md).
- **Owner:** Kenny Hill Jr.
- **Date:** 2026-10-19
- **Extends:** [MIGRATION_SPEC.md](../../MIGRATION_SPEC.md) sections 6, 7, 8 and 9 (deltas in section 10 below)
- **Implements in:** `openclaw-ecc-orchestrator` (runtime) and each application repository's `.orchestration/` (configuration)
- **First user:** Research MCP v2 milestone M0 (`my-research-mcp`)

## Changes from v5

The owner asked that spec-driven builds use the same build skills as ctxd (run, simplify, verify, code review), for every provider: comparable skills where a provider has them, and otherwise a Claude Code session afterwards to run them. In v6 (new 4.5):

- Build skills are Markdown in the application repository (`.agents/skills/`, which Codex and Gemini read natively; `.claude/skills` links to it), so every provider follows the same steps. Later, ctxd's shared skill library distributes them; the repository stays the source of truth.
- Claude Code coders may invoke skills (the `Skill` tool is allowed), including its bundled `/simplify`, `/verify`, `/code-review` and `/security-review`.
- When a unit's author is not Claude Code, a **skills pass** runs after the author's attempt and before the gates: a fresh Claude Code session applies its bundled skills and the repository's to the unit's changes and commits fixes within the unit's scope.

## Changes from v4

The owner reviewed the first M0 run (`rmcp-m0f`) and asked for "rules around the branches to use, loops to continue until corrected, better instructions of the next step", and for a specification as the contract, as ctxd has. The run had stalled on exactly those gaps: units branched from the run's first commit and never saw their dependencies, every stop waited for the owner, and stops said `resolve_needs_user` instead of what to run. In v5:

- **The contract is the repository's specification** (new 4.3). Units cite its sections; reviewers, the architect and the product owners judge against it.
- **Branch rules** (new 4.4): a unit branches from the target's tip after its dependencies merged; before every later attempt the orchestrator merges the target into the unit's branch, and a conflict becomes the coder's task, not a stop.
- **Healing before the owner** (new 7.1): the drive sets aside a unit it cannot act on and carries on with the rest; before stopping, the delivery lead applies bounded recoveries on its own (one more attempt, a review restart, a conflict retry).
- **Next steps** (new 7.2): every stop lists the exact commands to run, and the CLI prints them as `next:` lines.
- **Isolation** (4.4): coding runs load project settings only, so the owner's personal editor plugins and hooks cannot refuse a unit's edits; Codex's sandbox is granted the shared `uv` cache.

## Changes from v3

The delivery lead moves from the economical class to the **standard** class. In run `rmcp-m0f` the economical panel gave the role to Groq's small model, whose triage of two stopped units was wrong: it invented a missing user token and a cost that did not exist, while the units' own handoffs named the real causes (a stale worktree base and a write-blocking editor guardrail). Triage decides what the owner is told, so it needs a model that reads evidence reliably. Groq serves only the economical class, so it no longer plays this role; the panel order is unchanged.

## Changes from v2

The owner ruled during the first live M0 run (`rmcp-m0f`) that a provider must never block delivery: "the blocker shouldn't be a provider. It's the persona the context that agent is running under. As long as different and the correct one for the role, it should proceed." The run had stopped because the only provider independent of both the coder and the PR reviewer returned empty replies. In v3:

- A role's independence comes from its **persona and its own session**: a fresh, read-only session with the role's prompt and evidence pack, never the coder's session. Every turn already runs that way (`claude -p` without session persistence, `codex exec --ephemeral`, stateless API calls).
- **Different providers are preferred, not required.** Assignment first tries providers other than the coder's (and, for the security reviewer, the PR reviewer's). If none of them produces a verdict, any provider eligible for the role's class plays the persona. Each verdict records `independence: provider` or `independence: persona`.
- A provider that errors or returns nothing is **skipped**, never counted as a verdict. This now also holds for the product owner, whose pair may be one provider playing the persona twice in separate sessions.
- `no_qualified_reviewer` remains only for the case where no eligible provider answers at all.

## Changes from v1

The owner found v1 biased toward Claude: every role that was not a cross-family review defaulted to Claude. In v2:

- Every role has a **panel** drawn from all five certified providers (Claude, Codex, Gemini, Kimi, Groq), and assignments **rotate** through the panel (new section 3.1).
- Roles that do not need to run commands (every reviewer, the architect, the designer, the delivery lead, the product owner) are **text-in, verdict-out**: the orchestrator hands them an evidence pack, so API-only providers can play them (section 3.2).
- The product owner is a **pair** of separate sessions, from two different providers when possible (v3), and both must accept.
- Rotation and provider share are reported, with a cap on any one provider's share (section 3.3).
- Authoring stays with the two coding CLIs (Claude Code and Codex) until API runners can author (MIGRATION backlog); that is a tooling limit, not a preference, and the share report shows it.

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
| TD-G3 | Independent agents, not the author, decide quality and merge. | Every merge has an approving review and an approving verification from sessions other than the author's, from another model family when one answers (v3), and a post-merge gate run. |
| TD-G4 | The owner judges the product, not the plumbing. | The owner sees a product report per milestone (PI), plus only the stop conditions in section 7. |
| TD-G5 | Platform defects are caught before a real unit runs. | A preflight round trip exercises every runner's write, commit, handoff and gate path; the four defects in section 1 would each have failed it. |

Non-goals: parallel dispatch (a later version; units run one at a time in v1); API-only runners as authors (Backlog); pushing to a remote or opening GitHub pull requests (no remote exists; "PR" below is the local branch and its diff); changing the cost router.

## 3. The team

Roles are fixed; who plays each role is configuration (`.orchestration/team.json`, section 8).

| Role | Default player | Input | Output | Authority |
|---|---|---|---|---|
| **Coder** | Claude or Codex, chosen per unit by the existing cost router (classify, select, escalate) | Unit description, LLD sections, test ids, scope; on a retry, the previous failure (section 5) | Commits on the unit branch; a schema-valid handoff | Writes only inside the unit worktree and scope |
| **PR reviewer** | Panel by review tier (3.1), rotating, never the coder's provider | The diff (base to verified head), unit description, LLD section, test ids, gate results | Verdict `approved`, `changes_requested` or `rejected` with findings | Read only |
| **Verifier (QA)** | Panel of tool-capable runners (3.1), rotating, never the coder's provider | A throwaway checkout of the verified head; the unit's user-facing behavior from the LLD and PRD | Verdict `pass` or `fail` with evidence: commands run, real outputs, findings | Runs commands in the throwaway checkout only; its changes are discarded |
| **Integrator** | The orchestrator (no model) | Approving review and verification bound to the same head | A local merge into `main` after the gates pass on the merge result | Merges locally; never pushes |
| **Security reviewer (ISO)** | Advanced panel (3.1), rotating, never the coder's or the PR reviewer's provider | Units that touch the policy's `high_risk_paths` (secrets, redaction, HTTP client, stores, auth, security tests) or whose diff trips the security signals of the classifier | Verdict like the PR reviewer, against OWASP Top 10 and the repository's security rules (secrets only in the Keychain, origin-scoped credentials, SSRF and download controls, redaction on every output, no SQL over local files) | Read only; blocking. Runs in addition to the PR reviewer, not instead of it |
| **Architect** | Advanced, long-context panel (3.1), rotating | (a) Milestone start: the plan, the LLD and the ADRs. (b) Units that change a contract other units depend on (`core/specs.py`, `core/models.py`, `sources/base.py`, schemas, migrations). (c) Milestone end: the code against the LLD's names and boundaries | (a) Plan check: units match the LLD, scopes do not overlap, dependencies are right. (b) Verdict on contract changes. (c) Drift report | Read only; (a) and (b) are blocking, (c) feeds the product report |
| **Designer** | Image-capable panel (3.1), rotating | Units that touch the UI (`ui/templates`, `ui/static`, UI routes); milestone M3 | Verdict on accessibility (WCAG 2.1 AA basics), consistency with the UI PRD, and the rendered pages (screenshots from a headless browser in the throwaway checkout) | Read only; blocking for UI units |
| **Delivery lead** | Standard panel (3.1), rotating (v4) | A unit that hits a section 5.3 budget or tier stop; milestone end | (a) Triage before the owner is interrupted: retry at a stated tier with a sharper brief, split the unit (proposed plan change), or escalate to the owner with a diagnosis. (b) Milestone retrospective: time, cost, attempts, escalations, interventions per unit (the Phase 6 pilot report) | May re-queue a unit once at its maximum tier; plan changes go to the owner |
| **Product owner** | A pair from the advanced panel (3.1), two separate sessions, different providers preferred (v3), rotating each milestone; both must accept | `main` at milestone end; the PRD goals and milestone exit criteria; the test plan's milestone gate; the architect's drift report and the delivery lead's retrospective | Product report: each exit criterion met or not, with evidence; verdict `accept` or `reject` | Read only, plus running the test suite and CLI in a throwaway checkout |

Independence rules (v3): the reviewers (PR, security, architect for contract units, designer for UI units) and the verifier always run as separate, read-only sessions with their own persona prompts, never in the coder's session. Another model family is preferred (MIGRATION_SPEC 9.4) but never blocks: when no other family answers, the coder's provider plays the persona; the product owner reviews the milestone as a whole, not units.

### 3.1 Panels and rotation

The panel lists providers in rotation order. Model ids are not fixed here: each comes from the repository policy's `cli_models` and `model_preferences` for the capability class, resolved against the live certified catalog (today: Claude Haiku, Sonnet and Opus; Codex GPT-6-Luna and GPT-6-Astra; Gemini 3.5 Flash-Lite; Kimi K2.7-Code and K3; Groq gpt-oss-20b).

| Role | Class | Needs tools | Panel (rotation order) |
|---|---|---|---|
| Coder | per unit tier (router) | yes | Claude Code, Codex (cost router picks; API authoring is backlog) |
| PR reviewer, tier 0 | economical | no | Gemini, Groq, Kimi, Codex, Claude |
| PR reviewer, tier 1 | standard | no | Kimi, Gemini, Codex, Claude |
| PR reviewer, tier 2 | advanced | no | Kimi, Codex, Claude |
| Security reviewer | advanced | no | Codex, Kimi, Claude |
| Verifier (QA) | standard | yes | Codex, Claude (the only tool-capable runners today; Gemini CLI or Kimi Code join when certified as coding runners) |
| Architect | advanced, long context | no | Kimi, Codex, Gemini, Claude |
| Designer | image-capable | no | Gemini, Codex, Claude |
| Delivery lead | standard (v4) | no | Gemini, Groq, Kimi, Codex, Claude (Groq is skipped: it serves only the economical class) |
| Product owner (pair) | advanced | no | Kimi, Codex, Claude (pair advances one step each milestone) |

**Assignment rule.** For each assignment the orchestrator walks the role's panel from the role's rotation cursor and takes the first provider that is:

1. certified and unexpired, with its circuit breaker closed;
2. preferably not the coder's provider, and for the security reviewer preferably not the PR reviewer's provider either. If no such provider produces a verdict, the walk repeats without this rule (v3);
3. at or above the role's capability class (a provider with no model in that class is skipped, for example Gemini for advanced roles while only Flash-Lite is certified);
4. able to take the evidence pack within its context window and rate limit (Groq's free tier, 8K tokens per minute, takes only small packs);
5. within the role's per-turn cost cap.

The cursor then moves past the chosen provider and is stored in the run state, so rotation survives restarts and is auditable. If no panel member qualifies, any certified provider that meets rules 1 to 3 is used; if none does, the existing `no_qualified_reviewer` stop applies.

### 3.2 Text-only personas and the evidence pack

A persona that does not need tools gets an evidence pack instead of a checkout, so API runners can play it:

- the unit description, scope and test ids; the LLD section text and ADRs the unit names;
- the diff from base to the verified head (lock files and generated files summarized, not inlined), plus the full text of changed files up to a size cap;
- gate commands with exit codes and output tails; the verifier's evidence when it ran first;
- for milestone roles: the milestone exit criteria and the outputs of the milestone gate commands, run by the orchestrator.

Tool-capable personas (Claude Code, Codex) get the same pack and may also read files. The verdict format (6.3) is the same for every provider.

### 3.3 Bias guardrails

The delivery lead's retrospective reports, per role and per provider: turns, share, cost, and agreement (for example, how often a reviewer approved what QA then failed, or what the product owner later rejected). When at least three providers are eligible for a role, no provider may take more than 40% of that role's turns in a milestone; the rotation cursor enforces it. Coder share is reported separately and is not capped, because only two runners can author today. Panels are reordered by the owner in `team.json`, informed by the agreement figures; the platform does not reorder itself.

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

### 4.3 The contract (v5)

Each application repository keeps a normative specification (for example `docs/spec/SPEC-v1.md`) that owns names, interfaces, formats and the work breakdown. Unit descriptions cite its sections by number; the evidence pack includes those sections; the architect's plan check, the drift check and the product owners judge against it as well as the PRD. A conflict between the specification and the PRD or test plan is recorded in the handoff, never resolved silently by code. Changing the specification takes a new version.

### 4.4 Branches (v5)

- A unit's branch is `ecc/<run>/<unit>`, created from the target branch's **current tip** when the unit first runs. A unit becomes ready only after its dependencies merged into the target, so its branch starts with them.
- Coders work only on their branch: commit there, never push, never create or switch branches, never rewrite history, never commit to the target. Only the merge queue writes the target, after review and verification pass on the same head.
- **Before every later attempt** (repair, retry, resume) the orchestrator merges the target's tip into the unit's branch. A clean merge is committed and the coder is told; a conflict is left in progress with the conflicted files named in the coder's prompt, and resolving it is the first part of the attempt; uncommitted changes block the merge and the coder is told to commit and merge.
- Diffs for review, scope and verification are measured from the branch's merge base with the target, so dependency work merged in is never counted as the unit's.
- Coding runs load project and local settings only (`claude --setting-sources project,local`), never the owner's user-level plugins and hooks. Codex's sandbox is granted the repository's git directory and the shared `uv` cache.

### 4.5 Build skills (v6)

- Each application repository defines its build skills as Markdown (`.agents/skills/<name>/SKILL.md`, with `name` and `description`), at minimum: run (how to build and drive the application in isolation), simplify, verify (exercise the behavior, not only the tests), review against the specification, and security review for high-risk paths. Its agent instructions map each to every provider's own command where one exists (for example Claude Code's `/verify`, Codex's `codex review`) and require them in the definition of done.
- Claude Code coding runs allow the `Skill` tool, so the repository skills and Claude Code's bundled ones can run inside the attempt.
- **Skills pass.** When the author of an attempt is not the configured skills runner (Claude Code by default), the orchestrator runs that runner once in the unit's worktree after the handoff is accepted and before the gates. It applies `/simplify`, `/verify` and `/code-review` (and `/security-review` for high-risk units) with the repository skills, fixes findings within the unit's scope, and commits on the unit's branch. Uncommitted leftovers are stashed, never verified. The pass never fails the attempt: the gates, reviewers and verifier that follow judge the result. The unit records `skills_pass` (runner, author, status, commits, heads).
- Configuration: `team.json` `"skills_pass": {"runner": "claude", "class": "standard", "timeout_minutes": 30}`; omit it or set `"enabled": false` to turn it off.

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
| Budget or maximum tier reached | Spend control | The delivery lead grants up to two more attempts on its own (7.1); then `needs_user` with the attempt history, the triage and the next steps |
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

### 7.1 Healing before the owner (v5)

The drive stops only when no unit can move. Before that:

- A unit the orchestrator refuses to act on (plan check, lease, routing) is set aside for the rest of the drive; the drive continues with every other unit.
- The delivery lead applies these recoveries on its own, each capped per unit for the whole run, and records them on the unit and in the drive log:

| Stopped because | Recovery | Cap per unit |
|---|---|---|
| Budget or escalation stop (`escalation_stopped`, `budget_exhausted`) | One more attempt (`budget_grant` by `delivery_lead`), with the last failure as the brief | 2 grants |
| The coder reported `blocked` (`runner_needs_user`) | One more attempt with a brief: dependencies are merged and the target was merged in; name exactly anything only the owner can change | 1, and it uses a grant |
| No reviewer or verifier answered | Back to the team review | 2 |
| Merge conflict in the queue | Back to the coder, who resolves it on top of the target | 2 |

Credentials, missing CLIs, denied tools, routing changes and a `rejected` review are never healed: they are the owner's.

### 7.2 Next steps (v5)

Every stop carries, per stuck unit, the exact command or action that unblocks it (for example `ecc resume --run-id <run> --unit <unit> --extra-attempts 1`, or the sign-in command for a CLI), followed by `ecc drive --run-id <run>`. The CLI prints them as `next:` lines; the drive state records them. The delivery lead's diagnosis accompanies them but never replaces them.

## 8. Configuration

`.orchestration/team.json` in the application repository:

```json
{
  "schema_version": "2.0",
  "merge_approval": "agents",
  "handoff_repair_turns": 1,
  "preflight": "required",
  "share_cap": 0.4,
  "roles": {
    "pr_reviewer": {"class": "unit_review_tier", "panels": {
        "economical": ["gemini", "groq", "kimi", "codex", "claude"],
        "standard": ["kimi", "gemini", "codex", "claude"],
        "advanced": ["kimi", "codex", "claude"]}, "cost_cap_usd_per_turn": 0.50},
    "security_reviewer": {"class": "advanced", "panel": ["codex", "kimi", "claude"],
        "when": "high_risk_paths_or_security_signals", "distinct_from": ["author", "pr_reviewer"],
        "cost_cap_usd_per_turn": 1.00},
    "verifier": {"class": "standard", "tools": true, "panel": ["codex", "claude"], "timeout_minutes": 30},
    "architect": {"class": "advanced", "panel": ["kimi", "codex", "gemini", "claude"],
        "when": ["milestone_start", "contract_units", "milestone_end"],
        "contract_paths": ["src/research_mcp/core/specs.py", "src/research_mcp/core/models.py",
                           "src/research_mcp/sources/base.py", "src/research_mcp/platform/migrations/**"],
        "cost_cap_usd_per_turn": 1.50},
    "designer": {"class": "standard", "images": true, "panel": ["gemini", "codex", "claude"],
        "when_paths": ["src/research_mcp/ui/**"], "cost_cap_usd_per_turn": 0.50},
    "delivery_lead": {"class": "standard", "panel": ["gemini", "groq", "kimi", "codex", "claude"],
        "when": ["budget_stop", "milestone_end"], "cost_cap_usd_per_turn": 0.25},
    "product_owner": {"class": "advanced", "pair": true, "panel": ["kimi", "codex", "claude"],
        "at": "milestone_end", "cost_cap_usd_per_turn": 2.00}
  }
}
```

Claude and Codex personas run on the owner's subscriptions; Gemini, Kimi and Groq personas are billed per token through their APIs and stay within `cost_cap_usd_per_turn`. The repository policy's `allowed_providers` lists all five; authoring is still limited to the coding CLIs by dispatch. `merge_approval` is `agents` or `human`. `human` keeps today's broker flow for repositories that want it; `my-research-mcp` uses `agents`.

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
| AT-TD-06 | Reviewer and verifier run in sessions separate from the author's, a different family when one answers (v3); verdict lines parse; a wrong head is discarded; unparsable output is re-asked once | unit |
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
| AT-TD-18 | Rotation: across a sequence of assignments each role walks its panel in order, skips ineligible providers for the stated reason (author's provider, class, context, rate limit, cost cap, expired certification, open breaker), and persists its cursor across a restart | unit |
| AT-TD-19 | Text-only personas on an API runner receive the evidence pack and return a parsable verdict; packs too large for a provider skip it | integration |
| AT-TD-20 | The security reviewer prefers a provider other than the coder's and the PR reviewer's; when none answers, the persona runs on one of theirs and the record says `independence: persona` (v3) | unit |
| AT-TD-21 | The product owner pair prefers two providers; a silent provider is skipped; a single reject rejects the milestone (v3) | integration |
| AT-TD-22 | With three or more eligible providers, no provider exceeds the share cap for a role in a milestone; the retrospective reports share, cost and agreement per provider | unit |
| AT-TD-13 | Drive ceilings (`--max-cost-usd`, `--max-hours`) stop the drive cleanly | unit |
| AT-TD-23 | A dependent unit branches from the target after its dependency merged; a retry merges the target's new commits into the unit branch first (v5) | integration |
| AT-TD-24 | A coder that reports blocked gets one delivery-lead retry and then proceeds; a second block stops with exact next steps (v5) | integration |
| AT-TD-25 | Every drive stop lists next steps ending with `ecc drive --run-id <run>`, printed as `next:` lines (v5) | unit |
| AT-TD-26 | Coding runs ignore user-level editor settings; Codex is granted the shared uv cache (v5) | unit |
| AT-TD-27 | After a non-Claude author's attempt the skills pass runs, its commits are on the branch, and the verified head is the pass's head; no pass runs for a Claude-authored unit (v6) | integration |
| AT-TD-28 | Claude Code coding runs allow the Skill tool (v6) | unit |
| OC-TD-01 | Live: `my-research-mcp` M0 completes from one `ecc drive` on the Mac; record time, cost, attempts, escalations and interventions (the Phase 6 pilot report) | owner check |

## 12. Build order

1. This spec approved (owner).
2. Orchestrator: retry loop and failure brief (5.1, 6.2), handoff-only repair (5.2), stop classification (5.3), preflight (9). Tests AT-TD-01 to 05, 12.
3. Orchestrator: persona runner (one mechanism for every reviewer, the verifier, the architect, the designer, the delivery lead and the product owner, with prompts adapted from agent-engineers), verdict parsing (6.3), panels, rotation and evidence packs (3.1, 3.2), API persona runs for Gemini, Kimi and Groq, agent merge approval (8). Tests AT-TD-06 to 09, 14 to 16, 18 to 20.
4. Orchestrator: `ecc drive` loop, milestone start and end steps, ceilings (4.2, 6.4, 7). Tests AT-TD-10, 11, 13, 15, 17, 21, 22.
5. `my-research-mcp`: add `team.json`; set `allowed_providers` to all five; update PILOT-M0 to one `ecc drive` command.
6. Live: OC-TD-01.

Steps 2 to 4 are built by hand under this spec and its tests, because the drive cannot build itself; from step 6 on, platform changes go through the drive like any other repository.

## 13. Already fixed during the pilot (kept)

| Commit | Fix |
|---|---|
| `6f96ea8` | Runner environment keeps `USER` and `LOGNAME`; Claude runner may run `uv` and `tools/ci.sh` |
| `8657bc9` | Literal handoff path in the prompt; `--add-dir` for the handoff folder |
| `12569e8` | Schema-valid handoff template and rules in the prompt |
