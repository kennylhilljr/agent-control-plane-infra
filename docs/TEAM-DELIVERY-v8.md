# TEAM-DELIVERY v8

- **Status:** Approved by the owner on 2026-10-29 (revision: blob `f25f665b1e4d` at `a09a637`)
- **Applies to:** Milestone-based delivery coordinated by `openclaw-ecc-orchestrator`
- **Authority:** This document specializes `MIGRATION_SPEC.md`. The migration specification and repository `AGENTS.md` files take precedence if their rules conflict with this draft.

TEAM-DELIVERY v8 defines the records and gates needed to turn an approved low-level design (LLD) into an auditable delivery run. It does not define platform architecture, routing policy, or general Git safety; those remain in `MIGRATION_SPEC.md`.

The workflow labels `create-run`, `trace-check`, and `test-plan gate` name required capabilities. They do not assert that a command with that name exists. A run guide must point to the supported runtime command or document the manual equivalent used to produce the same evidence.

## Assign one accountable role to every gate

| Role | Accountable work | Approval boundary |
| --- | --- | --- |
| Owner | Approves the LLD and final delivery plan, performs the target-branch checks, accepts product review, and makes the final target-branch push. | The owner is the only role in this workflow that can grant owner approval. This draft grants none. |
| Delivery lead | Builds the delivery plan and run guide, maintains unit status, enforces the gate order, owns milestone close, and prepares the evidence handoff. | May stop or reopen work, but cannot substitute for the architect check or owner approval. |
| Architect | Performs the standalone plan check after deterministic lint passes. | Records a pass or findings. An architect pass is not owner approval. |
| Work-unit owner | Works only on the assigned unit branch and scope, runs declared unit checks, and writes the unit handoff. | Cannot move the target branch or approve the overall plan. |
| Composition owner | Owns the declared composition-root changes and their integration tests. This may be a work-unit owner with an explicit wiring assignment. | No other unit may edit the same wiring surface during the milestone. |
| Product reviewer | Reviews the integrated product behavior after target-branch checks pass. | Cannot waive failed gates or perform the final push for the owner. |
| Automation or orchestrator | Performs deterministic validation, records state and evidence, detects scope conflicts, and invokes supported gates. | Cannot infer an approval, silently repair a failed gate, or discard changes outside an active unit's scope. |

The run guide must name people or durable agent identities for every role used in the run. A blank role is a stop condition, not an implied assignment.

## Keep delivery records addressable

Every input and result must have a stable pointer. A pointer contains the repository, revision or plan hash, path or record ID, and the relevant section when the artifact is larger than the referenced decision. Use timestamps as supporting metadata, not as the only identity.

The delivery record set contains:

- the approved LLD and its approval evidence;
- the delivery plan and exact plan hash;
- deterministic lint results;
- the architect plan-check record;
- owner plan-approval evidence;
- the run guide generated from the template;
- work-unit rows and structured handoffs;
- the test-plan gate definition and results;
- milestone-close and target-branch evidence.

Do not put credentials, transcripts, provider tokens, or unrestricted machine state in these records.

## Pass the plan readiness gate before creating a run

Plan readiness begins only after the LLD is approved. The delivery lead must stop if the LLD pointer or its approval evidence is missing.

| Order | Gate | Actor | Input | Required output |
| ---: | --- | --- | --- | --- |
| 1 | Build delivery plan | Delivery lead | Approved LLD, repository rules, test plan, milestone scope | Versioned plan with units, dependencies, scopes, Provides/Requires declarations, wiring ownership, risks, and evidence locations |
| 2 | Deterministic plan lint | Automation | Exact plan candidate | Machine-readable result tied to the plan hash; zero errors |
| 3 | Standalone architect plan check | Architect | Lint-passing plan and LLD | Separate pass/fail record with reviewer identity, findings, plan hash, and timestamp |
| 4 | Owner plan approval | Owner | Plan, lint result, architect record, unresolved-risk list | Explicit approval tied to the same plan hash |
| 5 | Create run | Delivery lead or automation | Approved plan and approval record | Durable run ID, immutable plan pointer, target base, and initial state |

The order is mandatory. A plan change after lint invalidates the lint result. A material plan change after the architect check also invalidates the architect result. Any plan change after owner approval requires the approval to be repeated against the new hash.

### Make deterministic lint reproducible

Plan lint must produce the same result from the same inputs and check at least:

- unique unit, milestone, contract, and evidence IDs;
- a complete, acyclic dependency graph;
- declared scopes that use repository-relative paths and do not overlap without an explicit serialization rule;
- a provider for every Required contract and a compatible kind and signature;
- exactly one owner for every composition-wiring surface;
- a contract-first unit at the start of every milestone;
- test-plan and rollback pointers for every unit;
- known roles, branches, target base, and evidence destinations;
- no unit scheduled before its Required contracts become available.

