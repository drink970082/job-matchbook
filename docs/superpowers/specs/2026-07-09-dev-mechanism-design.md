# Design: Development mechanism for future AI sessions (PRINCIPLES + DEVELOPMENT)

**Status:** approved (brainstorming), ready to write the files directly (docs-only
change — no separate implementation plan; see Sequencing).
**Date:** 2026-07-09.

## Problem / motivation

This design was produced in a one-off session on the strongest available model
(Fable). All future development — clearing the PROGRESS backlog, new features, and
maintenance — will run on smaller models (Opus/Sonnet). The owner's two observed /
feared failure modes for those sessions:

1. **Unreliable design judgment** — wrong trade-offs, over-engineering, choices that
   don't match the project's taste (e.g. automating away a human-confirmation seam,
   adding a heavy dependency casually).
2. **Dishonest completion** — claiming done without running verification, or treating
   "tests green" as "behavior verified".

The repo already has half a mechanism, proven over three feature cycles:
`CLAUDE.md` is the auto-loaded boot vector (mandates reading SPEC + PROGRESS),
`docs/SPEC.md` carries contract-vs-snapshot semantics and an invariant→test
traceability table, `docs/PROGRESS.md` carries the severity-graded delta,
the superpowers plugin supplies the generic process (brainstorm → spec → plan →
execute), and CI enforces coverage + schema-drift + e2e gates.

What is missing is **judgment, not process**: (a) the *generative* design
principles behind SPEC §10's per-decision rationale are written nowhere — they live
in git history and the owner's head; (b) there is no written evidence standard for
"done", which is exactly the hole false completion claims crawl through.

## Goal

Bank the project's design DNA and pin the per-session workflow to an evidence-based
definition of done, as **plain repo markdown** any model or tool can follow — riding
the existing CLAUDE.md boot vector rather than adding machinery.

## Non-goals

- **No project-local skills** (`.claude/skills/`) — auto-trigger reliability on
  smaller models is the weakest link, and it would duplicate the superpowers process
  layer while binding the mechanism to Claude Code.
- **No hooks / CI hard gates** for process (e.g. "code change requires docs change") —
  the target failure modes are judgment and verification honesty, which a hook cannot
  check; discipline has not been a problem. Revisit only if doc drift actually appears.
- **No pre-designed backlog specs.** The owner explicitly chose not to bank designs
  for open-work items now (they would go stale as the code moves); every future item
  walks the design gate fresh, grounded by PRINCIPLES.
- **No duplication of superpowers content** — DEVELOPMENT references the generic
  skills where they exist; it only adds what is repo-specific.
- No new dependencies, no code changes.

## Decisions (resolved with the user)

1. **Serve all three future modes** — backlog execution, new-feature design, and
   maintenance. The mechanism is a rail, not an answer set.
2. **Defend the two chosen failure modes** — design judgment (→ PRINCIPLES.md + a
   design gate with user-decided forks) and completion honesty (→ a verify gate with
   an explicit evidence table). Process discipline and context loss were considered
   and *not* selected as targets.
3. **Form A: plain documents.** Two new docs + pointer lines in CLAUDE.md. Rejected:
   project skills (trigger reliability, duplication, lock-in) and hard gates (wrong
   failure mode, false-positive noise).
4. **This session writes the mechanism in full.** Rationale: the mechanism is prose,
   so design ≈ implementation — a spec detailed enough to transcribe faithfully costs
   as much as the files themselves, and a handoff would add one dilution step.
   Anti-context-blowup insurance is *committing early*: the repo, not the
   conversation, is the durable state.
5. **The handoff deliverable is a kickoff prompt**, instantiated from the template in
   DEVELOPMENT.md, pointing the next session at the first real task.
6. **First task = the notify-failure defect** (PROGRESS → Defects: a transient
   Telegram send error marks a `scored ≥ threshold` row `failed` and buries it).
   Small, real, carries genuine design forks (leave-`scored` vs auto-retry vs
   needs-attention view) — so it exercises every rail step and doubles as the
   mechanism's acceptance test.
7. **English**, matching every other repo doc.

## Change list

### New: `docs/PRINCIPLES.md` — design DNA

Format per principle: **name — one-line rule + why + repo exemplar + violation
smell.** The fourteen principles (approved list):

1. **Human owns the trigger** — outward/irreversible actions are human-fired
   (no auto-apply; suggest-never-auto-promote; notify only alerts).
2. **Deterministic code over LLM judgment** — if a rule can be written, write it;
   LLMs extract facts, code decides (location gate; screen facts-vs-verdict split).
3. **Err toward keep** — filters fail open: a lost job is unrecoverable, a spurious
   alert is one click (screen parse failure → keep; unresolvable location → keep).
4. **Local for frequency, Claude for judgment, cache the static** — high-frequency
   cheap checks on the host GPU; paid calls only where judgment matters; byte-identical
   cached system prefix.
5. **Fail loud into a visible queue** — breakage surfaces on a board
   (`feed_unresolved`, `detail_fetch_failed`, collapse warnings), never swallowed.
6. **One bad item never aborts the batch** — per-item try/except + `mark_failed`,
   keep going.
7. **Requests-only worker; heavy deps optional, isolated, config-gated** — climb the
   ladder (stdlib → existing dep → few lines of code) before adding; a real new dep
   ships behind config in its own module (the planned Playwright path is the template).
