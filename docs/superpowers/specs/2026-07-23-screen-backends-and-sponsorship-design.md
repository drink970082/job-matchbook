# Screen backends, sponsorship rework, and concurrency — design

**Date:** 2026-07-23 · **Status:** design agreed, not yet implemented
**Supersedes the relevant parts of:**
[`2026-07-22-provider-choice-and-onboarding-notes.md`](./2026-07-22-provider-choice-and-onboarding-notes.md)
(tracks 1 and 5; tracks 2 and 3 shipped 2026-07-23; track 4 closed 2026-07-26 --
AGENTS.md landed, and the `.agents/skills` symlink is verified load-bearing for Codex).

Covers P1 items 3 (screen backends + sponsorship gate) and the concurrency work that
rides with them.

---

## 1. Why

Three premises the tool currently fails.

1. **A GPU-less user cannot screen at all.** The hard-requirements screen runs only
   against host Ollama (`score/screen.py:160`, `_post`), with no alternative backend.
   Tracks 2 and 3 made a fresh checkout *set up*; this makes it *run*.
2. **The sponsorship gate has ~2/11 recall — measured, not estimated.**
   `NO_SPONSOR_PHRASES` (`screen.py:57`) is a closed 12-phrase substring list, so it
   catches only JDs whose wording happens to be on it. It is the highest-value check for
   any sponsorship-needing user, and the *only* screen check not using the LLM — while
   degree and clearance, the two a phrase list could nearly handle, do.
3. **The screen and the fit loop are both serial.** `run_score` screens one row at a
   time (`pipeline.py:459`) and walks fit chunks serially (`pipeline.py:481`), even
   though `run_feed` already proves a safe concurrency pattern in this codebase.

---

## 2. Scope

**In:**

- Six-way `SCREEN_BACKEND`, three adapter shapes, never auto-selecting a paid backend.
- Quote-grounded sponsorship extraction; `NO_SPONSOR_PHRASES` demoted to a floor.
- A fallback screen check inside the fit scorer, for configurations where the screen
  produced nothing.
- Concurrency for the screen loop (per-backend worker count) and the fit loop.

**Out (deliberate, with reasons):**

- **Screen batching.** The per-JD-extraction argument for why the domain-verdict bleed
  does not transfer is a hypothesis, not a result. It needs its own batched-equals-single
  guard, and folding it in here would put three correctness gates in one diff. Defer.
- **Score batching.** Dead at every size > 1 on measured grounds (SPEC §13); not revived.
- **Track 4 (agent portability).** Independent; unaffected by this work.

---

## 3. Architecture — the `extract` seam

`screen_posting` is already backend-agnostic *except* for one step. Its logic is: build
the prompt → get JSON back → `_screen_verdict` applies the candidate's constraint in
**code** → `deterministic_screen` adds the intern/location gates. Only "give me JSON from
this prompt" is Ollama-specific.

So inject it, exactly as `fit_fn` already is:

```python
def screen_posting(posting, *, extract=None, candidate=None, num_ctx=8192) -> dict:
    ...
    data = extract(SCREEN_HEADER + checklist + "\n" + job, SCREEN_SCHEMA)
```

- `extract(prompt: str, schema: dict) -> dict` is the entire backend contract.
- `extract=None` means **no LLM screen** — the `none` backend and the current
  "no candidate constraints configured" path collapse into the same branch.
- The existing failure contract is preserved verbatim: an `extract` that raises
  `ScoreError` errs toward **keep**, never toward discard. This is load-bearing and must
  not regress — a broken provider must not silently discard the queue.
- `run.py` gains `make_screener(backend, *, env, ...)` mirroring `make_scorer`
  (`run.py:78`). All real wiring stays in `run.py`; the modules stay pure and injected.

Everything downstream — `_screen_verdict`, `_check_degree`, `_check_clearance`,
`deterministic_screen`, the persisted `score_detail` shape — is unchanged.

### Three adapter shapes

| Shape | Backends | Mechanism |
|---|---|---|
| HTTP + JSON schema | `ollama`, `claude-api`, `openai-api` | POST, schema-constrained response |
| CLI subprocess | `codex`, `claude-code` | `subprocess.run`, schema file, read result |
| Deterministic-only | `none` | `extract` is `None`; no call |

