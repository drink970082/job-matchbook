# Design: Claude-scored fit, local crisp-fact screening

**Date:** 2026-07-05
**Status:** shipped 2026-07-05 (v1.0.0)
**Scope:** `apps/worker` scoring path only. Tailoring removal is a **separate** spec (see §8).

## Problem

The fit SCORE runs on a local 4B model (`qwen3.5:4b`) and does not assess fit — it
keyword-matches. Evidence from the shared DB (`db/applications.db`, 2033 scored postings):

- **Score mode-collapse:** 5 discrete values (85, 45, 78, 82, 62) cover **57%** of all
  scores. 1152/2033 (57%) land in the 75–89 "good fit" band. The model buckets
  "vaguely relevant" → 78/82/85 rather than scoring fit.
- **Disqualifiers scored as good fits:** e.g. an ML Engineer whose own reasoning says the
  candidate "lacks the required 5+ years... only completed internships" and lacks C++,
  still scored **78**; an FPGA Hardware role (candidate missing FPGA) also **78**.
- **Fragile pre-filter false-discards:** the deterministic years gate + `_EARLY_CAREER_HINTS`
  substring backstop killed **114 strong-fit (score ≥ 75) jobs on a ≤3-year floor**,
  including the Virtu "Automation Analyst" (score 85, disqualified on "requires ~2+ years"
  because its JD says "graduates *are* considered", one word off the hint list). Of 580
  years-gate disqualifications, 444 (77%) fire on ≤4-year floors; only ~25 are real
  (6+ year) walls.

### Root causes (why the local model is weak)

1. `think: False` (`score.py:247`) — required to work around an Ollama `format=json` bug,
   but it makes scoring a single forward pass to JSON with **zero deliberation**.
2. The output schema teaches keyword-matching (score first, keywords, reasoning last) — the
   number is committed **before** any reasoning exists.
3. 4B params + `temperature=0` → mode collapse onto anchor numbers.
4. The prompt never instructs weighing disqualifiers (seniority/domain) over surface overlap.

The SCREEN (hard-requirements) call is **not** the problem: the LLM only extracts facts and
code applies the candidate's constraints (`_screen_verdict`). The one exception is the years
gate, which secretly requires a semantic judgment ("is this stated minimum a hard wall?") that
a 4B model + substring list cannot do reliably — see §3.

## Goal

Replace the fit SCORE with a Claude call that actually reasons about fit; move seniority
judgment off the local pre-filter and into that score. Keep the SCREEN's crisp factual gates
local and free. Drop-in: no change to the `score_detail` schema, threshold gate, or dashboard.

## Non-goals

- Changing the SCREEN call's crisp gates (degree / clearance / country / internships /
  sponsorship). They work and stay on Ollama.
- Removing tailoring (separate spec — §8).
- Any web/dashboard change.

---

## §1 — Model & scope

- **Fit SCORE call → Claude Sonnet 4.6** (`claude-sonnet-4-6`). Rationale: fit is a *judgment*
  task (junior-vs-senior, domain match) where reasoning depth matters; Sonnet is the
  speed/intelligence sweet spot and is already the tailoring default. Env/CLI-overridable like
  the tailoring model.
- **SCREEN call stays on local Ollama** (crisp facts, code judges — unchanged).
- **Years gate deleted.** Remove the years check in `_check_experience` and the
  `_EARLY_CAREER_HINTS` machinery entirely. Seniority fit becomes the Claude score's job. A
  genuinely-too-senior role simply gets a low score.

Resulting division of labor:

| Step | Runs on | Owns |
|---|---|---|
| SCREEN | local Ollama | crisp facts: degree you lack, active clearance you lack, country you can't work in, internships you refuse, sponsorship explicitly denied |
| SCORE | Claude Sonnet 4.6 | all fit + seniority + domain nuance |

## §2 — Code shape & wiring (matches existing DI convention)

- `score_posting` keeps orchestrating both calls. It gains one injected callable
  `score_fit(prompt: str) -> dict` used for the SCORE step; the SCREEN step keeps using the
  injected `http` / `ollama_host`.
- New adapter `make_claude_scorer(api_key, model)` in `score.py`, mirroring
  `tailor.py:make_claude` (lazy `import anthropic` inside the closure, so the module imports
  fine in the test env without the SDK). Returns `score_fit`.
- Wired in `run.py` alongside the existing `make_claude` for tailoring (reuses the same
  `ANTHROPIC_API_KEY`).
- The Ollama SCORE path (building `SCORE_HEADER` prompt and calling `_post` for the fit score)
  is removed. `_post`, the Ollama envelope parsing, and the SCREEN path stay.
- Keeps worker modules pure + dependency-injected + zero-network tests, per `CLAUDE.md`.

