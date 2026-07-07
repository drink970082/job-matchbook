# Design: Remove résumé tailoring — pipeline ends at score → notify

**Date:** 2026-07-06
**Status:** Approved (design) — pending implementation
**Scope:** Remove the tailor stage end-to-end. Follows the scoring spec
(`2026-07-05-claude-scoring-design.md` §8, which deferred this).

## Problem / motivation

The tailor stage (Claude + tectonic, per-posting single-page loop) writes a
tailored PDF for every match. The user no longer wants machine-tailored resumes:
they apply by hand and only need the *alert*. Tailoring adds cost (an Anthropic
call per match, several rounds), a heavy Docker dependency (tectonic), a shared
`resumes/` volume, three DB columns, a PDF route, and a whole pipeline stage —
all for output the user doesn't use.

## Goal

Collapse the pipeline `new → scored → tailored → notified` to
**`new → scored → notified`**. The score threshold (75) that used to gate
*tailoring* now gates *notification*. Telegram sends a message-only alert
(company / role / score / link — no PDF).

## Non-goals

- Scoring, screening, fetch, feed — untouched.
- The `matched_keywords` / `missing_keywords` score outputs **stay** (see
  Decision 3).

## Decisions (resolved with the user)

1. **Notification gating → threshold (75).** `run_notify` processes `scored`
   rows with `score ≥ cfg.threshold`. Below-threshold rows stay `scored`
   (exactly as they do under tailoring today). Preserves current alert volume.