Lint failure blocks the architect check. The result must list each error with a stable rule ID and the affected plan location.

### Run the architect check as a separate decision

The architect checks design fitness that deterministic lint cannot establish:

- the unit boundaries preserve the approved LLD;
- Provides and Requires declarations cover the actual cross-unit surface;
- the contract-first unit is sufficient to unblock consumers without hiding feature work;
- store signatures define ownership, transaction boundaries, and error behavior where applicable;
- composition ownership covers registration, bootstrap, configuration mapping, and integration tests;
- dependencies reflect delivery order rather than convenience;
- the test plan can prove integration behavior and rollback.

The architect records either `pass` or `findings`. Findings must be resolved in the plan, followed by fresh lint and another architect check. The architect does not approve on the owner's behalf.

### Require explicit owner approval

Owner approval must identify the owner, plan hash, approved target base, timestamp, and any conditions. Missing, stale, or conditional approval whose conditions have not been met blocks run creation. The status of this document is `Draft`; it is not owner-approved by publication or by its presence in the repository.

## Declare cross-unit contracts with Provides and Requires

Every cross-unit dependency uses a paired declaration. Prose descriptions may explain the contract, but they do not replace the declaration.

Each `Provides` entry records:

- contract ID and kind;
- name and canonical repository location;
- providing unit and accountable owner;
- public signature, schema, or wiring boundary;
- milestone and point at which it becomes available;
- verification pointer.

Each `Requires` entry records:

- contract ID and kind;
- consuming unit;
- provider contract ID and providing unit;
- expected signature, schema version, or behavior;
- the stage before which it must be available;
- consumer-side verification pointer.

Use one of these contract kinds:

| Kind | Declaration covers | Minimum contract detail |
| --- | --- | --- |
| `symbol` | Exported types, functions, classes, constants, protocols, or events | Qualified name, signature or shape, ownership, compatibility rule |
| `table` | Database tables, views, durable files, or equivalent stored records | Schema/version, keys, reader/writer ownership, migration and compatibility rule |
| `job` | Scheduled, queued, or event-driven jobs | Trigger, input/output, retry behavior, idempotency, failure reporting |
| `wiring` | Dependency registration, composition roots, bootstrap, routes, plugin registration, or configuration mapping | Wiring location, composition owner, providers and consumers joined, integration check |

A Required declaration cannot point to a general milestone or team. It must point to one Provided contract. One Provided contract may serve several consumers, but every consumer lists its own requirement and verification.

Undeclared cross-unit imports, table access, job invocation, or composition edits stop the affected unit. The delivery lead updates the plan and repeats the readiness gates when the dependency changes the approved plan.

## Start every milestone with a contract-first unit

The first unit in each milestone is the contract-first unit. It establishes the cross-unit types, protocols, and store signatures that units in that milestone share. Dependent implementation units do not start until this unit passes its checks and is integrated into the milestone base through the approved integration path.

The contract-first unit may contain:

- shared type and protocol definitions;
- store interfaces and signatures, including transaction and error behavior;
- schema or event definitions;
- compatibility fixtures and contract tests;
- the finalized Provides/Requires rows for the milestone.

It must not conceal feature behavior, opportunistic refactoring, or composition wiring that belongs to a named implementation unit. If a milestone has no cross-unit contract, the unit still exists as a record and returns an explicit `no cross-unit contract` result with the architect's rationale and a test-plan pointer.

The unit output includes the contract revision, checks and exact results, affected declarations, integration evidence, and a handoff to every consumer. Missing signatures, incompatible consumers, unresolved ownership, or failing contract tests block the milestone.

## Give composition wiring one owner

Every composition surface has exactly one owner for the milestone. The plan must name the owner before implementation begins and include the surface in that unit's scope.

The composition owner:

1. Requires the contracts for every component being joined.
2. Owns registration, bootstrap, route or plugin attachment, and configuration mapping in the declared composition surface.
3. Adds or updates an integration check that exercises the resulting wiring.
4. Records the exact files and evidence in the unit handoff.

Provider units do not edit composition surfaces unless the plan also assigns them composition ownership. Shared ownership, implicit ownership by the last unit, and wiring added during milestone close are stop conditions.

## Enforce run hygiene during active milestones

These rules apply from milestone open until the delivery lead begins the close procedure:

1. Each work-unit owner edits and commits only on the branch assigned to that unit. Branch changes require a recorded reassignment or handoff.
2. No contributor or automation pushes to or pulls the target branch. Read-only fetches may observe remote state, but they must not update the target checkout or a unit branch implicitly.
3. Editor and IDE auto-sync, auto-pull, auto-push, and background branch-update features remain off for the repository.
4. Automation tolerates existing or concurrent changes outside the union of every active unit's declared scope. It must preserve and report them, not add, revert, clean, or classify them as a unit failure.
5. A change that overlaps an active unit's scope without belonging to its assigned branch stops that unit for conflict review.
6. Unit checks run from the assigned worktree and record the branch, head SHA, command or manual procedure, exit status, and relevant artifact pointer.