8. **Official APIs only; don't fight bot walls** — a wall or ToS risk means record
   and defer, not circumvent (iCIMS / ByteDance precedent).
9. **Prisma owns the schema; the worker issues no DDL** — destructive schema changes
   need a DB backup first (no migration history by design).
10. **Purity + DI in the worker; wiring only in `run.py`** — tests run with zero
    network and zero keys, forever.
11. **SQLite discipline** — WAL + `busy_timeout`, DB reads/writes on the main thread
    only, directory (not file) bind mount.
12. **Privacy red lines** — resume, `.env`, `config.yaml`, `db/` never enter git;
    the repo ships `*.example` templates only.
13. **Single-user simplicity** — no multi-tenant, no auth, no cloud beyond the three
    external APIs; rebuildable beats migratable.
14. **Defer with a recorded reason** — what we don't do gets a written why
    (PROGRESS severity grading stays honest: defects > unverified > enhancements).

Plus a **Decision procedure** section: research forks before choosing; present
forks with trade-offs + a recommendation to the user, who makes the call; record
rejected alternatives and why in the spec; new behavior lands with a SPEC §9
invariant + traceability row; when principles conflict, surface the conflict
instead of silently picking.

### New: `docs/DEVELOPMENT.md` — session protocol

- **The rail (six steps):**
  1. *Boot* — read SPEC + PROGRESS + PRINCIPLES (CLAUDE.md mandates this).
  2. *Classify* — **design-shaped** (changes behavior/invariants, adds a dep,
     touches schema, or has any open fork; no approved spec) vs **execution-shaped**
     (an approved spec/plan exists in `docs/superpowers/`) vs **maintenance**
     (restores intended behavior, no §9 invariant change). Unsure → design-shaped.
     A maintenance fix that starts wanting to change an invariant is reclassified.
  3. *Design gate* (design-shaped only) — brainstorm against PRINCIPLES; forks go
     to the user before finalizing; spec → `docs/superpowers/specs/`, plan (when
     multi-step) → `docs/superpowers/plans/`.
  4. *Implement* — TDD; keep worker purity/DI; follow the approved plan.
  5. *Verify gate* — the evidence table (below) + iron rules.
  6. *Docs + finish* — same-commit SPEC/PROGRESS/CHANGELOG updates
     (contract vs snapshot rule restated in brief); commit `type(scope):` style on
     `dev`; push `origin/dev`; master untouched.
- **Evidence table** (change touches → must run → pass bar): worker code →
  `make test-worker` (logic changes also `make test-coverage`, worker floor 85);
  web code → `make test-web` + `make lint`; cross-service/pipeline behavior →
  `make test-integration`; `schema.prisma` → `make check-schema` (+ backup warning
  for destructive changes); UI flow → `make test-e2e` or a recorded manual drive;
  §9 behavior → SPEC clause + traceability row updated same commit; docs-only →
  no test run, links + doc-set consistency.
- **Iron rules:** (1) never claim a result from a command not run this session —
  paste the output tail; (2) tests green ≠ behavior verified — drive the runtime
  surface when one exists and report what was observed; (3) the final report lists
  what changed / evidence / docs updated / **what was NOT verified and why**.
- **Cross-session handoff rule:** the repo is the handoff medium — commit
  specs/plans/state before a session ends; decisions must not live only in
  conversation.
- **Kickoff prompt template** (with a one-line model hint: design-gate work wants
  the strongest available model; execution/maintenance runs fine on smaller ones).

### Edits

- **`CLAUDE.md`** — add PRINCIPLES.md and DEVELOPMENT.md to the read-first section
  (two lines; stays lean).
- **`docs/SPEC.md` §14 References** — link both new docs.
- **`CHANGELOG.md`** — one `docs:` entry under Unreleased.
- **`docs/PROGRESS.md`** — untouched (meta-work, not a system capability or gap).

## Impact & operational risks

- **The mechanism binds only as well as models follow docs.** Accepted: the
  CLAUDE.md boot vector + read-first mandate is the same enforcement the SPEC/PROGRESS
  discipline already rides, and that has held across sessions and models.
- **Principle staleness.** Principles are generative (taste), not snapshots of code,
  so they age slowly; still, a session that deliberately overturns one (with the
  user's sign-off) must edit PRINCIPLES.md in the same commit — stated in the doc.
- **Docs-only change** — no runtime surface, no test surface; risk is limited to
  wrong guidance, mitigated by this spec review + the shakedown task.

## Testing / verification

- Docs-only: links resolve; CLAUDE.md stays lean; no code or schema touched.
- **Real acceptance test = the shakedown session:** the next session takes the
  kickoff prompt for the notify-failure defect and must walk the full rail —
  design forks surfaced to the user, evidence pasted at the verify gate, same-commit
  doc updates on `dev`. Mechanism gaps found there get folded back into the two docs.

## Sequencing

1. This spec → user review (gate).
2. Write `docs/PRINCIPLES.md` + `docs/DEVELOPMENT.md`; edit CLAUDE.md, SPEC §14,
   CHANGELOG. One commit on `dev`. (Docs-only, fully specified above — a separate
   implementation plan would restate this spec, so it is deliberately skipped;
   repo precedent: docs-only commits carry no plan.)
3. Hand the user the instantiated kickoff prompt for the notify-failure defect.
