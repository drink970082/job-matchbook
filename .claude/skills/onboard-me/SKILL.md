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
| 0 | a runnable checkout (deps, DB, template copies) | `make setup` + `make doctor` |
| 2 | `apps/worker/resume/personal_profile.txt` | you write it from the interview |
| 3 | categories (a DB `app_settings` row) | bundled `set_categories.py` |
| 4 | `apps/worker/config.yaml` `candidate:` block | you edit the file |
| 5 | `apps/worker/resume/resume.txt` | you read their résumé → clean text |
| 6 | watchlist rows (DB) | **delegate to the `onboard-board` skill** |
| 7 | `apps/worker/.env` | you fill values the user gives (prereqs came from Step 0) |
| 8 | first pass | `python -m ats_worker.run --once` |

Steps are **ordered but independent.** A brand-new user wants the whole run; someone
who says "just fix my profile" or "set up my categories" wants one step — do that
one and stop. Ask which they need if it's unclear.

## Step 0 — make the checkout runnable (before you interview)

Do this first on a fresh checkout, and **read the output** — it decides what you can
honestly promise in later steps. Skip it only when they asked for one specific step on
a checkout that already works.

```bash
make setup     # web + worker deps, DB, and the config templates (never clobbers)
make doctor    # one status line per prerequisite
```

`make setup` copies the two **config** templates that Steps 4 and 7 would otherwise
`cp` (`config.yaml`, `.env`) — non-clobbering, so it never overwrites a file they
already filled in. If it ran, skip those copy commands. It deliberately does **not**
create `resume.txt` or `personal_profile.txt`: those are authored content (Steps 2 and
5), and a leftover placeholder would be silently loaded as the user's real résumé.

`make doctor` exits non-zero **only** when a *universal* prerequisite is missing.
Everything else is an `[ok]`/`[no]` **status line, not a verdict** — read the rows to
pick this user's path; never demand all of them go green.

| doctor row | If `[no]` |
|---|---|
| worker python deps · database | **Blocking** — re-run `make setup`; nothing runs without these |
| ollama | The screen has no backend. Start Ollama, **or** point `OLLAMA_HOST` at a remote/cloud instance — a local GPU is *not* required |
| codex CLI | Default fit backend unavailable — either `codex login`, or switch to `SCORE_BACKEND=claude` + `ANTHROPIC_API_KEY` |
| claude CLI · anthropic api key | Only needed for the `claude` fit backend |
| telegram | **Fine — alerts are optional.** Matches still land in the Discovered Jobs tab |
| node · docker | Only for the web app, not the pipeline |

Report what's actually missing *for the path they want*, in a line. Never fabricate a
key or token to turn a row green.

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
person?) is judged against the TARGET / ANTI-TARGET tiers you write here.

Write `apps/worker/resume/personal_profile.txt` with exactly these six section
headers, which the scorer keys on: **STAGE**, **TARGET** (priority order),
**ANTI-TARGETS**, **POSITIONING**, **INTERESTS**, **CAVEATS**. Structure matches
`apps/worker/resume/personal_profile.txt.example`.

**Read [`references/profile.md`](references/profile.md) before you write it.** Each
section carries a scoping rule that decides whether the verdict comes out right, and
the two that bite most — TARGET must be résumé-backed, ANTI-TARGETS must be scoped to
the disliked day-to-day — are not guessable. The tiers must be résumé-backed, so read
their résumé first if you haven't; you ingest it properly in Step 5, but you need its
content now to place the targets honestly.

Show the user the draft and adjust — this file is worth a second pass.

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
anytime from the web app's **Categories** button. (Needs the DB to exist — a "DB not
found" error means Step 0's `make setup` hasn't run; run it first.)

## Step 4 — candidate hard-constraints (`config.yaml`)

Hard constraints are the ONLY things that **discard** a posting; a missing *skill*
is not one (that just lowers the fit score — skills live in the résumé). Copy the
template if `config.yaml` doesn't exist yet, then edit the `candidate:` block from
the dealbreakers you gathered:

```bash
cp apps/worker/config.yaml.example apps/worker/config.yaml   # only if Step 0 didn't
```

**Read [`references/config.md`](references/config.md) for the field list and the two
failure modes** — the allowed values per field, plus the key-placement and typo rules
that make the worker fail loud at startup. Edit the file by hand, not with a script:
a YAML writer strips the template's comments.

## Step 5 — ingest their résumé

The scorer judges fit on résumé *content*, not formatting, so all it needs is clean
readable text at `apps/worker/resume/resume.txt`, in UTF-8 (a non-UTF-8 file aborts
worker startup).

- **`.txt`** — copy it in.
- **PDF** — read it directly (your Read tool renders PDFs), then write the text out.
- **`.docx`** — unzip and read `word/document.xml`, **extracting the visible text (the
  `<w:t>` runs), not the raw markup**. Don't add a parsing dependency for this.

[`references/resume.md`](references/resume.md) has the fallbacks for a file that won't
render and the multi-version naming rule — read it if the résumé isn't a clean single
`.txt`/PDF, or if they want role-targeted versions. That file is gitignored personal
data; never commit it.

## Step 6 — starter watchlist (delegate to `onboard-board`)

For each company they named, hand off to the **`onboard-board` skill** — it walks the
platform → plain-HTTP → browser cascade, validates, and adds the row to the DB
watchlist (`add_watched.py`). Don't reimplement that here; invoke it per company. If
they named none, that's fine — they can add boards anytime in the web **Watchlist**
tab or by asking to "add <company>" later.

## Step 7 — secrets (`.env`)

Step 0's `make doctor` already told you which of these are missing — don't re-probe
with `curl` or `codex doctor`; re-run `make doctor` if you need a fresh read. All that
is left is filling in values **only the user can give you**. Fill them into
`apps/worker/.env` (Step 0 copied it from the template):

- `OLLAMA_HOST` — `http://localhost:11434` locally, or the URL of a remote/cloud
  Ollama. Set it whenever the `ollama` row was `[no]` but they have one elsewhere.
- **Fit-score backend** — default `codex` uses a ChatGPT subscription, *not* a key
  (`codex login`). No subscription? Set `SCORE_BACKEND=claude` and supply
  `ANTHROPIC_API_KEY` (metered).
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — **optional.** Push alerts from BotFather.
  Without them the worker runs fine and matches appear in the Discovered Jobs tab, so
  offer this rather than gating the setup on it.

**Verify, don't fabricate.** Never invent a token or key. If a prereq is genuinely
missing, say so plainly and point at `docs/SETUP.md` — a clear "you still need X" is
the useful answer.

## Step 8 — first run (the payoff)

End on the activation event — one pass, so they see it work:

```bash
cd apps/worker && python -m ats_worker.run --once
```

Matches land in the web app's **Discovered Jobs** tab — and in Telegram too, if they
configured a bot. Once they're
happy, dropping `--once` runs it on the schedule (`schedule_hours`, default 24h).
That's the finish line — a personalized pipeline surfacing real roles.

## Guardrails

- **Personalization is data, never the rubric.** Never edit
  `ats_worker/prompts/score.txt`. Wrong verdict → fix the profile.
- **DB writes go through the bundled script; files you edit directly.** Categories and
  watchlist touch SQLite (script / `onboard-board`); the profile, `config.yaml`, and
  résumé are files you write.
- **Don't fabricate secrets or prereqs.** Verify what exists, name what's missing.
- **`make doctor` reports; it doesn't gate.** Only its core rows (worker deps,
  database) block a run. Ollama/codex/claude/telegram/node/docker are provider rows —
  use them to pick this user's path, never as a checklist they must complete. Telegram
  in particular is optional.
- **One board add ≠ onboarding.** If all they want is a single company on the
  watchlist, that's `onboard-board`, not this.