2. **Full removal, not soft.** Drop the `resume_tex` / `resume_path` /
   `resume_pages` columns, the `/api/resume/[id]` route, the download UI, the
   `tailored` pipeline status, and the tectonic dependency. This is a
   **destructive schema change** with no migration history → **back up
   `db/applications.db` before `make db-push`** (PROGRESS "No schema migration
   path").
3. **Keep the score keywords.** The scoring spec called `matched_keywords` /
   `missing_keywords` "orphaned" — that was wrong. `JobDetailModal` still
   displays them as fit signal (with a regression-guard test). Only tailoring's
   consumption of `missing_keywords` goes away. `score.py` output, the modal, and
   its test are **unchanged**.
4. **Notify-failure defect stays out of scope.** Removing the PDF makes notify a
   single atomic `sendMessage`, which *would* make the documented "transient
   notify failure buries prepared work" defect (PROGRESS) cheap to fix here. We
   deliberately do **not** — `run_notify` keeps marking a row `failed` on a
   Telegram error, exactly as today. Scope stays "remove tailoring." The defect
   is milder post-removal (no PDF is lost) and gets its own spec. PROGRESS is
   restated to reflect the reduced-but-present defect (see Docs).

## Change list

### Worker

**Delete**
- `ats_worker/tailor.py` (whole module)
- `ats_worker/prompts/tailor.txt`
- `prompts.py`: the `_t = _sections("tailor.txt")` line + `FABRICATION_GUARD`,
  `BASE_PROMPT`, `FEEDBACK_PROMPT`. Keep `_s` / `score.txt` + the SCREEN clauses.
- `pipeline.run_tailor`
- `db.save_resume`
- `run.py`: `tailor_fn` + `_claude_cell`, the `_missing_keywords` helper, the
  `resume_out_dir` helper, `make_claude`/`tectonic_compile`/`pypdf_count`/
  `tailor_resume` import, `DEFAULT_ANTHROPIC_MODEL`, `--anthropic-model` arg,
  `master_tex` reading + `--master-tex`, `resume_dir` / `--resume-dir` /
  `RESUME_DIR` (no PDFs are written anymore). `run_once` loses the `master_tex`,
  `resume_dir`, `anthropic_model` params. **Keep** `resume_text` / `--resume` —
  the *scorer* still consumes `resume.txt`. Keep `ANTHROPIC_API_KEY` (scorer).
- `config.py`: `max_single_page_rounds` + `DEFAULT_MAX_SINGLE_PAGE_ROUNDS`.

**Modify**
- `pipeline.run_notify(conn, threshold, *, now, notify_fn, token, chat_id)`:
  read `db.get_by_status(conn, "scored", min_score=threshold)`; call
  `notify_fn(posting, token=..., chat_id=...)` (no PDF); advance to `notified`.
  **Keep** the existing `try/except → db.mark_failed` (Decision 4 — no defect
  fix). Update the module docstring's stage-gating block.
- `notify.py`: drop the `pdf_path` param and the `sendDocument` branch →
  message-only. Update docstring (no attachment).
- `run.py`: pass `threshold=cfg.threshold` to `run_notify`; `run_once` docstring
  "fetch → score → notify".
- `config.yaml` + `.example`: remove `max_single_page_rounds`; reword the
  `threshold` comment ("match/notify threshold", no longer "tailoring").
- `util.py`: comment "score/tailor fill the rest" → "score fills the rest".
  (Dockerfile / compose changes are under Infra.)

**Tests**
- Delete `tests/test_tailor.py`.
- `test_pipeline.py`: drop `run_tailor` tests; update `run_notify` (reads
  `scored` ≥ threshold, message-only).
- `test_notify.py`: drop `sendDocument` / PDF assertions.
- `test_db.py`: drop the `save_resume` test.
- `test_run.py`: update wiring (no tailor_fn / master_tex / resume_dir).
- `integration/test_pipeline_e2e.py`: drop the tailored stage; assert
  `scored ≥ threshold → notified` directly.
- `tests/fixtures/schema.sql`: drop `resume_tex` / `resume_path` /
  `resume_pages` (mirror `schema.prisma`; `make check-schema` enforces parity).

### Web (+ shared schema)

**Schema — destructive, back up `db/applications.db` first**
- `prisma/schema.prisma`: drop `resume_tex` / `resume_path` / `resume_pages`;
  update the `pipeline_status` comment (remove `tailored`). Then `make db-push`.
- **Data fix (one-time):** any existing rows at `pipeline_status='tailored'`
  → set to `'notified'` (they were tailored, effectively done — don't re-spam;
  and after removal `run_notify` reads `scored`, so they'd otherwise be stranded).
  `UPDATE job_postings SET pipeline_status='notified' WHERE pipeline_status='tailored';`

**Code**
- Delete `app/api/resume/[id]/route.ts` (whole PDF route).
- `DiscoveredJobsTable.tsx`: remove `resume_path` / `resume_pages` fields, the
  multi-page badge, the download link.
- `JobDetailModal.tsx`: remove the "Download Resume (PDF)" button + `resume_path`
  from its type. **Keep** the matched/missing keyword display.
- `lib/actions.ts`: `ACTIVE_PIPELINE_STATUSES` `['scored','tailored','notified']`
  → `['scored','notified']`.
- `lib/promotion-actions.ts`: `IN ('tailored','notified','applied')`
  → `IN ('notified','applied')` (both the SELECT and HAVING).
- `lib/constants.ts`: reword the `MATCH_SCORE_THRESHOLD` comment ("match/notify
  threshold", not "tailoring threshold").
- `test-utils/factories.ts`: drop `resume_*` fields.
- Tests: `DiscoveredJobsTable.test`, `JobDetailModal.test` (keep the keyword
  test, drop the download-link test), `promotion.int.test`, `actions.test` —
  drop `resume_*` from fixtures and any `tailored`-status expectations.

### Infra

- `Dockerfile` (worker): remove the whole tectonic block — binary download,
  font/TLS runtime libs, `TECTONIC_*` env, and the bundle **prewarm** step
  (lines ~10–49). Net: smaller image, faster build.
- `docker-compose.yml`: remove the `./resumes:/resumes` volume + `RESUME_DIR`
  from **both** the web (`:ro`) and worker services, and the `./resumes`
  ownership comment. **Keep** `./apps/worker/resume:/app/resume:ro` — it carries
  `resume.txt`, which the *scorer* still reads; only `master.tex` inside it goes
  unused.
- `.env.example` / any `RESUME_DIR` reference: drop.
- `resumes/` dir: no longer written; existing tailored PDFs are orphaned (fine —
  gitignored, user can delete).
- `tools/seed_db.mjs`: **no change** — it never references `resume_*` or
  `tailored`, so the e2e throwaway DB is unaffected.
- `tools/check_schema_drift.mjs`: only checks prisma-fields ⊆ schema.sql, so
  dropping `resume_*` from `schema.sql` isn't strictly required to pass — but do
  it anyway (Worker → Tests) to keep the fixture honest.

### Docs (same commit)

- `SPEC.md`: pipeline is fetch → score → notify; remove tailoring capability,
  the tailored state, tectonic/`resumes/` dependencies; notify is message-only,
  threshold-gated.
- `PROGRESS.md`: close the 🚧 tailoring-removal line. Restate the "transient
  notify failure buries work" defect — the `tailored` state and PDF loss are
  gone, but a notify failure still marks a *scored ≥ threshold* row `failed`,
  dropping it from the default view and never re-notifying. Milder, still open
  (Decision 4 left it unfixed); note the removal made the eventual fix trivial.
- `CHANGELOG.md`: history entry.

## Impact & operational risks

- **⚠️ First-pass alert storm.** After deploy, `run_notify` reads
  `scored ≥ 75` — every existing match that hasn't been notified fires at once.
  Steady-state that's ~0 rows (the old tailor stage drained them each pass), but
  a backlog re-scored with the new Claude scorer could flood Telegram. **Before
  the first run**, check
  `SELECT COUNT(*) FROM job_postings WHERE pipeline_status='scored' AND score>=75;`
  If it's large and unwanted, bump those rows to `notified`/`discarded` first.
- **Coverage gate.** Deleting `tailor.py` + its tests and gutting `run_tailor`
  should be net-neutral on the worker's 85% floor, but confirm with
  `make test-coverage` before committing.
- **Destructive migration.** `resume_tex` is dropped (historical tailored LaTeX
  lost) and `resumes/*.pdf` are orphaned. Back up `db/applications.db` first
  (no migration history — PROGRESS). Existing `tailored` rows MUST get the
  `→ notified` data fix or they strand (Web → Schema).
- **Build/type safety.** The column drop + `prisma generate` turns every stale
  `resume_*` reference into a TS compile error, so `make lint` / build surfaces
  any web ref this spec missed — no silent runtime breakage.

## Testing / verification

- `make test` green (both suites), `make check-schema` green (fixture vs schema),
  `make test-e2e` green.
- Manual: a `scored ≥ 75` row produces a Telegram message (no PDF); a
  `scored < 75` row does not; the modal still shows matched/missing keywords; the
  Discovered queue renders without a download column.

## Sequencing (suggested)

1. Worker changes + worker tests (no schema dependency; fully testable offline).
2. Back up `db/applications.db`; edit `schema.prisma`; `make db-push`; run the
   `tailored → notified` data fix.
3. Web code + web tests; `make lint`; `make test-e2e`.
4. Docs (SPEC / PROGRESS / CHANGELOG) in the same commit as the behavior change.
