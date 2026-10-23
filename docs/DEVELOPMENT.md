# Development protocol — the session rail

> How a development session runs in this repo — any model, any harness. The docs
> divide the load: [`SPEC.md`](./SPEC.md) says what the system *is*,
> [`PROGRESS.md`](./PROGRESS.md) what's *open*, [`PRINCIPLES.md`](./PRINCIPLES.md)
> how to *decide*, and this file how to *work*. `make help` lists every command the
> gates below use; CI runs the same gates, so local green ≈ CI green.

The rail has six steps. Steps 1, 5, and 6 apply to **every** change; 2–4 scale with
the task. [§7](#7-working-as-a-team-of-sessions) is not a step — it is how sessions
share the repo (claiming work, branches, PRs, and what a session may merge alone).

---

## 1. Boot

Read `docs/SPEC.md` (the capability map — note the contract-vs-snapshot rule in its
header), `docs/PROGRESS.md` (the live delta), and `docs/PRINCIPLES.md` (the decision
DNA). Do this before touching anything; the rest of the rail assumes it.

## 2. Classify the task

| Type | Definition | Rail |
|------|------------|------|
| **Design-shaped** | Changes behavior or a SPEC §9 invariant, adds a dependency, touches `schema.prisma`, or has *any* open fork — and no approved spec exists yet | Full rail: 3 → 4 → 5 → 6 |
| **Execution-shaped** | An approved spec (and plan, if multi-step) already exists under `docs/superpowers/` | Skip 3: execute the plan as written; a deviation discovered mid-flight goes back through 3 |
| **Maintenance** | Restores already-specified behavior without changing any invariant (clear-repro bug, doc drift, dependency bump) — or **adds tests/verification for already-specified behavior** (close the matching **(no test)** row in SPEC §9's traceability table) | Skip 3; 5–6 still apply in full |

**Unsure → design-shaped.** A maintenance fix that starts wanting to change an
invariant or add behavior is reclassified on the spot.

A spec counts as **approved** only when its `**Status:**` header line says so — a
committed spec without that line is a draft, not a license to build (committing
early as context insurance produces exactly such drafts).

## 3. Design gate *(design-shaped only)*

- Check the idea against `PRINCIPLES.md` explicitly; cite principle numbers in the
  spec. When principles conflict, surface the conflict.
- Brainstorm before building (the superpowers `brainstorming` skill, where
  available): purpose, constraints, 2–3 approaches.
- **Every fork goes to the user** with researched trade-offs and a recommendation —
  the user decides. This includes new dependencies and changed defaults.
- Write the spec to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` (rejected
  alternatives + reasons included) and commit it. Its `**Status:**` header becomes
  `approved` only after the user signs off. Multi-step work also gets a plan in
  `docs/superpowers/plans/`.

## 4. Implement

Implementation belongs to Luna at max effort under the ownership contract below.

- Test-first (red → green → refactor); one focused commit per green step where
  practical. Product order comes from ROADMAP, branch claims from PROGRESS; consult
  ARCHITECTURE before implementing target boundaries. EVALUATION scopes model checks:
  retaining a scorer does not require live model evals for unrelated docs/source/tool work.
- Hold the structural invariants while coding: worker modules stay pure + dependency-
  injected (wiring only in `run.py`); web mutations go through Server Actions; the
  worker issues no DDL. Conventions: [`../CONTRIBUTING.md`](../CONTRIBUTING.md).
- Smallest diff that satisfies the spec — no speculative abstraction.

## 5. Verify gate — evidence, not assertion

Run everything the change touches. This table **is** the verification step — no extra
self-review pass, no subagent sent to double-check work you just did. (§7's pre-merge
review is a separate gate on *merging*, not a second verification of the change.)

| Change touches | Must run | Pass bar |
|---|---|---|
| Worker code | `make test-worker` | Suite green; logic changes also run `make test-coverage` (worker floor 85) |
| Web code | `make test-web` + `make lint` | Suite green, lint clean |
| Cross-service / pipeline-stage behavior | `make test-integration` | Green |
| `schema.prisma` | `make check-schema`; **back up `db/applications.db` before destructive changes** (no migration history) | Guard green |
| UI flow | `make test-e2e`, or a manual drive with steps + observed result written down | Observed behavior matches the spec |
| Any SPEC §9 behavior/invariant | Update the §9 clause + its invariant→test traceability row | Row points at a real test, same commit |
| Docs only | No test run | Links resolve; SPEC/PROGRESS/CHANGELOG stay mutually consistent |

**Iron rules:**

1. **Never claim a result from a command not run in this session.** Paste the tail
   of the actual output into the report.
2. **Tests green ≠ behavior verified.** When the change has a runtime surface, drive
   it — worker: targeted pytest, plus a `--once` pass where real config/keys are
   set up (SPEC §12); web: `make dev`
   and click through the flow — and report what was *observed*, not what should
   happen.
3. **The final report always states:** what changed · the evidence (commands + output
   tails) · docs updated · **what was NOT verified, and why.** An honest gap beats a
   false pass.

## 6. Docs + finish

- **Same commit as the code:** update `SPEC.md` (behavior → a §4/§9 contract clause
  + test; structure → the §5–§8/§12 snapshot sections), `PROGRESS.md` (open an in-flight line
  when starting; the line *leaves* when the work lands), and `CHANGELOG.md`
  (Unreleased section). Write the clause the change needs and stop — these three
  files are reloaded every session, so padding costs the next one's context.
- **Close the spec you built from.** If the work came from a `docs/superpowers/`
  spec, move its `**Status:**` header to `shipped <date>` in the same commit. §2
  treats that line as the license to build, so a stale one misleads the next
  session about what is and isn't already live.
- Commit style: short imperative subject, `type(scope):` prefix. Keep each commit
  green.
- **Branch discipline:** see [§7](#7-working-as-a-team-of-sessions) — `main` is the
  only long-lived branch, substantive work goes on a short-lived branch cut from
  `main`, and it lands as a squash-merged PR once CI is green.
- Never commit: `apps/worker/resume/`, `.env`, `config.yaml`, `db/`
  (PRINCIPLES #12).

---

## 7. Working as a team of sessions

Sessions are the workers here, and they don't share memory — only the repo. Treat
every other session as a teammate you cannot talk to: everything they need must be
committed, and everything they left must be read before you touch it.

**The repo is the handoff medium.** Specs, plans, and progress notes are committed
before a session ends; a decision that lives only in the conversation is lost. Long
work lands as reviewable, green increments — never as an uncommitted pile a future
session must reconstruct.

### Claiming work

One branch per unit of work, named `feat/` · `fix/` · `docs/` · `chore/` + topic.
**You claim it by writing the In-flight entry in `PROGRESS.md`** naming the branch
and its state — that entry, not the branch's existence, is the claim. Before starting,
read In flight: a branch another entry describes as *landed, unmerged* is someone
else's finished work awaiting a gate, so add to it only if your change belongs to the
same unit. When your work lands, the entry leaves.

### Branch and PR rules

`main` is the only long-lived branch and is always releasable. **Everything goes through
a PR, including a one-line doc fix** — a repository rule rejects a direct push to `main`
outright (`push declined due to repository rule violations`), so the older "small doc
fixes may go straight to main" line was advice the remote does not accept. Never force-push `main`.
Releasing is an explicit, separate act — [`CONTRIBUTING.md`](../CONTRIBUTING.md)
"Branching and releases".

Each rule below was paid for by an incident on 2026-07-24:

- **Cut from `main`, and pass `--base main` explicitly.** `gh pr create` infers a base
  from the current upstream and will happily target another feature branch. Check
  `gh pr view <n> --json baseRefName` before merging — a PR that merged into the wrong
  base looks exactly like a successful merge, except `main` never got the work.
- **Fetch, then verify the local branch is not stale.** `git fetch` updates
  remote-tracking refs, *not* your local branches. Before merging into a branch, confirm
  `git rev-list --left-right --count <branch>...origin/<branch>` is `0 0`. Merging onto
  a stale local branch silently drops whatever landed on the remote.
- **Don't stack PRs.** A stacked branch carries the commits of the PR below it; once
  that one squash-merges, `main` holds a *different* commit with the same content and
  every later PR conflicts. If stacking is unavoidable, merge bottom-up and expect it.
- **Resolving a squash-divergence conflict:** the content is usually identical, so
  resolve per hunk taking the newer side — never a blanket `--ours`/`--theirs`, which
  discards the auto-merged parts of the file. Then check two things a mechanical
  resolution gets wrong: a hunk where **both** sides are wanted, and a **closed** item
  being reintroduced (a stale branch's PROGRESS can re-open work that same branch
  shipped).
- **Never switch branches while a long run is in flight.** The worker imports from the
  working tree, so a switch silently changes the code under the next chunk.

### Authority — what a session decides alone

| Do it | Ask first |
|---|---|
| Create a branch, commit, push it, open a PR | Merging a PR whose review raised anything unresolved |
| **Merge your own PR — CI green *and* a passing fresh-subagent review (below)** | Merging **another session's** work |
| Resolve conflicts; keep SPEC/PROGRESS/CHANGELOG in sync | Force-push anything; deleting unmerged work |
| Record a defect you found instead of fixing it | Tags and releases |
| Anything free and reversible | Reverting another session's commit |
| | Anything that **spends money or quota** |

The split is a normal team's: a dev opens and merges their own work once it has passed
review, and everything irreversible or shared stays with the operator. An operator who
says "just merge" has authorized *that* merge, not a standing one.

### The review is a fresh subagent, never the author

**A session must not review its own PR.** Having written the diff, it re-reads its own
intent instead of the code: it already believes the edge case is handled, so it checks
that the code matches the plan rather than that the plan was right. That is the failure
mode a review exists to catch, and it is exactly the one an author cannot catch.

So before self-merging, dispatch a **fresh subagent** and give it only what a reviewer
would have:

- the diff (`git diff main...HEAD`), the branch's commits, and the spec or PROGRESS
  entry the work claims to satisfy;
- **not** the working session's reasoning, its justifications, or its summary of what
  the change does. Those are the very claims under review.

Ask it to find defects, not to confirm the work. Treat what it returns the way the
`superpowers:receiving-code-review` skill does — verify the technical claims rather than
implementing or dismissing them on sight; a reviewer with no context also has no
context, and some findings will be wrong. **Any finding that survives verification
blocks the merge** until it is fixed or the operator waives it.

If no subagent capability is available in the session, the merge goes to the operator.
"CI is green" is not a review: CI proves the suite passes, which is a claim about the
tests, not about whether the change is right.

### Issues and repository documents

GitHub issues own deliverable scope, dependencies, acceptance checklists and open/closed
status. ROADMAP owns product order and links issues; PROGRESS owns active branch claims
and current implementation limitations; BACKLOG owns unselected ideas, linking a ticket
rather than duplicating its status. Plans own execution detail. Shipped behavior belongs
in SPEC and completion history in CHANGELOG.

Only assign an issue when its dependencies and scoped plan are ready. `enhancement` and
`documentation` classify issues; neither label means ready to execute. Conditional issues
remain deferred until their stated selection/design gate is met. An implementation PR
references its issue; close it only after the orchestrator accepts the deliverable.
Planning/documentation PRs must not auto-close future implementation tickets.

## Agent ownership and handoff

- **Astra/Sol orchestrator:** owns documentation, architecture, issue decomposition,
  contracts, scope decisions, acceptance and merge coordination. It may inspect code and
  run checks, but does not implement production code/tests or patch review findings.
- **Luna, max effort:** owns all implementation and corrective patches. Start from current
  main in an isolated branch/worktree, execute one selected issue and its approved plan,
  run relevant checks, update shipped-behavior docs and open a PR. Do not self-merge or
  deploy. Implementation model/effort is distinct from the runtime Luna/medium screener.
- The orchestrator supplies the issue, plan revision, dependency state, allowed changes,
  forbidden side effects, acceptance cases and required evidence. Luna reports actual
  commands/results, remaining risks and deviations; unresolved design changes return to
  Astra/Sol. Findings go back to Luna for fixes, then to acceptance again.
- A fresh Astra/Sol reviewer checks the exact PR head against the contract and evidence;
  the author is not its own reviewer. Green CI plus acceptance allows orchestrator merge
  under §7. Deployments and live model workloads need separately established scope.
- The selected implementation issue may run in goal mode as requested by the operator;
  the goal is the bounded issue/PR deliverable, not all roadmap items. A goal is created
  only for an explicitly assigned goal-mode run. Never interpret a remaining backlog as
  permission to start another issue, change models, spend evaluation quota or clean data.

## Session kickoff template

Start a development session with this prompt (fill the angle brackets):

```text
Read docs/SPEC.md, docs/PROGRESS.md, docs/PRINCIPLES.md, then follow
docs/DEVELOPMENT.md as the working protocol.

Task: <one line — what and why now>
Type: <design-shaped | execution-shaped | maintenance> — self-check against
DEVELOPMENT.md §2; if unsure, treat as design-shaped.

Non-negotiables:
- Design forks come to me with researched trade-offs and your recommendation
  before you finalize anything (PRINCIPLES.md, Decision procedure).
- Scope is the ask: raise a concern in a sentence and keep going; don't widen,
  narrow, or transform the task on your own.
- Definition of done = the §5 evidence table for everything you touched, plus
  same-commit doc updates per §6.
- Branch off main for anything substantive; land it as a squash-merged PR with
  CI green. Never force-push main.
- Your final report must state what you did NOT verify.
```

Agent assignment follows the ownership contract above. Astra/Sol handles orchestration;
Luna at max effort handles implementation. This overrides older model-agnostic or
Claude-specific implementation defaults for the pivot workstream.
