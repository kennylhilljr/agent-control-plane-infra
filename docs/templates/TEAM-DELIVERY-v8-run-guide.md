# TEAM-DELIVERY v8 run guide: `<run name>`

- **Status:** Draft
- **Run ID:** `<assigned after create-run>`
- **Policy:** `docs/TEAM-DELIVERY-v8.md` at `<revision>`
- **Repository:** `<owner/repository>`
- **Target branch:** `<branch>`
- **Target base SHA:** `<sha>`
- **Plan revision/hash:** `<pointer and hash>`
- **Prepared by:** `<delivery lead>`
- **Last updated:** `<ISO-8601 timestamp>`

Copy this template into the run's durable record location. Replace every placeholder or mark it `not applicable` with a reason. Do not add credentials, transcripts, or unrestricted machine output.

The labels `create-run`, `trace-check`, and `test-plan gate` describe workflow capabilities. In the evidence fields below, link the actual supported command or write the manual procedure used for this run.

## Roles

| Role | Person or durable agent identity | Contact or record pointer |
| --- | --- | --- |
| Owner | `<required>` | `<pointer>` |
| Delivery lead | `<required>` | `<pointer>` |
| Architect | `<required>` | `<pointer>` |
| Product reviewer | `<required>` | `<pointer>` |
| Work-unit owners | `<required>` | `<unit table or pointer>` |
| Composition owners | `<required>` | `<wiring rows or pointer>` |

## Approved inputs

| Input | Revision/hash | Approval or evidence pointer |
| --- | --- | --- |
| LLD | `<revision>` | `<owner approval>` |
| Delivery plan | `<hash>` | `<plan record>` |
| Repository rules | `<revision>` | `<AGENTS.md path>` |
| Test plan | `<revision>` | `<gate pointer>` |
| Rollback plan | `<revision>` | `<pointer>` |

## Plan readiness gate

Complete in order. A changed plan hash clears every later checkbox.

- [ ] Delivery lead built the plan from the approved LLD.
- [ ] Deterministic lint passed with zero errors.
  - Evidence: `<plan hash, ruleset/version, result pointer>`
- [ ] Architect completed a standalone plan check.
  - Result: `<pass or findings>`
  - Evidence: `<architect, plan hash, record pointer, timestamp>`
- [ ] All architect findings were resolved and the final hash was checked again.
  - Evidence: `<pointer>`
- [ ] Owner explicitly approved the same plan hash and target base.
  - Evidence: `<owner, plan hash, target SHA, conditions, timestamp>`
- [ ] Run creation produced a durable run ID and immutable plan pointer.
  - Supported command or manual procedure: `<procedure>`
  - Evidence: `<pointer>`

## Provides declarations

| ID | Kind | Name and location | Providing unit/owner | Signature, schema, or boundary | Available after | Verification |
| --- | --- | --- | --- | --- | --- | --- |
| `<P-01>` | `<symbol/table/job/wiring>` | `<name, path>` | `<unit, owner>` | `<contract>` | `<unit/milestone>` | `<pointer>` |

## Requires declarations

| ID | Kind | Consuming unit | Provider ID/unit | Expected contract | Needed before | Consumer verification |
| --- | --- | --- | --- | --- | --- | --- |
| `<R-01>` | `<symbol/table/job/wiring>` | `<unit>` | `<P-01, unit>` | `<expectation>` | `<stage>` | `<pointer>` |

## Composition wiring ownership

| Wiring surface | Composition owner/unit | Required provider IDs | Integration check | Scope paths |
| --- | --- | --- | --- | --- |
| `<bootstrap, registry, route, plugin, or config surface>` | `<one owner and unit>` | `<P-IDs>` | `<test-plan pointer>` | `<repository-relative paths>` |

## Milestones and units

| Milestone | Contract-first unit | Entry gate | Exit gate | Status |
| --- | --- | --- | --- | --- |
| `<M1>` | `<M1-C0>` | `<approved plan/run state>` | `<close evidence>` | `<planned/active/closing/closed>` |

For each milestone, copy the sections below.

### `<M1>` contract-first unit

