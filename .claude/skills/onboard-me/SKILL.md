---
name: onboard-me
description: >-
  Use when someone wants this job-search tool (ATS / tracker / worker / pipeline)
  set up, configured, or personalized for THEIR own hunt — so it screens and scores
  real postings against their background and résumé. Trigger on "set me up", "get me
  started", "onboard me", or "walk me through setup" — and, just as important,
  whenever they simply describe themselves (target roles, level, a career switch, a
  résumé file or path) or their must-haves (remote-only, no relocation, visa
  sponsorship, a degree, clearance) and want the tool tuned to match jobs for them.
  Covers the full fresh-checkout walkthrough AND configuring any single input on its
  own: fit profile, résumé ingestion, tracking categories, or hard requirements. Do
  NOT trigger for operating an already-set-up tool: adding one company (that's
  onboard-board), rewording a loaded résumé, scheduling runs, fixing broken alerts,
  or explaining scorer verdicts.
---

# Onboard a new user

The engine is **persona-agnostic** — it fits *any* field. Everything that makes a
run personal lives in **data the user provides**, never in the scorer's prompt. Your
job is to hold one friendly interview and turn the answers into that data, so a
first-time checkout becomes a pipeline tuned to *this* person's search.

This is the conversational counterpart to `docs/SETUP.md` Path B: same inputs, but
you interview instead of handing them a checklist. On success the payoff is a first
pipeline pass that surfaces real matches — so drive toward that, don't just create
files.

**Never touch `apps/worker/ats_worker/prompts/score.txt`.** Generality is supposed to live
in the profile and résumé, not the rubric — scorer-prompt edits have destabilized
verdicts before (see CHANGELOG / SPEC §7.1). If a role scores wrong, fix the
*profile*, not the prompt.

## What you'll produce (all gitignored personal data)

| Step | Artifact | How |
|------|----------|-----|
| 2 | `apps/worker/resume/personal_profile.txt` | you write it from the interview |
| 3 | categories (a DB `app_settings` row) | bundled `set_categories.py` |
| 4 | `apps/worker/config.yaml` `candidate:` block | you edit the file |
| 5 | `apps/worker/resume/resume.txt` | you read their résumé → clean text |
| 6 | watchlist rows (DB) | **delegate to the `onboard-board` skill** |
| 7 | `apps/worker/.env` | you fill values the user gives; verify prereqs |
| 8 | first pass | `python -m ats_worker.run --once` |

Steps are **ordered but independent.** A brand-new user wants the whole run; someone
who says "just fix my profile" or "set up my categories" wants one step — do that
one and stop. Ask which they need if it's unclear.

## Step 1 — gather the facts (adapt to how much they gave)

The later steps all draw on the same handful of facts. How you collect them depends
on what the user already handed you — two rules govern it: **read what they've
already said first**, and **never make them repeat themselves.**

- **They already laid it out** (a detailed ask, or a full dump) → don't interrogate
  them. Reflect back what you understood, ask only about the genuine gaps, and move
  on to writing artifacts.
- **They just said "onboard me"** with little else → **walk them through it
  conversationally** — a few related questions at a time, in plain language. This is
  often a first-time, possibly non-technical user; a warm step-by-step beats dropping
  a wall of form fields on them.

Either way you're converging on **one** artifact-ready set of answers — gather it
once, reuse it across steps 2–6. What you need to end up with:

- **Target roles** — what work do they actually want, described by the *day-to-day*,
  not just a title? Get a rough priority order (their #1 vs. would-also-take).
- **Career stage** — years / level, and where they're heading (sets "right
  seniority").
- **Dealbreakers** — the things that should *discard* a posting outright: work
  authorization / sponsorship, where they can legally work (locations / remote),
  minimum degree, security clearance, interns-only-or-not. These are HARD filters —
  distinct from "nice to have."
- **Anti-targets** — roles they'd pass the résumé screen for but don't want (so the
  scorer marks them down).
- **Genuine interests** — the one honest lever that legitimately *raises* fit
  (fintech, dev tools, climate…).
- **Résumé** — where's the file? (path to a PDF / .txt / .docx.)
- **Target companies** — any boards/companies they already want watched.

You don't need every field before you start — gather more as a step needs it. A
blank section beats a made-up one.

## Step 2 — write `personal_profile.txt` (the high-value piece)

This is the biggest lever. `personal_profile.txt` is short about-you context the fit
scorer reads on **every** call; its **domain verdict** (does this role *suit* this
person?) is judged against the TARGET / ANTI-TARGET tiers you write here. Get this
right and the whole pipeline points the right way. (The tiers must be *résumé-backed*,
so read their résumé first if you haven't already — you'll ingest it properly in
Step 5, but you need its content now to place the targets honestly.)

Read the template so you match its structure exactly — the scorer relies on these
section headers:

```
apps/worker/resume/personal_profile.txt.example
```

Write `apps/worker/resume/personal_profile.txt` with these sections, filled from the
interview (not the example's bracketed placeholders):

- **STAGE** — their career stage in a line.
- **TARGET, priority order** — numbered; describe the actual day-to-day work, not a
  title. Priority 1–3 score a full domain `match`, so **only list a role here if the
  résumé demonstrably backs it.** A field they're merely *interested* in but haven't
  done goes in INTERESTS (or a clearly-labeled lower "would-stretch-into" tier), never
  the top 3 — putting it up top inflates the verdict. Lower tiers score `adjacent`.
- **ANTI-TARGETS** — bulleted; always beat any TARGET a role also matches. **Scope
  each to the disliked day-to-day, qualified ("pure/only…") — never a bare title that
  overlaps a target,** or you'll down-score a role they'd take. (Excluding "visual
  design" would sink a Lead Product Designer whose work includes visual craft;
  "pure visual/marketing-only design" excludes just the unwanted work.)
- **POSITIONING** — how they frame themselves / what they optimize for. **Keep hard
  constraints out** (visa, location, degree, clearance) — those live in `config.yaml`
  (Step 4); here they only pollute the fit signal.
- **INTERESTS** — genuine interests that raise fit (the honest upward lever). A domain
  they like but haven't done lives here, not in TARGET.
- **CAVEATS** — honest downward notes, or leave blank. **Ground them in what the user
  said or an evident résumé gap tied to a stated target — don't invent weakness
  categories from résumé absence.**

Keep it concise and honest. It is **not** a résumé — it never claims a skill the
résumé can't show (a recruiter sees the résumé, not this). A real skill gap is
fix-the-résumé signal, not something to paper over here. Show the user the draft and
adjust — this file is worth a second pass.

## Step 3 — set their categories

Categories are the vocabulary the tracker files applications under (the Add /
Mark-Applied dropdowns and the donut chart). Turn their targets into 3–8 short
labels **in their words**, keeping an `Others` catch-all, and persist with the
bundled script (writes the shared SQLite via the worker DB layer; the web UI
reflects it immediately):

```bash
python .claude/skills/onboard-me/scripts/set_categories.py "Cat A,Cat B,Others"
```

Confirm the `set N categories: …` line. Tell them it now drives the Add-application
form, the Mark-Applied dialog, the table filter, and the category donut — editable
anytime from the web app's **Categories** button. (Needs the DB to exist — if the
script errors with "DB not found", they haven't run `make db-push` yet; do that
first.)

## Step 4 — candidate hard-constraints (`config.yaml`)

Hard constraints are the ONLY things that **discard** a posting; a missing *skill*
is not one (that just lowers the fit score — skills live in the résumé). Copy the
template if `config.yaml` doesn't exist yet, then edit the `candidate:` block from
the dealbreakers you gathered:

```bash
cp apps/worker/config.yaml.example apps/worker/config.yaml   # only if missing
```

Edit these fields (leave any one **blank** to *not* screen on it; blank everything to
disable disqualification):

- `highest_degree` — none | High School | Associate | Bachelor's | Master's | PhD
- `work_authorization` — citizen | permanent resident | authorized-no-sponsorship | needs visa sponsorship
- `security_clearance` — none | confidential | secret | top secret
- `locations` — where they can actually work (e.g. `["remote"]`, `["USA"]`); on-site
  roles elsewhere are discarded. The LLM judges by meaning ("USA" covers "New York").
- `exclude_internships` — `true`/`false` (deterministic, by title).

Optionally set `title_filter` — a coarse, **title-only** substring keep-list applied
before the scorer. Leave it empty unless a high-volume company floods them with
off-target titles; the scorer does the real relevance work. **`title_filter` is a
top-level key (a sibling of `candidate:`, at column 0), NOT a `candidate:` subkey** —
nesting it under `candidate:` fails loud at startup.

**Edit the file directly — don't script it** (a YAML writer would strip the template's
comments). Two rules that bite: **unknown / mistyped keys fail loud at startup** — both
at the top level and inside `candidate:` — so use only the documented keys and keep each
at its right level (the five above under `candidate:`, `title_filter` at the top); and
set values, don't add sections.

