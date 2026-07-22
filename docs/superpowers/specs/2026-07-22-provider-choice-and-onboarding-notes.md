# Provider choice, screening, and onboarding — session notes

**Date:** 2026-07-22 · **Status:** design agreed, spec not yet written

These are the decisions and findings from the design session. They are *notes*,
not the implementation spec — the spec covers all five tracks below and comes next.

## Why

Two premises the tool currently fails:

1. **Not everyone has a local LLM.** The hard-requirements screen runs only on
   host Ollama with no fallback, so a GPU-less user cannot run the pipeline at all.
2. **Onboarding assumes a working checkout.** Nothing installs worker deps or
   creates the DB, nothing reports what's missing, and the `onboard-me` skill
   starts at step 2 of a process whose step 0 doesn't exist.

Underneath both: the tool should let users pick their own provider (Codex CLI,
Claude Code, Claude API, OpenAI API, local, or none) rather than hard-coding one.

## Findings

### The LLM screen is pointed at the wrong things

`score/screen.py` sends one Ollama call returning three fields. Only two are used:

| Field | Status |
|---|---|
| `required_degree` | Used — `_check_degree` vs `candidate.highest_degree` |
| `requires_clearance` | Used — `_check_clearance` |
| `offers_sponsorship` | **Ignored** (D1) — decided instead by `NO_SPONSOR_PHRASES` substring matching |

Everything else that discards a posting is already deterministic Python:
`resolve_location` (pycountry), `_INTERN_TITLE` (regex), `NO_SPONSOR_PHRASES`
(phrase list). The module docstring's "keep it local, it runs on every posting"
rationale is **stale** — screen volume equals score volume (`run_score` screens
only `new` rows, then gates the fit call).

### `NO_SPONSOR_PHRASES` has ~2/11 recall — measured, not estimated

Run against realistic phrasings with `work_authorization: "needs visa sponsorship"`:

| Phrasing | Result |
|---|---|
| `US Citizenship is required.` | passes through |
| `Must be a U.S. citizen or Green Card holder.` | passes through |
| `requires US Person status as defined by ITAR` | passes through |
| `permanent work authorization … now and in the future` | passes through |
| `unable to offer immigration support at this time` | passes through |
| `Visa sponsorship is not available for this position.` | passes through |
| `must not require employer-sponsored work authorization` | passes through |
| `No H-1B transfers.` | passes through |
| `We will not sponsor visas for this role.` | **caught** |
| `must be authorized to work without sponsorship` | **caught** |

Sponsorship is unbounded natural language — the one check that genuinely needs a
model — and it is the one check currently done by string matching. Backwards.

### The fit scorer does not duplicate the degree check

`prompts/score.txt` has no degree gate. A degree gap lands in
`must_haves.missing`, which lowers the score but does **not** gate notification
(that gates on the seniority + domain verdicts). So a PhD-required role can still
notify today. The degree screen is narrow but not redundant — and it is free,
riding a call that has to happen anyway for sponsorship.

### Skills are portable in format, not in location

- `SKILL.md` is a real cross-agent standard — Anthropic open-sourced the Agent
  Skills spec (Dec 2025); OpenAI adopted it for Codex CLI and ChatGPT; Gemini CLI
  and Cursor read it too. A skill using only `name`, `description`, and plain
  Markdown runs anywhere.
- **Discovery paths differ.** Claude Code reads `.claude/skills/`; Codex reads
  `.agents/skills/**/SKILL.md` (repo scope; `.codex/skills/` is legacy). So
  `onboard-me` and `onboard-board` are currently invisible to every agent except
  Claude Code.
- `AGENTS.md` is a Linux Foundation (Agentic AI Foundation) standard read by 30+
  agents. This repo has none — `CLAUDE.md` is Claude-only.

### Other universality gaps found

- **Telegram is mandatory.** `run_once` does `env["TELEGRAM_BOT_TOKEN"]` →
  `KeyError`. Someone happy to review the Discovered Jobs tab cannot run the
  worker at all. ~3 lines to fix.
- **No setup path.** No `pip install` target, no `make setup`, no DB creation.
  `onboard-me` step 3 writes categories into a DB that may not exist and only
  *reacts* to the resulting error.
- **No preflight.** Nothing reports what's missing; every "is it set up?" answer
  today is a manual `curl` / `codex doctor` / `ls`.
- **Remote Ollama already works** — `OLLAMA_HOST` is env-driven — but `SETUP.md`
  says "GPU required, no cloud fallback", which is wrong.

## Decisions

### Screen backends (agreed)