- Unit ID and owner: `<M1-C0, owner>`
- Branch and worktree: `<branch, path or worktree ID>`
- Scope: `<repository-relative paths>`
- Cross-unit types and protocols: `<Provided IDs or explicit none>`
- Store signatures: `<Provided IDs or explicit none>`
- Contract checks: `<commands/manual steps and expected results>`
- Consumer handoffs: `<Requires IDs and pointers>`
- Integration evidence: `<commit/merge record>`
- Status: `<planned/active/passed/blocked>`

If there is no cross-unit contract, record the architect's rationale and test-plan pointer: `<rationale and pointer>`.

### `<M1>` work units

| Unit | Owner | Branch | Scope | Provides | Requires | Wiring owned | Checks | Status/evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `<M1-U1>` | `<owner>` | `<branch>` | `<paths>` | `<P-IDs>` | `<R-IDs>` | `<surface or none>` | `<test pointer>` | `<state, pointer>` |

## Active-milestone hygiene declaration

- [ ] Each owner works only on the assigned unit branch.
- [ ] No contributor or automation pushes to or pulls the target branch while the milestone is active.
- [ ] Editor/IDE auto-sync, auto-pull, auto-push, and background branch updates are off.
- [ ] The automation configuration preserves and reports changes outside all active unit scopes.
- [ ] Scope overlaps have an explicit serialization rule or are removed.
- [ ] Unit evidence records branch, head SHA, procedure, result, and artifact pointer.

Repository-specific setup needed to enforce these rules: `<steps and evidence>`

## Evidence index

| Evidence ID | Decision supported | Actor | Input revision/SHA | Result | Artifact pointer |
| --- | --- | --- | --- | --- | --- |
| `<E-01>` | `<decision>` | `<actor>` | `<revision>` | `<pass/fail/state>` | `<pointer>` |

## Milestone close

The delivery lead completes these steps in order:

- [ ] Stop new dispatch and capture every unit's row, branch, head, handoff, and merge evidence.
- [ ] Mark merged rows `done`; leave every other row in its actual state.
- [ ] Run traceability with all planned tasks due.
  - Supported command or manual procedure: `<procedure>`
  - Plan hash and result: `<hash, result>`
  - Evidence: `<pointer>`
- [ ] Verify the test-plan gate pointer resolves to the exact required revision and result set.
  - Pointer and resolved revision: `<pointer, revision>`
  - Evidence: `<pointer>`
- [ ] Draft the handoff with integrated refs, contract and wiring changes, checks, exceptions, rollback, and evidence index.
  - Handoff: `<pointer>`
- [ ] Write complete owner-check procedures below.
- [ ] Send the handoff to the owner and wait for target-branch results.
- [ ] Confirm every owner result is tied to the expected target SHA and passes.
- [ ] Begin product review only after the owner checks pass.
- [ ] Record product acceptance or reopen the milestone.
- [ ] Owner performs the final target-branch push and records the remote result.

## Owner checks on the local target branch

The owner runs these steps without pulling the target branch. Add one subsection per check.

### `<check name>`

- Working directory: `<path>`
- Expected target branch and SHA: `<branch, sha>`
- Preconditions: `<complete setup>`
- Steps: `<exact command sequence or manual actions>`
- Expected success result: `<exit status, output summary, or observed behavior>`
- Evidence to capture: `<artifact and pointer>`
- On failure: `<stop, rollback or preserve-state steps, and escalation destination>`
- Owner result: `<pending/pass/fail, actor, tested SHA, timestamp, evidence>`

## Product review and final push

- Product-review input SHA: `<sha>`
- Product reviewer and result: `<identity, pending/accepted/rejected>`
- Product-review evidence: `<pointer>`
- Owner final-push procedure: `<procedure; no delegated push>`
- Pushed SHA and remote result: `<pending or evidence>`

## Stop conditions, exceptions, and resume evidence

| Time | Condition or exception | Work stopped | Decision owner | Corrective action | Resume evidence |
| --- | --- | --- | --- | --- | --- |
| `<timestamp>` | `<condition>` | `<units/milestone>` | `<role>` | `<action>` | `<pointer>` |

## Tracking links

- Infrastructure issue: `<link>`
- Runtime implementation issue(s): `<link(s); do not mark complete from this guide>`
- Application delivery issue(s): `<link(s); retain independent acceptance evidence>`