## §3 — Prompt redesign (`prompts/score.txt`, `score_header`)

- **Reason before scoring.** The model must first assess, in the `reasoning` field,
  (a) seniority match, (b) domain match, (c) the top missing must-haves — **then** emit the
  0–100 score. (Chain-of-thought precedes the number instead of following it.)
- **Sharpen the rubric.** 75–89 "good fit" requires genuine seniority + domain alignment, not
  keyword overlap; explicitly instruct weighing disqualifiers (seniority gap, wrong domain)
  heavily against surface matches.
- **Adaptive thinking on** (`thinking: {type: "adaptive"}`) — real deliberation, no
  `think:False` hack.
- **Structured output** via `output_config.format` (JSON schema) — reliable JSON, replacing
  the Ollama `format=json` workaround.
- **Output schema unchanged:** `{score, matched_keywords, missing_keywords, reasoning}`.
  `matched_keywords`/`missing_keywords` are retained because `tailor.py` consumes
  `missing_keywords`; they are dropped later by the tailoring-removal spec (§8).

## §4 — Cost controls

- **Prompt-cache** the resume + rubric prefix (~1,180 tokens, byte-identical every call →
  ~0.1× on cache reads). Only the JD (~930 tokens) is fresh per call.
- **Run real-time** — steady-state volume is tens/day. (The 1,987-in-one-day spike was the
  initial board backfill.)
- **Batch API (−50%)** noted as an option only if re-scoring a large backlog; not built now.

Estimated cost (Sonnet 4.6, ~2,100 in / ~250 out per call, with caching): ~$6.90 / 1,000
postings; the full 2,033-posting historical re-score ≈ ~$14 one-time; steady state ≈ pennies/day.

## §5 — Error handling

- Unchanged philosophy: a Claude failure raises `ScoreError` → the pipeline marks that **one**
  posting failed and the batch continues (never aborts). The Anthropic SDK auto-retries
  429/5xx.
- SCREEN parse failure still errs toward keep (scored-but-not-screened).

## §6 — Testing

- Tests mock the injected `score_fit` callable — no network, no API key (per `CLAUDE.md`
  worker rule). New unit tests: score-prompt assembly, structured-output parsing, and that a
  `score_fit` failure raises `ScoreError` without aborting.
- **Delete** the years-gate and early-career-hint tests in `test_score.py`.
- SCREEN tests for the remaining crisp gates (degree/clearance/location/sponsorship/
  internships) stay unchanged.
- `make check-schema` (worker SQL fixture vs `schema.prisma`) unaffected — no schema change.

## §7 — Docs to update (same commit)

- `docs/SPEC.md` — scoring capability (SCORE on Claude, SCREEN local, no years gate).
- `docs/PROGRESS.md` — close the "weak scoring" gap; add tailoring-removal as an in-flight
  follow-up.
- `CHANGELOG.md` — history entry.

## §8 — Out of scope: tailoring removal (next spec)

The user wants tailoring removed. It is deliberately **not** in this spec — different blast
radius, and it introduces behavior questions this change does not. Captured here so it is not
lost:

- **Worker:** `tailor.py`, `prompts/tailor.txt`, `prompts.py`, `pipeline.py`
  (`new→scored→tailored→notified` state machine → collapses to `new→scored→notified`),
  `notify.py` (currently sends the tailored PDF), `db.py`, `run.py`, `util.py`, and tests
  (`test_tailor`, `test_pipeline`, `test_notify`, `test_db`, `test_run`, integration e2e,
  `fixtures/schema.sql`).
- **Web (+ shared schema):** `prisma/schema.prisma` (`resumeTex`/`resumePath`/`resumePages`
  columns → `make db-push`), `api/resume/[id]/route.ts` (PDF route), `DiscoveredJobsTable.tsx`,
  `JobDetailModal.tsx`, `constants.ts` (status enum), `actions.ts`, `promotion-actions.ts`,
  factories + tests.
- **Infra:** `tectonic` dependency (Docker), `resumes/` dir.
- **Open behavior questions for that spec:** does the score threshold now gate *notification*?
  What does Telegram notify send without a PDF (job link + score)?
- **Coupling handled by sequencing:** the removal spec also drops the now-orphaned
  `matched_keywords`/`missing_keywords` from the score output that this spec retains.

## Verification (post-implementation)

- Re-score a sample and confirm the score distribution spreads (no 78/82/85 mode-collapse);
  spot-check that the previously-mis-scored disqualifier examples now score low.
- Confirm the ~114 soft-floor false-discards are no longer discarded.
- **Note:** with the years gate gone and honest scores, the score threshold that gates
  downstream may need retuning — surface the new distribution when verifying.