If a hygiene rule is violated, stop dispatch and preserve all worktrees. The delivery lead records the observed refs and paths, resolves ownership without deleting unique work, and documents the new base or reassignment before work resumes.

## Close each milestone through the delivery lead

The delivery lead owns the close procedure. Run these steps in order:

1. Stop new dispatch and collect the current row, branch, head, handoff, and merge evidence for every milestone unit.
2. Mark only merged rows `done`. Each completed row must point to its integrated commit or merge record. Leave unmerged, skipped, or failed rows in their truthful state.
3. Perform the traceability check with all planned tasks treated as due, including blocked and deferred rows. If the runtime has no supported `trace-check` command, compare the LLD, plan, unit rows, contracts, tests, and evidence manually and record the method. Any missing task or evidence fails close.
4. Verify that the test-plan gate pointer resolves to the exact test-plan revision and required result set for this milestone. A moving branch name or an unversioned path is insufficient by itself.
5. Draft the milestone handoff. Include integrated refs, Provides/Requires changes, wiring evidence, exact checks and results, known failures, scope exceptions, rollback instructions, and the evidence index.
6. List owner checks as complete procedures. Each procedure includes the working directory, expected target ref and SHA, prerequisites, exact steps, expected success result, captured evidence, and what to do on failure. Do not instruct the owner to pull the target branch.
7. Give the handoff to the owner and wait. The owner runs the checks on the local target branch and returns results tied to the tested SHA.
8. Begin product review only after every required owner check passes on that target SHA. Failed or missing results reopen the milestone.
9. After product acceptance and all repository protections are satisfied, the owner performs the final target-branch push. Record the pushed SHA and remote result.

Delivery-lead preparation, automated checks, owner checks, product acceptance, and the final push are separate evidence events. One event cannot stand in for another.

## Record enough evidence to reproduce each decision

| Decision | Required evidence |
| --- | --- |
| Plan lint passed | Plan hash, lint ruleset/version, result, rule findings, artifact pointer |
| Architect check passed | Architect identity, plan hash, result, findings disposition, timestamp |
| Owner approved plan | Owner identity, plan hash, target base, conditions, timestamp |
| Contract-first unit passed | Contract revision, declarations, checks, integration ref, consumer handoffs |
| Unit completed | Unit branch and head, declared scope, files changed, commands and results, handoff, merge evidence |
| Milestone closed | Truthful row states, all-due trace result, test-plan gate pointer, handoff, owner-check procedures |
| Target checks passed | Owner identity, target SHA, exact steps and results, artifacts, timestamp |
| Product accepted and pushed | Product-review result, owner identity, pushed SHA, remote response |

Machine-readable evidence is preferred when the runtime supports it. Manual evidence must still identify the actor, inputs, procedure, output, and time.

## Stop rather than infer missing state

Stop plan or run progression when any of these conditions is present:

- the approved LLD, plan hash, target base, role assignment, or required evidence pointer is missing;
- deterministic lint fails or its result does not match the current plan;
- the architect has unresolved findings;
- owner approval is absent, stale, or attached to a different plan;
- a Required contract lacks a compatible provider;
- a milestone contract-first unit or composition owner is missing;
- work begins outside the assigned branch or scope;
- target-branch push/pull or editor auto-sync occurs during an active milestone;
- automation would need to alter changes outside all active scopes;
- a required check fails, the test-plan pointer does not resolve, or traceability is incomplete;
- owner target-branch results are missing or tied to another SHA;
- a secret or other prohibited artifact appears in delivery evidence.

Resume only after the corrective action and new evidence are recorded. Never convert an unknown state into a pass.

## Use the reusable run guide

Create each run guide from [`templates/TEAM-DELIVERY-v8-run-guide.md`](templates/TEAM-DELIVERY-v8-run-guide.md). Keep run-specific facts in the copied guide and keep policy here. Orchestrator issues should reference this file for the policy and the run guide for the concrete plan, rather than copying sections into issue descriptions.

## Track issues without overstating implementation

| Issue | Documentation status | Remaining boundary |
| --- | --- | --- |
| #4 | The draft defines plan readiness, deterministic lint, a standalone architect check, Provides/Requires, contract-first milestone units, and composition ownership. | Owner review and approval remain pending. Orchestrator enforcement belongs in linked runtime work. |
| #5 | The draft defines active-run hygiene, delivery-lead milestone close, owner target checks and final push, plus a reusable run-guide template. | Runtime support and adoption must be verified in their own issues. |
| #6 | Tracking reference only. | It does not make linked infrastructure, runtime, or application issues complete. Each linked issue retains its own evidence and acceptance decision. |
