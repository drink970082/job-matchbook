# Development protocol — the session rail

> How a development session runs in this repo — any model, any harness. The docs
> divide the load: [`SPEC.md`](./SPEC.md) says what the system *is*,
> [`PROGRESS.md`](./PROGRESS.md) what's *open*, [`PRINCIPLES.md`](./PRINCIPLES.md)
> how to *decide*, and this file how to *work*. `make help` lists every command the
> gates below use; CI runs the same gates, so local green ≈ CI green.

The rail has six steps. Steps 1, 5, and 6 apply to **every** change; 2–4 scale with
the task.

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
| **Maintenance** | Restores already-specified behavior without changing any invariant (clear-repro bug, doc drift, dependency bump) — or **adds tests/verification for already-specified behavior** (close the matching ⚠ row in SPEC §9's traceability table) | Skip 3; 5–6 still apply in full |

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

- Test-first (red → green → refactor); one focused commit per green step where
  practical.
- Hold the structural invariants while coding: worker modules stay pure + dependency-
  injected (wiring only in `run.py`); web mutations go through Server Actions; the
  worker issues no DDL. Conventions: [`../CONTRIBUTING.md`](../CONTRIBUTING.md).
- Smallest diff that satisfies the spec — no speculative abstraction.

## 5. Verify gate — evidence, not assertion

Run everything the change touches:

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
  + test; structure → the §5–§8/§12 snapshot sections), `PROGRESS.md` (open a 🚧 line
  when starting; the line *leaves* when the work lands), and `CHANGELOG.md`
  (Unreleased section).
- **Close the spec you built from.** If the work came from a `docs/superpowers/`
  spec, move its `**Status:**` header to `shipped <date>` in the same commit. §2
  treats that line as the license to build, so a stale one misleads the next
  session about what is and isn't already live.
- Commit style: short imperative subject, `type(scope):` prefix. Keep each commit
  green.
- **Branch discipline:** `main` is the only long-lived branch and is always
  releasable. Substantive work goes on a short-lived `feat/` · `fix/` · `docs/` ·
  `chore/` branch cut from `main`, lands via a squash-merged PR once CI is green,
  and the branch is deleted. Small doc fixes may go straight to `main`. Never
  force-push `main`. Releasing is an explicit, separate act — see
  [`CONTRIBUTING.md`](../CONTRIBUTING.md) "Branching and releases".
- Never commit: `apps/worker/resume/`, `.env`, `config.yaml`, `db/`
  (PRINCIPLES #12).

---

## Cross-session handoff

**The repo is the handoff medium.** Specs, plans, and progress notes are committed
before a session ends; a decision that lives only in the conversation is lost. Long
work lands as reviewable, green increments — never as an uncommitted pile a future
session must reconstruct.

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
- Definition of done = the §5 evidence table for everything you touched, plus
  same-commit doc updates per §6.
- Branch off main for anything substantive; land it as a squash-merged PR with
  CI green. Never force-push main.
- Your final report must state what you did NOT verify.
```

*Model hint:* design-gate work benefits from the strongest model available;
execution-shaped and maintenance sessions run fine on smaller ones.