`SCREEN_BACKEND = ollama | codex | claude-code | claude-api | openai-api | none`,
default `ollama`. **Auto-detection must never select a paid backend** — spending
money is explicit opt-in. Five configs reduce to three adapter shapes:

- **HTTP + JSON schema** — ollama (exists), claude-api, openai-api
- **CLI subprocess + `--output-schema`** — codex (adapt `backends_codex.py`), claude-code
- **`none`** — deterministic gates only, documented as low-recall on sponsorship

Model picks: `claude-haiku-4-5` for both Claude paths (two-field extraction —
Sonnet is wasted money; `claude-sonnet-5` as override). **`gpt-5.6-luna` for
Codex** — `run.py` rejects luna outright, but that verdict was measured on *fit
scoring*, a calibration-sensitive judgment where its ~3× looser spread was fatal.
Extraction is what luna is recommended for and there is no spread to blow. The
prior rejection does not transfer, but must be re-measured, not assumed.
OpenAI API model string: **not yet chosen** — check what's available first.

### Codex latency (agreed)

- **Batch the screen.** `DEFAULT_BATCH_SIZE = 1` is parked because batching bled
  the *domain verdict* — a cross-JD judgment. The screen is per-JD fact
  extraction, so the objection does not transfer. Reuse the existing `job_ref`
  alignment guard; gate with a batched==single run like `tools/score_eval.py`.
- **Run screens concurrently.** `pipeline.run_score` screens in a serial loop.
  A thread pool helps every backend; it is the main win for subprocess backends.
  Neutral for Ollama (one GPU serializes anyway).

### Sponsorship (agreed — option 1)

**The LLM becomes the primary sponsorship check; `NO_SPONSOR_PHRASES` is demoted
to a floor that can only *add* disqualifications.** Rejected alternative: LLM as
second opinion that fires only when the phrase list also fires — that inherits
the list's 2/11 recall and buys nothing.

D1 (the 4B model inventing "no" from silence) is handled by **grounding the
extraction in a verbatim quote** rather than by requiring a better model:

```
"authorization": {"no_sponsorship_quote": "<the exact sentence from the JD that
                   states sponsorship is unavailable, or null if none exists>"}
```

Code verifies the quote actually appears in the description before acting on it.
A hallucinated quote fails the check and the posting is **kept** — hallucination
cannot disqualify anything by construction, not by trust. Same
LLM-extracts / code-decides pattern the module already uses, one step further.
Works on every backend including `qwen3.5:4b`, so D1 need not be re-litigated.

**Residual risk, stated honestly:** quote-grounding kills hallucination but not
*misclassification* — a model could quote real-but-irrelevant text (the old
"company-sponsored sports teams" false positive was that shape, though it was the
old substring guard's failure, not the model's). Measurable, not theoretical.

**Gate:** a sponsorship labeled set (*no-sponsorship / offers / silent*). Cheap
route — run the new LLM screen and the current phrase list over the ~600
already-scored rows and diff; disagreements are hand-label candidates,
agreements are free labels.

### Screen scope (agreed)

Keep the screen, repoint it:

- **Sponsorship (quote-grounded)** — the primary job
- **Degree** — stays; cheap notify-gate the scorer does not cover
- **Clearance** — rides along free; rare, but one field in a schema already sent

## Spec scope — five tracks

1. **Screen backends** — the six-way `SCREEN_BACKEND`, three adapters, never
   auto-select paid.
2. **Universality fixes** — Telegram optional; `make setup` (deps + DB + template
   copies) and `make doctor` (✓/✗ for python / node / docker / ollama / codex /
   claude / keys / telegram / db); document remote `OLLAMA_HOST`.
3. **`onboard-me` Step 0** — runs `make setup`, then `make doctor`, then picks
   the provider path from what is actually installed, before the interview. The
   skill reads `doctor` output instead of carrying its own prereq prose, which
   makes it shorter *and* agent-agnostic.
4. **Agent portability** — move skills to `.agents/skills/`, symlink
   `.claude/skills` → `.agents/skills`, add a thin root `AGENTS.md` pointing at
   `CLAUDE.md` and the skills. **Verify Claude Code follows a symlinked skills
   dir** before committing to that direction rather than the reverse.
5. **Sponsorship screen rework** — quote-grounded LLM primary, phrase list as
   floor, plus the labeled set and gate.

Track 5 is the one with a correctness gate; 1 and 5 share the screen call and
should land together.

## Open questions

- OpenAI API model string for the screen — unchosen.
- Does Claude Code discover skills through a symlinked `.claude/skills`?
- Screen batch size for the codex backend — pick after the batched==single guard.