`ollama` reuses the existing `_post` unchanged. `claude-api` uses the Anthropic SDK's
`output_config={"format": {"type": "json_schema", "schema": ...}}`, the same mechanism
`backends_claude.py:49` already uses for fit scoring. `codex` reuses the
`codex exec --output-schema <file> --output-last-message <file>` pattern from
`backends_codex.py:114-122`, including its tool-less security posture
(`--disable shell_tool`, `web_search="disabled"`) — a JD is untrusted scraped text and
`codex exec` is natively an agent holding a shell. `claude-code` uses
`claude -p --json-schema <schema> --output-format json` (flags verified against the
installed CLI, not assumed).

---

## 4. Backends and models

| `SCREEN_BACKEND` | Model | Cost | Notes |
|---|---|---|---|
| `ollama` (default) | `qwen3.5:4b` | free | Unchanged. ~3GB resident, ~2s/posting |
| `codex` | `gpt-5.6-sol` → `gpt-5.6-luna` | subscription | **Ships on `sol`** (already trusted). `luna` is the cheaper candidate and becomes the default only if it passes the extraction re-measurement in §10 |
| `claude-code` | CLI default | subscription | Subprocess; schema via `--json-schema` |
| `claude-api` | `claude-haiku-4-5` | $1/$5 per MTok | 200K ctx; structured outputs supported |
| `openai-api` | `gpt-5.6-luna` | $1/$6 per MTok | 1.05M ctx; structured outputs supported |
| `none` | — | free | Deterministic gates only; **low recall, must be documented** |

Model-string research (2026-07-23): `claude-haiku-4-5` is the cheapest current Claude
tier and is on the supported list for structured outputs — correct for three-field
extraction, where Sonnet is wasted money. On the OpenAI side, `gpt-5.6-luna` ($1/$6,
1.05M ctx) is the cheapest of the three frontier models and supports structured outputs.
Aggregator sites claim a much cheaper "nano" tier (~$0.075/$0.30); OpenAI's own models
page does not list one in the frontier section, so it is deliberately not hard-coded
here. Revisit only if screen cost ever becomes material.

**Auto-detection must never select a paid backend.** The default stays `ollama`.
Spending money is explicit opt-in via `SCREEN_BACKEND` / `--screen-backend`.
`make doctor` already reports which providers are actually present; that is the data an
operator (or `onboard-me` Step 0) uses to choose.

---

## 5. Sponsorship rework — quote grounding

The LLM becomes the **primary** sponsorship check. The rejected alternative — LLM as a
second opinion firing only when the phrase list also fires — inherits the list's 2/11
recall and buys nothing.

D1 (the 4B model inventing `offers_sponsorship: "no"` from silence) is handled by
grounding the extraction in a verbatim quote rather than by demanding a better model:

```
"authorization": {"no_sponsorship_quote": "<the exact sentence from the JD stating
                   sponsorship is unavailable, or null if none exists>"}
```

`_check_authorization` (`screen.py:307`) becomes:

1. If the candidate does not need sponsorship → pass (unchanged).
2. If `no_sponsorship_quote` is non-null **and the quote actually appears in the
   description** → disqualify.
3. Else, fall through to `NO_SPONSOR_PHRASES` as a **floor** that can only *add* a
   disqualification, never veto the model.

**Quote matching:** whitespace-collapsed and case-insensitive substring, matching the
normalization the existing phrase check already applies (`" ".join(text.lower().split())`).
That tolerates line wraps and casing differences — the ways a faithful quote legitimately
differs — but not invented text. A hallucinated quote fails verification and the posting
is **kept**: hallucination cannot disqualify anything *by construction*, not by trust.
That property holds on `qwen3.5:4b` too, so D1 needs no re-litigating, and it holds
identically on every backend.

**Residual risk, stated honestly:** quote-grounding kills hallucination but not
*misclassification* — a model quoting real-but-irrelevant text. That is the shape of the
old "company-sponsored sports teams" false positive, though that was the previous
substring guard's failure, not a model's. Measurable, not theoretical; see §9.

---

## 6. Scorer fallback check

The fit scorer already runs on every screen survivor, so adding extraction fields to its
schema costs a handful of output tokens and **zero extra calls**.

**Prompt shape.** `prompts/score.txt` gains an *additive* extraction block and matching
schema fields (degree, clearance, sponsorship quote) — the same three facts, the same
quote-grounding rule. The block is appended; the scoring rubric and the
seniority/domain verdict definitions are **not touched**.