## Step 5 — ingest their résumé

The scorer judges fit on résumé *content*, not formatting, so all it needs is clean
readable text at `apps/worker/resume/resume.txt`.

- **`.txt`** — copy it in.
- **PDF** — read it directly (your Read tool renders PDFs), then write the text out. If
  it won't render (a scanned/image-only PDF, or no rasterizer available), ask them to
  paste the text or export a `.txt` — don't dead-end on it.
- **`.docx`** — unzip and read `word/document.xml`, **extracting the visible text (the
  `<w:t>` runs), not the raw markup** — or just ask them to export a PDF or paste the
  text. Don't add a parsing dependency for this.

Write the plain text to `apps/worker/resume/resume.txt`. It must be UTF-8 (a
non-UTF-8 file aborts worker startup). Two gotchas from `resume/README.md`: **every
`*.txt` in that directory is loaded as a résumé version**, so if they want targeted
versions name them `resume_<label>.txt` and delete the generic `resume.txt`; and this
file is gitignored personal data — never commit it.

## Step 6 — starter watchlist (delegate to `onboard-board`)

For each company they named, hand off to the **`onboard-board` skill** — it walks the
platform → plain-HTTP → browser cascade, validates, and adds the row to the DB
watchlist (`add_watched.py`). Don't reimplement that here; invoke it per company. If
they named none, that's fine — they can add boards anytime in the web **Watchlist**
tab or by asking to "add <company>" later.

## Step 7 — secrets & prerequisites (`.env`)

The pipeline needs services only the user can provide — so **verify, don't fabricate**.
Copy the template and fill in the values they give you:

```bash
cp apps/worker/.env.example apps/worker/.env   # only if missing
```

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — the only match-alert channel; they get
  these from BotFather. Required for the pipeline.
- `OLLAMA_HOST` — usually `http://localhost:11434`. The hard-requirements screen runs
  on a **host GPU via Ollama** — there is no cloud fallback. Verify it's up:
  `curl -s localhost:11434/api/tags`.
- **Fit-score backend** — default `codex` (a ChatGPT subscription, *not* an API key):
  they run `codex login` once; verify with `codex doctor` (auth ✓). No subscription?
  Set `SCORE_BACKEND=claude` and supply `ANTHROPIC_API_KEY` (metered).

Never invent a token or key. If a prereq is missing, say so plainly and point them at
`docs/SETUP.md` — a clear "you still need X" is the useful answer.

## Step 8 — first run (the payoff)

End on the activation event — one pass, so they see it work:

```bash
cd apps/worker && python -m ats_worker.run --once
```

Matches land in Telegram and the web app's **Discovered Jobs** tab. Once they're
happy, dropping `--once` runs it on the schedule (`schedule_hours`, default 24h).
That's the finish line — a personalized pipeline surfacing real roles.

## Guardrails

- **Personalization is data, never the rubric.** Never edit
  `ats_worker/prompts/score.txt`. Wrong verdict → fix the profile.
- **DB writes go through the bundled script; files you edit directly.** Categories and
  watchlist touch SQLite (script / `onboard-board`); the profile, `config.yaml`, and
  résumé are files you write.
- **Don't fabricate secrets or prereqs.** Verify what exists, name what's missing.
- **One board add ≠ onboarding.** If all they want is a single company on the
  watchlist, that's `onboard-board`, not this.