**The prompt is identical in every configuration.** No conditional prompt per backend —
otherwise the golden-set gate stops covering the production prompt in some configs.

**Consumption is a fallback, not a second vote.** Code reads the scorer's screen fields
**only where the screen produced nothing** for that check:

- `SCREEN_BACKEND=none`, or
- a screen parse failure that err-toward-keep already swallowed, or
- a check the screen's extraction omitted.

On the validated Ollama path the screen's verdict stands. Rationale: a second independent
checker doubles the false-positive surface, and a spurious "requires PhD" would *silently
discard a good posting* — the exact failure mode the err-toward-keep design exists to
avoid. Insurance for the gap, not a redundant vote.

A posting the scorer disqualifies is re-bucketed `discarded` after the fit call. No money
is wasted — it was already spent — and the reason is persisted in `score_detail` like any
other screen verdict.

**This is the risky part of the change.** SPEC §7.1 and the `onboard-me` guardrail both
record that scorer-prompt edits have destabilized verdicts before, and the domain-verdict
fix specifically worked by tuning the *profile* while a prompt tweak made things worse.
The mitigation is the gate in §9, which is mandatory, not advisory.

---

## 7. Concurrency

`run_feed` (`pipeline.py:198-276`) already establishes the pattern this codebase trusts:
**read serial → network parallel (`ThreadPoolExecutor`) → write serial**, because SQLite
connections are not safe across threads. Both changes below copy that shape rather than
inventing one. Every DB call stays on the calling thread.

### 7.1 Screen loop

`run_score`'s screen loop (`pipeline.py:459`) fans the `screen_fn` calls out to a pool.
Worker count is **per-backend**, because the backends are bound by different things:

| Backend | Default workers | Why |
|---|---|---|
| `ollama` | **1** | A single GPU serializes the compute, so parallel requests interleave rather than speed up. Weights load once (~3GB) and are *not* duplicated per slot — only KV cache is — so RAM is the secondary constraint, not the binding one. Configurable, so a multi-GPU or remote-Ollama user can raise it |
| `codex`, `claude-code` | 4 | Each call pays a process spawn plus a network round trip — the largest win |
| `claude-api`, `openai-api` | 4 | Network-bound |
| `none` | n/a | No calls |

### 7.2 Fit loop

`run_score`'s chunk loop (`pipeline.py:481`) also runs serially today. Making it
concurrent is a genuine win and the objection recorded against it no longer holds:

The 2026-07-15 decision (`CHANGELOG.md:1172-1174`) concluded *"parallelism can't help"*
because *"Plus meters a rolling 5-hour message window (~20-110 on terra)"*. That premise
was **measured wrong and corrected two days later** (`CHANGELOG.md:412-414`): the binding
limit is **weekly** (`window_minutes=10080`). SPEC §11 now states the same, and prescribes
**pacing against weekly headroom** as the fix.

Concurrency and quota are orthogonal: running N codex execs in parallel spends exactly
the same number of messages as running them serially — it only changes wall-clock. Pacing
is already served by `--score-limit`. Concurrent `codex exec` is separately confirmed safe.

The existing per-chunk singles-fallback (`pipeline.py:485-495`) is preserved unchanged:
one bad posting must never abort the batch.

---

## 8. Config surface

| Setting | Env | CLI | Default |
|---|---|---|---|
| Screen backend | `SCREEN_BACKEND` | `--screen-backend` | `ollama` |
| Screen model override | `SCREEN_MODEL` | `--screen-model` | per-backend (§4) |
| Screen workers | `SCREEN_WORKERS` | `--screen-workers` | per-backend (§7.1) |
| Fit workers | `SCORE_WORKERS` | `--score-workers` | 4 |

`SCREEN_BACKEND` and `SCREEN_MODEL` are non-secret and follow the existing
`_ENV_ARGPARSE_KEYS` pattern (`run.py:72`). API keys are **not** promoted to argparse
defaults — they stay read from the in-process `env` dict only, per the existing rule that
promoting them would leak them to subprocesses inheriting the environment (the codex CLI).
`ANTHROPIC_API_KEY` is reused for `claude-api`; `openai-api` needs a new `OPENAI_API_KEY`,
which must be added to `.env.example` and to `make doctor`'s provider rows.

---

## 9. Testing and gates

**Unit (hermetic, no network — the standing rule).** Every adapter is tested with an
injected fake transport / fake subprocess. Specifically:

- `extract` raising → posting **kept**, not discarded (the err-toward-keep invariant).
- Quote grounding: a quote present in the JD disqualifies; a **hallucinated quote does
  not** — this is the security property of the whole design and gets a dedicated test.
- `NO_SPONSOR_PHRASES` can only add a disqualification, never veto a model pass.
- Scorer fallback consumed when the screen produced nothing; **ignored** when the screen
  produced a verdict.
- `none` backend: deterministic gates still fire; no LLM call attempted.
- Auto-detection never returns a paid backend.
- Concurrency: results are correctly associated with their postings under a pool (the
  ordering hazard), and all DB writes happen on the calling thread.

**Sponsorship labeled set (the correctness gate for §5).** Cheap route: run the new
quote-grounded screen and the current phrase list over the ~600 already-scored rows and
diff. Agreements are free labels; only the **disagreements** need hand-labeling, into
three classes — *no-sponsorship / offers / silent*. Report recall against the 11 realistic
phrasings already measured in the notes, and precision on the silent class (the
misclassification risk from §5).

**Scorer-prompt gate (mandatory for §6).** `tools/score_eval.py` against the 23-row golden
set, **two consecutive PASS** before shipping, per the standing rule for any `score.txt`
change. ~69 Codex messages per run, so ~140 total — a few percent of the weekly budget.

This gate is already owed for the 2026-07-22 `personal_profile.txt` edit (P2 item 5), so
both changes can ride one run. Note the golden set's documented Java blind spot and
`tools/score_eval.py`'s lack of argparse — any unrecognized flag starts a **live,
quota-spending** run; `--selftest` is the free hermetic path.

Coverage floor stays `fail_under = 85`.

---

## 10. Risks and open questions

- **`gpt-5.6-luna` is unverified for this task.** `run.py` rejects luna for fit scoring on
  measured golden-set grounds (~3x looser spread, gate 76%/38% flip). That verdict was
  measured on *calibration-sensitive judgment*; extraction has no spread to blow, and luna
  is what the docs recommend for classification. It must be **re-measured on extraction,
  not assumed to transfer** — in either direction. Until then `gpt-5.6-sol` is the safe
  fallback for the codex screen.
- **Scorer-prompt destabilization (§6).** Documented history; mitigated only by the §9
  gate. If the gate fails, the fallback check is dropped, not shipped anyway.
- **Misclassification survives quote-grounding (§5).** Hallucination is closed by
  construction; a model quoting real-but-irrelevant text is not. This is what the labeled
  set measures.
- **`none` is genuinely low-recall on sponsorship** — deterministic gates plus a 2/11
  phrase list. Must be documented in `SETUP.md` and surfaced by `onboard-me`, not
  presented as an equivalent option.
- **Per-backend worker defaults are estimates**, not measurements. They are configurable
  precisely because the right number depends on the host.

---

## 11. Suggested staging

This is a large scope for one landing. It decomposes cleanly along its correctness gates,
and each stage is independently shippable and green:

1. **The seam + `ollama` + `none`.** Inject `extract`, add `make_screener`, port the
   existing Ollama call behind it. No behavior change on the default path; `none`
   unblocks the GPU-less user immediately. No new gate needed.
2. **The hosted backends** (`claude-api`, `openai-api`, `codex`, `claude-code`). Pure
   addition behind the seam from stage 1.
3. **Sponsorship rework.** Gated by the labeled set (§9).
4. **Scorer fallback check.** Gated by two consecutive `score_eval` PASS (§9) — the only
   stage that can be blocked by its gate, and the only one that touches `score.txt`.
5. **Concurrency.** Screen loop, then fit loop. Independent of 1-4; could land first.

Stage 1 alone satisfies "a GPU-less user can run a pass", which is the P1 premise.

## 12. Definition of done

- Six backends selectable; default unchanged; auto-detection never picks a paid one.
- A GPU-less user can run a full pass end-to-end.
- Sponsorship recall measured against the labeled set and reported.
- Hallucinated quotes provably cannot disqualify (test, not assertion).
- Screen and fit loops concurrent, with Ollama defaulting to 1 worker.
- Two consecutive `score_eval` PASS before the scorer change ships.
- `SPEC.md` §7.1/§12, `PROGRESS.md`, `CHANGELOG.md`, `SETUP.md`, and `.env.example`
  updated in the same commits as the behavior.
