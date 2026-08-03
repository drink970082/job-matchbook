# Screen / score redesign: extraction first, rules from data

> **Execution 2026-08-03: steps 0-2 built on `feat/fit-extraction-shadow`.** The frozen
> hashes, the extraction schema and its shadow runner, and the 250-row stratified frame
> (`eval/frame_extraction.jsonl`) exist; see CHANGELOG and SPEC §13. **Step 3 is the next
> move and it is the operator's**, because it spends a paid pass over ~250 postings on
> each of two backends against the standing quota directive, and step 4 is human
> labelling. Nothing in steps 0-2 touches production state.
>
> **Status 2026-08-03.** Converged after two adversarial audits, then re-sequenced.
> The rebuild proceeds, but **extraction ships before the arithmetic** and the rubric's
> open rules are settled with measurements rather than argument. Sections 1-5 are the
> active plan; the DESIGN RECORD below holds the full reasoning and the known defects
> each step has to close.

---

## 0. The motivation, corrected

The plan was opened because six postings were notified at scores 52-58. **That is no
longer the reason, because the evidence killed it** (section 1). The rebuild proceeds on
four goals that were always the real ones and none of which are those six rows:

- **Tier filtering.** The operator wants to filter by target priority. A three-way
  `match/adjacent/mismatch` enum cannot express it.
- **Persona-agnostic engine.** This is an open-source tool; today's `domain` rule is
  shaped around one profile's structure.
- **Verifiable evidence.** `must_haves` is model self-report with nothing checking it
  against the posting text.
- **Cheaper models are reachable for bounded extraction** and were not for judgment.

Anything justified by "the six rows" is out of scope. Anything justified by the four
above stays in.

## 1. What the evidence says about the six rows

The plan was motivated by six postings notified at scores 52-58. Measuring the in-flight
blind relabel (`eval/codex_labels_20260802.jsonl` + `claude_code_labels_20260802.jsonl`,
287 rows each, two backends) against those six:

| id | production | codex relabel | claude relabel |
|---|---|---|---|
| 723 | match/match 55 | match/**mismatch** 38 | match/**adjacent** 40 |
| 738 | match/match 58 | match/match 55 | match/**adjacent** 33 |
| 25380 | match/match 58 | match/match 68 | match/**adjacent** 46 |
| 38786 | match/match 52 | match/**adjacent** 62 | match/**adjacent** 42 |
| 49597 | match/match 58 | match/**adjacent** 62 | match/**adjacent** 55 |
| 24900 | match/match 55 | not in corpus | not in corpus - but `military` is in `title_exclude`, so it is dropped at fetch |

**Not one survives as `match/match` in both arms**, so not one would pass today's gate.
Across the whole 287-row overlap only 16 rows are `match/match` in both.

The six rows are a **labelling / profile** problem, not a scoring-architecture problem, and
`SCORING 8.4` already records the lesson: *tune the profile, not the prompt*.

The rebuild's central mechanism would not even catch them: D2 rule 1 exempts 738 (its JD
states the "or equivalent industry experience" escape), scores 49597's eight gaps as
ordinary skills, and classes 38786's mandatory French as neither eligibility nor
credential. Three of six would score **higher** than today.

Both facts stand. They remove a justification; they do not remove the four in section 0.

## 2. Sequencing: extraction before arithmetic

The previous draft required D2's seven rules to be closed *before* production code. That
is backwards. At least four of them - relation weights, the dominance threshold, the
`requirement_type` boundary, empty-group handling - **cannot be decided without data**, so
scheduling them first meant deciding them with the least evidence available.

Inverted:

```
A. SHADOW extraction only                 runs beside the current scorer, decides nothing
B. Run both model families over the same stratified postings
C. Human labels: every DISAGREEMENT + an agreement sample
                 + a GRADED final relevance label
                 then cut development / held-out
D. Settle D2's seven rules on DEVELOPMENT data only
E. Verify on HELD-OUT, then cut over Stage 2 + gate + web in one move
F. Model downgrade, 2B arbiter, notification cap
```

### A is shadow, and that is a correctness requirement, not caution

The new extractor **must not replace the Stage 2 response.** `merge_fallback_screen`
(`screen.py:913`) refills a removed degree/clearance check from the fit call's `screen`
block; replacing that response leaves `demote_for_confirmation` with nothing to refill,
which materializes a pass verdict from a blind check. Section 4 records this as a
correctness defect.

```
current scorer   -> keeps deciding score / domain / gate
                 -> keeps emitting the secondary `screen` extraction
new extractor    -> its own column or artifact
                 -> writes no status, no gate input, never overwrites score_detail
```

"Ship" at step A means **the code runs offline / in shadow**, not that every new posting
immediately pays for a second model. Quota is still the standing priority.

### C needs an outcome label, not just extraction labels

Extraction labels alone cannot decide a relation weight, a dominance threshold, which
qualification gaps actually change a keep, or whether the final ranking matches the
operator's judgment. Every human-reviewed row also gets a **graded relevance**:

```
3 = high priority   2 = worth applying   1 = borderline   0 = not worth it
```

Graded, not binary, because NDCG@K needs graded relevance and binary keep/skip cannot
support it.

**Cut development / held-out before any rule is touched.** Development decides D2's rules,
the weights, the aggregator and the model; held-out only ever confirms. Using one set for
all of it is in-sample fitting wearing a verification badge. `seniority.py:214` is the
repo's precedent - a 32-row held-out slice is what turned a promising in-sample rule into
a documented ambiguity.

**Two implementation notes:**

- **Stratify deliberately, and restore the negative class.** The surviving golden corpus is
  15 keep / 54 near / **2 skip** - a gate whose job is to stop false keeps has almost no
  false-keep evidence. The sample must over-weight the thin classes and must include rows
  today's system gets *right*, or it can detect improvements but not regressions.
- **Freeze and stamp the profile first.** Graded relevance and concept mapping are both
  profile-dependent; `personal_profile.txt` changed 2026-08-02 and `config.yaml`
  2026-08-03, which is why all 501 stored scores are stale. Label against a frozen profile
  and stamp its hash on every row, or the corpus expires the next time it is edited.

The corpus gets built in the schema that will persist, and the human effort is spent once.
Under the old ordering it would have been spent twice: 28 of the 46 cross-model
disagreements in the current relabel are `adjacent` vs `mismatch`, a boundary this design
deletes - **61% of that review queue is resolving a distinction that will not exist.**

### The trap in step C, which is the whole risk

**Disagreement-only labeling has inverse coverage.** The new schema is closed-vocabulary
bounded extraction, so cross-model agreement should *rise*. Higher agreement means a
smaller human queue - which looks like success and is actually a **larger blind region**,
because where both models are wrong together nobody looks.

So the agreement sample is not optional and **scales up, not down, as agreement improves**.
Two failure modes are invisible to disagreement alone: both models inventing similar
duties (quote verification catches this in code, not labels), and both missing the same
requirement (only the sample catches it).

### What this does to `feat/golden-relabel`

That branch is claimed by another session. Under this ordering its `domain` half labels an
enum being deleted, so that asset depreciates. Two things keep their value: the
`seniority` half transfers whole (the new design keeps a seniority verdict, only
relocating it), and **the old system keeps running until the new one is measured** - the
relabel is the only thing that makes today's scorer changeable meanwhile.

This is a coordination question, not a technical one, and it should be raised early rather
than after more effort lands on a depreciated asset.

## 3. Step 0 is DOWNGRADED to a reversible experiment, not a merge

Earlier drafts made `AND score >= 60` the first merge, justified by "it removes exactly the
six complained-of rows". **That justification is dead and the draft was incoherent about
it** - section 0 says the six rows are no longer the reason while section 3 used them as
Step 0's headline effect.

The relabel evidence settles it: none of the six survives as `match/match` in either arm,
so the *verdict* already excludes them once labels are fresh. A score clause buys nothing
the fresh labels do not, while turning a number with a **13-point cross-model median
difference** into a gate - the thing `SCORING 8.6` and `9.3` both warn against, and a
contract break against `SPEC.md:1830` ("score is display/ranking only and gates nothing").

The failure mode it creates is concrete: correct seniority, correct domain, genuinely
worth notifying, and the model happens to say 58.

**So it ships as an experiment or not at all:**

- **Telegram only.** `get_notifiable` gets the clause; `matchedIds()` does **not**. The web
  Matched tab stays the full, unsuppressed view, so a wrong suppression remains visible and
  auditable. This deliberately breaks the UI/notify equality both code comments promise -
  say so in both, so nobody "fixes" the divergence.
- **Reversible by one constant**, and logged: count the rows suppressed and what a human
  judged them to be.
- **Decide with that data**, not now.

Notified scores are `52,55,55,58,58,58,68,68,...` - the gap above 58 is **ten** points, not
the six an earlier draft claimed (it misread the 30-row `match/match` set for the 27
notified rows). The gap is real; it is just not evidence that 60 is the right line.

## 3b. The relabel is dropped; the golden set is re-picked from scratch

Earlier drafts made `feat/golden-relabel` step 1. **That was wrong on all three of its
stated grounds:**

- *"The only thing that makes today's scorer changeable."* This plan leaves the current
  scorer untouched until the single cutover at step 7. The gate would be guarding a prompt
  nobody is going to edit.
- *"The seniority half transfers whole."* The seniority corpus is a **different file** -
  `seniority_golden.jsonl`, 446 rows, intact. The relabel's 287 rows add little there.
- *"It resolved the six rows."* Already banked in section 1. Continuing yields no more.

**And re-labelling cannot fix what is actually wrong with that corpus.** After the dead
rows it is **15 keep / 54 near / 2 skip**. A gate whose job is to stop false keeps has
almost no false-keep evidence - the same shape as the two recorded "gate that cannot fail"
incidents. Composition is not a labelling problem. On top of that, 61% of its cross-model
review queue (28 of 46) resolves `adjacent` vs `mismatch`, a boundary this design deletes.

A fresh pick gets four things a re-label structurally cannot:

1. **Deliberate stratification** - fixes 15/54/2, and must include rows today's system gets
   *right* or the corpus detects improvements but not regressions.
2. **Inline posting text from row one** - the absence of it is exactly why 22 rows died.
3. **A frozen, hashed profile** - `personal_profile.txt` changed 2026-08-02 and
   `config.yaml` 2026-08-03, which is why all 501 stored scores are stale.
4. **Graded relevance** - NDCG@K needs it; binary keep/skip cannot support it.

### Shape of the fresh set: large frame, small human cost

- **Sampling frame 200-300 postings** drawn from the 11,675 in the DB, stratified on
  current `domain` x `seniority`, company/source spread, and JD length.
- Human effort still only goes to **disagreements + an agreement sample** (step 4), so a
  bigger frame does not mean proportionally more labelling.
- Every row stores inline text and the profile hash it was labelled under.

### What survives the drop

- **The 64 human answers in `golden_review_answers.json`.** Their value is the `note`, not
  the enum - row 662 reads *"pure quant research and not engineering oriented sits
  anti-target"*, i.e. the human judged anti-target and the three-way enum flattened it.
  Those postings become **candidates** in the new frame with the note as context, not
  truth. Re-reading is far cheaper than re-judging.
- **`seniority_golden.jsonl` (446 rows) is untouched.** Open task, from the audit:
  `seniority_eval.py:103,191` builds its deciding filter from `assessment.domain.verdict`,
  so deleting the `domain` enum leaves that filter without a source. It needs a
  replacement before step 7.

### Coordination, which is not mine to settle

`feat/golden-relabel` is **claimed by another session** (`PROGRESS.md` In flight, "do not
pick it up"). This plan removes it from the execution order and records that its `domain`
output depreciates under the new schema. **Whether that work actually stops is a
conversation with that session, not a decision this document can make.**

## 4. Defects found while designing, worth filing regardless

- **The seniority layer buries rather than discards.** `get_by_status`'s docstring plus
  `deprioritized_at` leading the sort means a demoted row never resurfaces, yet it stays
  `pipeline_status='new'` with no reason code, invisible in the Discarded bucket and
  uncountable. The *honesty* half is worth fixing on its own. The *threshold* half is not
  yet priced: changing `>=` to `>` at `seniority.py:192` spares 61 of 251 `too_junior`
  corpus rows (24%), which cuts the only shipped quota lever by roughly a quarter.
- **`merge_fallback_screen` depends on the fit call's `screen` block.**
  `demote_for_confirmation` works by *removing* a failing degree/clearance check and
  letting `score.txt`'s secondary extraction refill it (`screen.py:885`, `:913`). Any
  future schema change that drops that block silently materializes a pass verdict from a
  blind check. This plan's own Phase 2 schema did exactly that and did not notice.
- **Fit-verdict rejects carry no `discard_reason`.** Only screen failures do; the web
  reconstructs the rest by complement.
- **`seniority_eval.py` reads `sol_domain` from `assessment.domain.verdict`** (`:103`,
  `:191`), so deleting the `domain` enum makes the 446-row seniority corpus's deciding
  filter unregenerable.
- **`eval/golden_review_answers.json`** holds 44 verdicts + 5 rejects with no consumer.

## 5. Locked execution order

```
0. Freeze the profile and hash it            everything below is labelled against it
1. Implement the extraction schema
     shadow / offline only; current scorer and its screen refill untouched
2. Pick the fresh golden frame               200-300 stratified postings, inline text
3. Run both model families over that frame
4. Human labelling
     every disagreement + agreement sample + extraction fields + graded relevance
     seed from the 64 existing review notes as context, not truth
5. Cut development / held-out
6. Decide the arithmetic on development data
7. Verify on held-out, then cut over Stage 2 + gate + web in ONE move
8. Then model downgrade, 2B arbiter, notification cap
```

`feat/golden-relabel` is **not in this order** - see 3b. It blocks nothing here, and its
`domain` output depreciates under the new schema.

### Deferred, and none of it blocks the above

| deferred | trigger |
|---|---|
| notification top-K / window / outbox | a day that actually overflows |
| 2B arbiter + 5% production blind-region audit | after cutover; step 4's agreement sample is the interim substitute |
| multiple aggregator plugins | a second strategy actually requested |
| duty-level bipartite alignment metrics | posting-level gate proving insufficient |
| fine-grained relation weight tuning | the sensitivity test showing weights matter |
| full multi-resume optimization | after cutover |
| finer hash layering + stale-score UI | after cutover |
| web bucket naming + full `discard_reason` | with step 8 |
| **seniority threshold rework** | fix only the *unobservable burying* now; the `>=`/`>` change costs 61 of 251 `too_junior` rows and stays unpriced |
| full model bake-off | needs the new extraction corpus first |

---

# DESIGN RECORD

Everything below is the full reasoning from the 2026-08-03 design session and two
adversarial audits. Steps A-E above draw on it; it is not itself an ordered plan, and
several parts are superseded by section 2.

**Known defects in this record, from the second audit. Step D must close them with data,
not argument:**

- D2 rule 1 misses three of the six rows it was written for.
- `fit_score` quantizes at least as coarsely as the number it replaces - one relation flip
  moves 7.9 points with 2 core duties, **45 points with one**.
- The dominance aggregator is undefined on ties, on zero total weight, and has no
  `target_bonus` for the `unresolved` outcome - which is also its most likely outcome.
- **Every abstention moves the score up** (`relation: unknown`, `status: uncertain`,
  item-cap truncation), and set-membership flip is in no metric.
- Section C's evidence rules contradict section D on `unknown`; C's "drop it and lower
  coverage" cannot lower a ratio it removes from both sides.
- Sections A and A2 specify two incompatible config schemas.
- `rank_score_raw` and `rank_score` are both used for the same field.
- Ephemeral concept refs break the `cache_control: ephemeral` byte-identical system prefix
  (`prompts.py:143`) - one of the two named token levers.
- **Deleting the fit call's `screen` block breaks `merge_fallback_screen`** (section 4),
  which is the refill for degree/clearance confirmation. Step A must keep that block.

## Context

Three defects drove this, all confirmed against the live DB (501 scored rows) and the code:

1. **`domain=adjacent` is a costume.** Parsing `TARGET: Priority N` out of every scored
   row's domain note: 42/43 `match` rows are priority 1-3, 83/84 parsed `adjacent` rows
   are priority 4-5. It routes nothing (0 pings from 89 rows) and the tier boundary is
   where the flip lives.
2. **The notify gate reads two of four scorecard axes.** `db.py get_notifiable` gates on
   `seniority` + `domain` + two thin-JD guards. It never reads `must_haves` and never
   reads `score` (except `ORDER BY score DESC`). Six notified rows scored 52-58.
3. **The score restates its own inputs.** The 0-100 bands are worded in terms of seniority
   and domain, which are already separate verdicts and already gate. The only thing moving
   across `match/match`'s observed 52-95 range is `must_haves`, and the bands never say
   how. Cross-model measurement: median absolute score difference **13 points**, p90 33,
   max 53 over 287 double-labeled rows.

A fourth surfaced during design: **the free seniority layer buries rather than discards.**
`get_by_status`'s own docstring - "a bounded pass always works the *back* of the backlog
... at 6 passes/day against a few thousand pending rows, that is weeks" - plus
`deprioritized_at` leading the sort means a demoted row is double-buried and never
resurfaces. `PROGRESS.md` calls the parked backlog "unreachable by construction". It is an
unlabelled discard: no reason code, absent from the Discarded bucket, uncountable.

Intended outcome: seniority becomes a screen concern that discards honestly, the domain
tier collapses to an anti-target check plus an explicit priority derived in code, the
model emits only bounded extraction, and every number is computed in code.

## The single rule the design turns on

**The model never interprets the operator's preferences.** It extracts what the JD and the
resume say, in a closed vocabulary. Code maps that onto priority and anti-target.

If the model still read the profile and emitted `target_priority` / `anti_target`
directly, this would be today's `domain` judgment with new field names and the flip would
survive the rename.

## Constraints carried from measured history

- `SCORING 9.1`: models cannot produce calibrated numbers here. Model emits categories and
  evidence; code emits every number.
- `SCORING 9.3`: a cheap-to-strong cascade is hostile *when the strong model is shown the
  cheap model's answer*. Any confirmation call must re-derive independently.
- `SCORING 8.7`: the transferable lesson is **methodology, not verdicts** - settle model
  choice on the golden set, never on a synthetic probe, and **run flip-rate, not
  agreement** (`SCORING.md:1668`: "an agreement number measured against one arm's own
  output cannot be the deciding test").
- **The existing model rejections are void for this scorer.** `gpt-5.6-luna` and
  `gpt-5.6-terra` were measured against a scorer that asked for a judgment plus a
  calibrated number. This asks for bounded extraction. Re-measure; do not default to
  `gpt-5.6-sol` because it won the old contest.
- `PRINCIPLES` uncertainty policy: a false discard is the expensive error. **Exception,
  decided by the operator:** seniority discards deliberately - see Phase 1.

## Authority order for filtering, as decided

1. **`title_exclude`** - code, fetch-time, terminal. Authoritative; a hit is out.
2. **screen checks** - degree / authorization / clearance / location / internships, plus
   seniority.
3. **profile ANTI-TARGETS** - content-based, for what the title could not reveal.

Note this means anti-target intent is expressed in two places today and the plan adds a
third. `config.yaml.example` warns that a title exclude "that over-reaches is invisible,
because the posting it wrongly dropped never appears anywhere for you to notice."

---

## BLOCKER - Phase 0 collides with a claimed branch

`PROGRESS.md` In flight: **`feat/golden-relabel`** - "Claimed by another session; **do not
pick it up.**" It is re-labelling the same corpus through the same `review_server.py`
sheet, producing the same `golden_review_answers.json`, and operator review was in
progress 2026-08-02. `PROGRESS.md:253` states outright: "The blind two-backend relabel
under In flight **is** the rebuild."

**Nothing in Phase 0 may start until that branch lands or is released.** Phases 1 and 5.2
do not depend on it.

---

## Phase 0 - Corpus

`golden.jsonl` is 93 rows: **keep 27 / near 55 / skip 11**, only 70 carrying an inline
`posting`. The unreachable rows are those with no inline text whose DB row is gone.

Two problems, the second larger: **59% of the corpus is labeled `near`, a band the new
schema does not have.** This is a re-label, not a repair.

1. **The repair job is 20 rows, not 22** (`PROGRESS.md`) - ids 132/184 are deliberately
   `marked` watch-list rows the gate excludes by policy.
2. **Stratify the replacements.** The dead rows are 12 keep / 9 skip / 1 near; dropping
   them leaves 15 keep / 54 near / **2 skip**, i.e. 82% of the negative class gone. A gate
   whose job is to stop false keeps cannot lose its false-keep evidence. Replacements must
   restore the keep/skip balance, not just the count.
3. Store inline posting text on every new row so the corpus stops depending on mutable DB
   state.
4. Extend the existing tooling rather than writing new: `eval/review_server.py`,
   `eval/golden_review.html`, `tools/label_golden.py`, `tools/expand_golden.py`.
5. **Label a 30-40 row pilot first.** Each new row costs an order of magnitude more than
   the old one (a relation + evidence per duty). Decide during the pilot whether `keep`
   becomes graded 0-3, because NDCG@K in Phase 5 needs graded relevance.

`seniority_golden.jsonl` (446 rows) is intact and needs no work.

### The corpus splits three ways, by what actually invalidates it

Binding every label to one `rubric_hash` would make a weight tweak invalidate the
extraction evidence. The dependencies are not the same:

| layer | contents | invalidated by | needs humans |
|---|---|---|---|
| **extraction golden** | duties, `importance`, relations, evidence validity | the model (flip), and `profile_hash` for concept mapping | **yes** - this is the expensive layer |
| **policy fixtures** | extracted record -> expected `fit_score`, `target_priority`, `anti_target`, deliverable | `rubric_hash` only | **no** |
| **delivery** | end-to-end verdicts | both | via the above |

**Policy fixtures need no human labeling at all** - they are hand-written input/output
pairs over the arithmetic, i.e. unit tests with provenance. So:

- swap the model -> re-run extraction eval only
- change a weight or bonus -> recompute policy fixtures only, no relabeling
- edit concept descriptions -> re-check the profile-dependent extraction labels

This is what makes a config-driven rubric affordable for an open-source tool where every
user runs a different rubric. Each layer stores the hash it was captured under and the
eval hard-fails on a mismatch.

### Cross-model consensus labeling - already the established workflow

**70 of the 93 golden rows already carry `label_source: "claude+codex consensus"`.** Two
rounds exist on disk, the second dated 2026-08-02 and unconsumed: `codex_labels.jsonl` +
`claude_labels.jsonl` (119 rows each) and `codex_labels_20260802.jsonl` +
`claude_code_labels_20260802.jsonl` (287 rows each, covering `relabel_corpus.jsonl`).

Measured agreement between the two 287-row files (different model families, the right
pairing against correlated error):

| field | agreement |
|---|---|
| seniority | 95% |
| domain | 84% |
| **both** | **79% -> human sees 59 of 287 rows (21%)** |
| `score` | median abs diff **13 points**, p90 33, max 53 |

**31 of 46 domain disagreements (67%) are `adjacent` vs `mismatch`** - the boundary this
redesign deletes; only 6 of 46 are `match` vs `mismatch`. So the new schema's human-review
load should land below the 21% measured here.

### Workflow, and its one non-skippable human step

1. Two models from **different families** (`SCORE_BACKEND=codex` and `claude-code`) label
   every row under the new schema.
2. **Agree -> auto-accept**, stamped `label_source: consensus`.
3. **Disagree -> human**, through `review_server.py`.
4. **Human-audit a ~10% random sample of the agreements.** Steps 1-3 give a *disagreement*
   rate, not an *error* rate; two models can agree and both be wrong. If sampled
   false-agreement exceeds ~5%, that field reverts to full human labeling.
5. Fields whose ground truth is the **operator's preference** get consensus as a proposal
   only. `SCORING 8.4`: when the mapping keeps coming out wrong, edit the profile.

Precedent for how far model-derived labels go, from `seniority.py`: labels learned from a
model's verdicts "inherit Sol's errors and are good enough to order work, not to delete a
posting." Consensus labels gate regressions; the human-audited slice validates the
redesign.

---

## Phase 1 - Seniority moves to the screen and discards

Independent of Phase 0; can land first.

### Why discard rather than demote

The demote-not-discard design does not preserve anything - see Context. A row that will
never be reached should not be labelled `new`.

**On the P .975 objection.** Those labels "were learned against *Sol's verdicts, not human
labels*" (`seniority.py` docstring). The 4-of-5 false demotions that state exactly 2 years
are false relative to Sol, not relative to the operator's policy - a 0-year candidate
should not be shown a 2+ year bar. Precision measured against the wrong authority is not
an argument for burying rows.

### The rule

```
years > years_experience + YEARS_MARGIN        -> reject   (discard, reason=seniority)
body-stated rank leaking past title_exclude    -> reject
title/body rank disagreement, years vs rank
  disagreement, unclear degree substitution    -> confirm  (paid re-check)
blind / empty / capped / no stated bar         -> pass     (keep direction, unchanged)
```

The `>=` at `seniority.py:192` becomes `>`: equality is the operator's policy call, and
`YEARS_MARGIN` is the dial that expresses it.

**`YEARS_MARGIN` moves to `config.yaml`** beside the profile. Once it discards it is a
policy statement, not a fitted constant: margin 2 means "show me up to two years above
me", margin 0 means strict.

### The rank branch is now a leakage backstop, not a primary rule

`title_exclude` already covers all four `RANKS` as whole words. Of 11,675 postings, 2,498
carry a rank word, 2,302 are already `discarded`, and **all 196 still alive were created
in 2026-07 - none in August**, i.e. they predate the `title_exclude` rewrite (which also
recovered ~107 wasted paid calls). `rank_stated_in` reads the JD *body*, so the residual
is a non-ranked title whose text names a rank. Operator's call: **reject on leakage.**

This retires the ambiguity in `seniority.py:214` - the title-token floor measurement "came
back AMBIGUOUS" and produced the only false demotion on the 32-row held-out slice, but it
measured a population `title_exclude` now removes at fetch time. (That slice **created**
the ambiguity; it decided nothing.)

### Unpriced work this actually needs

- `gate()` (`screen.py:448`) writes `{"pass": bool, "note": str}` - **no third state
  exists**. `confirm` needs a screen-schema change.
- `_CONFIRMABLE_CHECKS` membership routes *failures* to confirmation, so adding seniority
  naively makes `reject` undiscardable. The two states need separate paths.
- `demote_for_confirmation` works by **removing** the failing check so Stage 2's own
  extraction answers it. Phase 2 stops Stage 2 emitting a seniority verdict, so a routed
  `confirm` would clear the check with nothing to refill it - `SCORING 9.3`'s
  "materializing a pass verdict from a blind check".
  **Resolution: seniority `confirm` gets its own path and never touches the fit scorer.**

  ```
  local seniority extraction  ->  confirm
      -> strong seniority extraction, reading the RAW JD independently
      -> code re-runs the SAME verdict() over the stronger extraction
  ```

  Only the extraction quality changes; the code rule is identical, so there is no second
  vote and no blind pass. It also does not need to see the local extraction's answer,
  which keeps it clear of `SCORING 9.3`.
- `screen.txt` has no `stated_min_years` / `stated_rank` field today.
- `seniority` joins the `discard_reason` vocabulary.
- **`make eval-seniority` is the gate and its bar is zero false disqualifications.** It
  matters *more* under discard semantics, not less.

---

## Phase 2 - Stage 2 schema and a code-computed score

Ships with Phase 3. Widening domain without the new score takes the notify-eligible pool
from 27 rows (today's actual gate output) to ~131.

### A. The closed vocabulary is the operator's own target list - no taxonomy

A free-text duty `category` flips on its own (`ml_infrastructure` / `ml_platform` /
`ml_systems` are one thing wearing three names), so it must be closed. But a **fixed
taxonomy is the wrong way to close it**: any hardcoded vocabulary is persona-shaped, and
making it operator-extensible re-opens the set.

**The profile already contains a finite, operator-authored, priority-ordered list.** That
list is the vocabulary. The model matches a duty against supplied text - `SCORING 9.2`
lever 1, the only intervention that has converged here.

```jsonc
"concept_mapping": { "status": "mapped", "refs": ["c_8f2a"] },   // see B for the full shape
"label": "builds model-serving infrastructure"   // FREE TEXT, DISPLAY ONLY, never computed on
```

**Stable ids in config, ephemeral refs on the wire.** The profile gives each concept a
stable id (`ml-platform`); each request mints a throwaway opaque ref (`c_8f2a`) for it, and
code maps the answer back. The list is shuffled and carries neither `kind` nor `priority`.

This matters because an earlier draft said "list position *is* the priority", which
contradicts opaque ids and silently repoints every stored ref the moment the operator
reorders or inserts a concept. Priority is a declared property, never positional:

```yaml
concepts:
  - id: ml-platform
    description: "..."
    kind: target
    priority: primary          # a NAME, resolved via priority_levels

priority_levels:
  primary:    { rank: 1, bonus: 10 }
  secondary:  { rank: 2, bonus: 4 }
  acceptable: { rank: 3, bonus: 0 }
  none:       { rank: 99, bonus: -12 }
```

Three tiers, five, or none - nothing in the engine assumes a 1-5 scale.

- **Universal** - the vocabulary comes from the profile; the engine never knows a domain.
- **Cannot expand** - its size is exactly what the operator wrote.
- **No `taxonomy_version`** - the version key is the profile hash, computed over
  **canonicalized** config (sorted keys, normalized whitespace) so that reformatting the
  YAML does not invalidate every stored score.

`label` stays free text on purpose: phrasing drift is harmless when nothing computes on it.

### A2. What the engine fixes vs. what the profile supplies

This is an open-source, persona-agnostic tool. **The engine fixes the language and the
executor; it never fixes the operator's preferences.**

| fixed in engine | supplied by profile / config |
|---|---|
| duty / qualification / nice-to-have record shape | which concepts exist, and their descriptions |
| `importance` enum (core/supporting/incidental) | `kind` (target vs anti_target) per concept |
| `candidate_relation` enum (5 values) | how many priority levels, and their bonuses |
| evidence `{quote, source}` shape + verification | relation weights, group weights |
| schema validation and hashing | anti-target policy, thresholds, top-K, seniority margin |

Concepts are declared, not enumerated by the engine:

```yaml
fit_profile:
  concepts:
    - id: t_ml_platform
      description: "Building infrastructure used to train, deploy, serve, evaluate
                    or monitor machine-learning models."
      kind: target
      priority: 1
    - id: a_frontend
      description: "Work primarily focused on user interfaces, frontend components,
                    visual styling and browser application development."
      kind: anti_target
```

Priority levels are declared too - three tiers, five, or none - so nothing assumes a 1-5
scale.

**Config gets bounds even though its content is free.** Structure is validated, semantics
never are:

- concept ids unique and non-empty; every `priority` resolves to a declared level
- an `anti_target` concept may not carry a target priority
- descriptions non-empty, with a max length
- weights and bonuses finite and non-negative; at least one group weight > 0
- `unknown` explicitly declared as excluded-or-numeric
- `dominance_threshold` in (0, 1]
- at least one usable target concept, or an explicit opt-in to anti-target-only
- **a concept-count ceiling** - warn at ~20, hard maximum configurable

The count bound matters more than it looks: 100 overlapping concepts inflates prompt
tokens, raises mapping flip, starves every macro-F1 class of support, and pushes the model
to fill all 3 ref slots on every duty. It is a shipped default and a warning, not a
hardcoded domain.

**Config-driven policy couples the eval corpus to one config** - every label's expected
outcome becomes a function of the weights and the aggregator. Binding the whole corpus to
a `rubric_hash` would mean a single bonus edit invalidates the extractor evidence too.
Resolved by splitting the corpus along its actual dependencies - see Phase 0 - and the
eval **refuses to run on a hash mismatch rather than reporting a meaningless PASS.**

**Configurable values now; configurable strategies later.** Concepts, priorities, weights
and thresholds are config. **Exactly one aggregator and one anti-target policy ship** -
the five-aggregator menu (`best_core` / `worst_core` / `median_core` / `weighted_mode` /
`dominant`) is a framework built before a second user exists. Extract the interface when a
second strategy is actually requested, not on speculation.

### B. Model output - extraction only

```jsonc
{
  "duties": [                                  // max 5
    { "label": "...",                          // display only
      "importance": "core | supporting | incidental",
      "concept_mapping": {                     // status is EXPLICIT, never a fake id
        "status": "mapped | none | uncertain", //   mapped -> refs non-empty
        "refs": ["c_8f2a", "c_a921"]           //   none -> empty; uncertain -> may hold candidates
      },                                       // max 3 refs
      "candidate_relation": "direct_match | adjacent_match | weak_match | missing | unknown",
      "job_evidence":    { "quote": "...", "source": "description" },
      "resume_evidence": { "quote": "...", "source": "resume:default:experience:2" } }
  ],
  "required_qualifications": [                 // max 8
    { "requirement": "...",
      "requirement_type": "eligibility | credential | skill | experience",
      "relation": "<same five>", "job_evidence": {...}, "resume_evidence": null }
  ],
  "nice_to_haves":           [ /* max 5, same shape */ ],
  "summary": "one line, the bottom-line fit",     // display only
  "insufficient_context": false
}
```

With two or more resumes the per-item `candidate_relation` / `resume_evidence` fields are
carried per resume label under `resume_results` instead - see below. No
`recommended_resume`: code derives it.

`refs` is a list because a duty genuinely spans concepts - "build React dashboards for
monitoring ML inference" hits an ML-platform target *and* a frontend anti-target. Forcing
a single ref makes the model pick one, which is where the flip comes back.

`status` is a separate field rather than a sentinel id (`"none"` / `"uncertain"` posing as
concept ids) so that id validation, hashing and the aggregator have no special branches.

**A `strength: direct | related` field was drafted and is deleted.** Nothing in the rubric
reads it. A schema field that looks load-bearing but is consumed by no rule costs tokens,
makes the model deliberate over it, and misleads the next reader. Add it when a rule
actually needs it.

Absent by design: no `score`, no `confidence`, no `estimated_share`, no
`evidence_coverage`, no `target_priority`, no `anti_target`.

`summary` is retained for `notify.py:42-77`'s `Fit: {summary}` line (shipped 2026-07-30)
and is **display-only** - no rule may read it.

**`recommended_resume` is deleted from the model's output.** With multiple resumes the
model can cite resume 1 on one duty and resume 2 on the next, producing a composite fit
score no single resume earns. Instead the model emits **one relation record per resume**:

```jsonc
"resume_results": { "backend": { /* relations + evidence */ },
                    "ml":      { /* relations + evidence */ } }
```

Code scores each independently and takes the argmax - so the recommendation is a
derivation, not a model output, and cross-resume mixing is structurally impossible rather
than merely detectable. This is what `score.txt` already asks for in prose ("assess fit
for each version independently, score the BEST-fitting version"); `REJECTED.md` records
that as the shipped design whose missing half is *verification*.

**Cost note:** doing this in one call is not the saving it appears to be. Quota is
per-TOKEN, not per-message (`SCORING 4.5`, measured 2026-07-31), so N resumes means N x
the relation output either way; one call only saves the repeated prompt prefix. Choose
between one call and N calls on **stability**, not on call count.

### C. Evidence must survive a code check

```python
normalize(quote) in normalize(source_text)     # whitespace, unicode dashes, case
```

This generalizes a shipped mechanism: `score.txt:33` already requires the sponsorship
sentence "copied verbatim ... verified against the posting and a sentence that does not
appear there is discarded."

**The two sides fail differently and must be handled differently** - a single rule gets one
of them backwards:

```python
if not valid(job_evidence):
    # the JD item itself may not exist - the model may have invented the requirement.
    # DROP it; never penalise the candidate for a hallucinated requirement.
    # If it was a core duty or a required qualification, that is material:
    # lower evidence_coverage and route to 2B.
elif relation != "missing" and not valid(resume_evidence):
    # the JD item is real; the claimed candidate evidence is not.
    # KEEP it, contribute 0, keep it in the denominator.
```

An earlier draft used one rule for both, which meant a hallucinated JD requirement could
*lower* the candidate's score - punishing them for the model's invention.

New work implied: resumes are `{label: text}` today, so stable section ids need a chunking
step. The whole resume-side evidence check depends on it.

### D. `score/rubric.py` - every number, in code, from config

All values below are **shipped defaults in config, not engine constants.**

```
relation weight:   direct 1.00 | adjacent 0.65 | weak 0.30 | missing 0.00
                   unknown -> excluded from the denominator
                   (failed quote verification -> weight 0, KEPT in the denominator)

concept resolution: each duty's concept_refs -> (kind, priority) via the profile

anti_target:  core duty on an anti concept          -> yes
              supporting duty on an anti concept    -> uncertain  (routes to 2B)
              incidental duty on an anti concept    -> ignored
              core target AND core anti on one duty -> yes        (ANTI still wins)

target_priority: DOMINANCE over duties, weighted by importance
                 (core 4 / supporting 2 / incidental 0)
                 ONE DUTY CASTS ONE VOTE, however many refs it carries:
                   all its target refs share a priority -> vote that priority
                   its target refs disagree            -> that duty is unresolved -> 2B
                   status=none                          -> vote the `none` tier
                   status=uncertain                      -> that duty is unresolved;
                                                            its candidate refs DO NOT vote
                 anti refs are checked SEPARATELY and never consume the target vote

                 winner requires BOTH:
                   the maximum voting weight is held by exactly ONE priority, and
                   winner_weight / total_weight >= dominance_threshold   (config)
                 a tie at the maximum -> unresolved, even at 100% combined share
                 unique winner below the threshold -> unresolved

evidence_coverage = weighted known / weighted total     # a RATIO, denominator required
                    core 4 | supporting 2 | incidental 1 | required 3 | nice 1

fit_score      = weighted mean over non-empty groups, renormalized   0-100, DISPLAY
rank_score_raw = fit_score + target_bonus                            -12..110, ORDERING
```

Group weights: core duties 45 / required quals 33 / supporting duties 17 /
nice-to-haves 5. The `transferable` group is deleted - `adjacent_match` already measures
transferability, so a transferable group scored it twice.

Coverage is weighted, not counted, because `known/(known+unknown)` is gameable by
fragmentation. Item caps (5/8/5) bound that direction; synonym dedup deferred.

Persist `fit_score`, `target_bonus`, `rank_score_raw`, `evidence_coverage`,
`target_priority`, `anti_target`, `policy_flags`, `delivery_eligible`, `summary`, plus the
provenance hashes below.

### D3. Four hashes, not one, and the query must check them

`profile_hash` is too coarse. The model only ever sees a concept's **id and description** -
never its `kind`, `priority` or bonus - so re-tagging a target as an anti-target does not
invalidate a single extraction. Split by what each change actually breaks:

| hash | covers | a change means |
|---|---|---|
| `concept_vocab_hash` | concept ids + descriptions | re-run extraction; extraction golden may be stale |
| `preference_policy_hash` | `kind`, `priority`, bonuses, anti-target policy | re-run policy arithmetic only |
| `rubric_hash` | relation + group weights, aggregator config | recompute policy fixtures only |
| `resume_hash` | resume text | re-run candidate relations |

This lines up one-to-one with the three-layer corpus split in Phase 0.

**Storing them is not enough - `get_notifiable` must check them:**

```
score_is_current = stored concept_vocab_hash == current
               AND stored preference_policy_hash == current
               AND stored rubric_hash == current
               AND stored resume_hash == current
```

Without it a profile edit leaves stale scores being notified as if fresh.

**Consequence that needs an affordance:** the first profile edit will empty the notify
queue until a re-score runs. That is correct but reads exactly like a broken pipeline, so
`make doctor` must report "N scored rows are stale against the current profile" and the
pass must log it. A silent empty queue is the worst of both.

### D1. V1 has no 2B, so uncertainty needs a defined home

Phase 2 routes four states to 2B - `concept_mapping.status = uncertain`,
`target_priority = unresolved`, supporting anti-target `uncertain`, and material evidence
failure - while the rollout order puts the 2B router last. **V1 must therefore answer what
happens to those rows without it.**

```
any of the four  ->  needs_confirmation = true
                     NOT notified
                     visible in the web review bucket
```

`needs_confirmation` already exists (`pipeline.py:470` reads it, `_CONFIRMABLE_CHECKS`
produces it today), so this is a reuse, not new machinery.

**What V1 must never do** is silently collapse these to `anti_target='no'`, apply the
`none` bonus, or drop them into the discarded complement. Any of those hides the
uncertainty, which is `SCORING 9.3`'s "materializing a pass verdict from a blind check" -
the exact failure this redesign exists to stop.

The alternative is shipping a minimal 2B router alongside Phase 2 rather than after it.
Either is fine; leaving it undefined is not.

### D2. The seven rules, resolved

1. **Missing required qualification.** A plain weighted mean cannot express "this one
   thing ends it", which is why the six originating rows would score *higher* than today.
   Resolution: `requirement_type` (`eligibility | credential | skill | experience`) with a
   config policy - missing `eligibility` sets a **policy flag**, not a score cap; missing
   `credential` takes a large penalty unless the JD states an equivalence; missing `skill`
   scores normally; missing `experience` is already the seniority screen's job and is not
   re-gated here.

   **The flag must not be a cap.** Capping `rank_score_raw` *below `QUALITY_FLOOR`* makes
   the score a function of the delivery threshold - move the floor from 70 to 60 and the
   same posting's score changes - which is precisely the fit/delivery coupling this design
   forbids elsewhere. Instead:

   ```jsonc
   { "fit_score": 84, "rank_score_raw": 94,
     "policy_flags": { "missing_eligibility": true },
     "delivery_eligible": false }
   ```
   ```sql
   AND json_extract(score_detail,'$.delivery_eligible') = 1
   AND json_extract(score_detail,'$.rank_score_raw') >= QUALITY_FLOOR
   ```

   `fit_score` keeps meaning capability match, `rank_score_raw` keeps meaning preference
   order, and eligibility suppresses *delivery* without falsifying either. Soft
   suppression, never a hard discard - a wrong call stays visible in the UI and is
   correctable.
   **Two cautions.** `requirement_type` is a judgment field - better shaped than
   "required vs preferred" (which `SCORING 8.1` failed four times) because it asks about
   the requirement's *nature*, not its obligation strength, but it must be in the golden
   eval. And "unless the JD allows equivalent experience" is a *second* judgment - id 738
   is exactly that case ("PhD **or equivalent industry experience**"). Both must be
   measured, and eligibility must only **cap toward the floor, never set `disqualified`**:
   a wrong cap is visible and recoverable, a wrong disqualification deletes the posting.
2. **Empty groups.** Core duties empty -> `insufficient_context`. Any other empty group is
   excluded and the remainder renormalized over original relative weights. Never score an
   empty group 0 (punishes a JD for having no nice-to-haves) and never 0.5 (invents
   score). One rule, one code path - today the ambiguity is worth 22 points on id 723.
3. **`status: none` is a real tier, not a null.** Bonus `-12` (config). "Matches no
   stated target" and "priority 5" must not collapse to the same thing - 335 of 501 live
   rows (67%) carry no parseable target today. Deliberately soft: an unlisted job with an
   outstanding capability match can still clear the floor; a generic irrelevant one falls
   below it.
4. **Dominance, not `min()`, and not median.** `min()` lets one priority-1 core duty
   outvote four unrelated ones. Median over a 1-3 item list is itself noisy and needs two
   patch rules (even-count rounding, unmapped-core demotion) to behave. Importance-weighted
   dominance with a 50% threshold and an explicit `unresolved` outcome is one rule.
5. **Anti-target dominance** - resolved in D above. Core rejects, supporting confirms,
   incidental is ignored, so "occasionally maintains a dashboard" no longer kills a
   backend role while ANTI still wins on a core duty.
6. **Relation weights get a sensitivity test, not tuning.** Run three sets
   (1.00/0.75/0.40/0 · 1.00/0.65/0.30/0 · 1.00/0.50/0.20/0) and compare top-K overlap,
   NDCG@K, flips near the floor, and human-keep recall. If the three agree, the weights do
   not matter - ship the simplest (1 / 0.5 / 0.25 / 0). If they diverge, `relation` is a
   high-sensitivity field and the answer is a **bigger corpus, not the best-performing
   parameter set**. Never fit to 93 rows.
7. **No cap at 100.** `min(100, ...)` piles today's 93-95 rows onto the ceiling and
   destroys ordering exactly where the cap bites. `fit_score` stays 0-100 for display;
   `rank_score_raw` (-12..110) is what SQL orders by. The `, id ASC` tiebreak stays but
   stops being load-bearing.

### Plumbing

`score/screen.py` - `_DOMAIN_VERDICTS` deleted; `_normalize_assessment` validates the new
enums *and* every `concept_mapping.refs` entry against the ephemeral list minted for that
call, plus the `status`/`refs` consistency rule (mapped -> non-empty, none -> empty). It raises
`ScoreError` on out-of-enum values, so the prompt, the schema and this constant move **in
one commit** or every posting fails.

Bump `prompts.py SCORER_VERSION` (currently `"2026-07-24"`).

---

## Phase 3 - Delivery: quality floor + tiered cap

A fixed `score >= X` is not stable volume control - the distribution moves with model
version, profile edits and prompt changes.

```sql
status='scored'
AND json_extract(score_detail,'$.anti_target') = 'no'
AND json_extract(score_detail,'$.delivery_eligible') = 1
AND COALESCE(json_extract(score_detail,'$.needs_confirmation'),0) <> 1
AND COALESCE(json_extract(score_detail,'$.insufficient_context'),0) <> 1
AND LENGTH(TRIM(description)) >= 200
AND json_extract(score_detail,'$.rank_score_raw') >= QUALITY_FLOOR
-- plus the four hash-currency checks from D3
ORDER BY json_extract(score_detail,'$.rank_score_raw') DESC, id ASC
```

**Delivery config is separate from fit semantics** - `quality_floor`,
`immediate_threshold` and `daily_limit` are operational preferences and live in their own
config block, not in `fit_profile`. A change to how many alerts you want must not look
like a change to what counts as a good job.

Keep the `id ASC` tiebreak. Both constants named in `db.py` and
`apps/web/src/lib/constants.ts`, pinned by a sync test following
`test_low_context_threshold_matches_web` (`tests/test_source_enums_sync.py:112`), per the
`LOW_CONTEXT_MAX_DESCRIPTION_LENGTH` precedent at `db.py:21`.

### v1 ships the floor only. The cap is designed and deferred.

**No volume control in v1.** `run_notify` is untouched; the floor is the whole change.

The reason is evidence: 27 rows have been notified over the entire history, and the pool
has never been over-full. Widening to `adjacent` raises the *historical* eligible pool to
~131, but what decides overflow is the **daily arrival rate**, for which there is no
measurement at all. A cap sized by guesswork is worse than no cap - and `REJECTED.md`
(Notification outbox, d) records that "starvation is unreachable until a cap exists",
i.e. building one manufactures a problem that does not exist today.

**Designed, for when a day actually overflows** - a notification *window* rather than a
tiered daily cap, because tiering only moves the failure one tier down (an afternoon 74
against a morning of 70-73s):

```
rank >= immediate_threshold          -> send now
floor <= rank < immediate_threshold  -> enters the current window
at a fixed time each day             -> top-K of that window is sent,
                                        the window CLOSES; unselected rows do not
                                        roll over and re-compete forever
```

Operational state lives in a notification **outbox**, never on the score:

```jsonc
{ "posting_id": 123, "window_id": "2026-08-03",
  "delivery_state": "pending | sent | not_selected",
  "rank_score_snapshot": 78, "scored_at": "..." }
```

That closes all four holes at once - morning rows monopolising quota, indefinite
re-competition, `run_expire` reaping a waiting row, and per-day counts having nowhere to
live. It also settles the UI/notify contract cleanly: **Matched shows everything above the
floor; the outbox decides what gets pushed.** The two stop being required to be equal,
which is a documented separation rather than the broken invariant an earlier draft
implied.

Cost when it lands: a Prisma table + `make db-push`, and a `run_notify` rewrite.

**This deliberately breaks an invariant.** `db.py` and `actions.ts` both promise the UI's
Matched tab and the Telegram gate never disagree. Update both comments and the sync test
to state the new contract.

**`discard_reason` column** (Prisma owns the schema; then `make db-push`). Persist only
durable causes. **By the plan's own durability test only `hard_screen` and `model_failure`
qualify** - `below_score_floor`, `anti_target` and `insufficient_context` are all
re-derived on every score. Either loosen the criterion or store a scored-at snapshot.
`outside_top_k` stays a log line and a query-time computation.

**No silent caps:** the pass logs how many cleared the floor and how many were held.

---

## Phase 4 - Web

- `actions.ts` - delete `belowBarIds()`, the `'belowbar'` branch, the `JobBucket` member,
  its half of the `keepIds` union. The `discarded` bucket is the complement, so rows
  re-home automatically. **45 rows re-home, not 56** - the other 11 live in `lowcontext`,
  which is mutually exclusive.
- `matchedIds()` - swap the verdict predicate for `anti_target='no' AND rank_score >=
  QUALITY_FLOOR`.
- `score-detail.ts` - pills for the new fields; a tier pill driven by `target_priority`.
- Also consume `score_detail`: `JobDetailModal.tsx` (+ test), `score-detail.test.ts`,
  `test-utils/factories.ts`, `job-query-shape.test.ts`, `DiscoveredJobsTable.tsx` (+ test),
  `actions.test.ts`, `actions.int.test.ts`.

Buckets become matched / discarded / lowcontext / failed.

---

## Phase 5 - Model selection and routing

Nothing is pre-assigned, including the default backend.

### 5.1 Roles

| role | task | candidates |
|---|---|---|
| **2A extractor** | JD + resume -> duties, quals, evidence. No numbers. | `qwen3.5:4b` (free, local), luna, terra, sol, haiku-4.5, sonnet-5 |
| **2B arbiter** | independent re-derivation on routed rows | same list; likely a different winner |

Local candidates are bounded by VRAM - `seniority.py` notes the 9b spills to CPU on an 8GB
card (~100s/call).

### 5.0 Successive halving - the bake-off as first drafted is unaffordable

7 candidates x ~100 postings x K=3 is ~2,100 calls, against a standing quota directive and
a backend that costs 0.29pp of a 5-hour window per call. Staged instead:

| round | who | corpus | K | measures | ~calls |
|---|---|---|---|---|---|
| 1 | all 7 | 30 | 2 | schema compliance, quote validity, flip | 420 |
| 2 | top 3 | 100 | 3 | full per-field stability | 900 |
| 3 | top 2 | rebuilt golden | - | accuracy, NDCG, boundary behavior | - |
| 4 | winner + one other family | - | - | 2A/2B routing economics | - |

Round 1 costs ~420 calls instead of ~2,100, and only survivors reach the expensive rounds.

### 5.2 Screen 1 - no labels needed, runs in parallel with Phase 0

- **Schema compliance.** `_normalize_assessment` raises on out-of-enum values; count the
  raise rate over ~100 postings. Baseline: today's free-text `BACKGROUND:` field runs
  **17% off-vocabulary** across 501 rows (`no`/`yes`/`neither`/`partial`/`adjacent`/
  `limited`/`partially`, plus 20 rows answering in prose).
- **Self-consistency.** K=3 re-draws, no labels. Per-field flip on `concept_mapping`,
  `importance`, relations. This is `SCORING 8.7`'s endorsed metric.

### 5.3 Screen 2 - accuracy, after Phase 0

**First, an alignment problem that makes the naive version of this table undefined.** Gold
may record one duty ("build data pipelines and backend services") where the model records
two. Both readings are correct, but per-duty macro-F1 needs a 1:1 correspondence that does
not exist, so every duty-level metric below is *uncomputable* without an alignment rule.

**V1 gates on posting-level derived features**, which are segmentation-invariant:

```
set of concept ids x importance     derived target_priority
relation distribution               derived anti_target
```

Duty-level metrics stay as *diagnostics*, not gates. The bipartite-matching alternative
(align duties by quote overlap or semantic similarity, then score matched pairs, unmatched
gold recall and invented-duty rate) is the better measurement and is deferred: it turns
the eval harness into an NLP matching project, and the harness is already a rewrite.

Accepted cost: a posting-level gate **cannot localize which duty was misread.**

Per-field, because one accuracy number hides what matters:

| field | metric | why |
|---|---|---|
| duty `concept_mapping` | macro-F1 over concept ids, plus status accuracy | `target_priority` derives from it |
| `relation` | **macro-F1** | `direct_match` dominates; accuracy would hide weak/adjacent confusion |
| `anti_target` (derived) | **precision-first** | a false positive kills a job |
| `target_priority` (derived) | weighted kappa / mean abs tier error | human 1 vs model 2 is not human 1 vs model 5 |
| `importance` | macro-F1 | drives the coverage weights |
| delivery | precision@K, recall of human keeps, NDCG@K | what the operator experiences |
| evidence | quote-verification failure rate | free, no labels |

Plus **cost per 100 postings** in the binding currency and wall-clock per posting.

**Caveat:** 93 rows against ~8 list ids gives single-digit support per class. Either the
corpus grows or the metric suite shrinks - do not report macro-F1 on 11 rows per class as
if it were stable.

**Caveat 2:** these are measured against *consensus* labels, which `SCORING 8.7` says
cannot be the deciding test. Weight 5.2's flip-rate and the human-audited slice above
agreement numbers.

### 5.4 Decision rule

**The cheapest candidate clearing the accuracy and stability bar wins the role**, not the
most accurate. Write the bar down before running.

### 5.5 Harness

`tools/score_eval.py` reads `SCORE_BACKEND`, `CODEX_SCORE_MODEL` /
`CLAUDE_CODE_SCORE_MODEL` / `ANTHROPIC_SCORE_MODEL`, `GOLDEN_SET`, and **`SCORE_EVAL_OUT`
(required for A/Bs, or concurrent runs clobber one report)**.

**But its metrics do not exist for this schema.** PASS is currently "0 hard invariant
violations AND >=85% verdict agreement AND <20% verdict flip-rate" on `seniority`/`domain`
- both deleted. Rewriting it for per-field macro-F1, kappa and NDCG is a **substantial
build, not configuration**, and until it exists the redesign has no gate.

Prior artifacts for format: `eval/frame_sol.md`, `frame_terra.md`, `x_luna_103.md`,
`x_ollama_103.md`.

### 5.6 Routing

2B fires on: seniority `confirm`; `anti_target` `uncertain`; low `evidence_coverage`;
`rank_score` within +/-5 of the floor; duty labels conflict; title contradicts
responsibilities.

1. **2B must never see 2A's output.** Otherwise this is `SCORING 9.3`'s second-vote
   pattern.
2. **Audit the blind region.** The +/-5 router cannot catch a confidently-wrong score far
   from the floor - `SCORING 8.7` observed terra throwing `skip(28)` between two
   `keep(86+)`. Route a 5% random sample of non-routed rows so the blind region is
   measured.

### 5.7 Merge rule - whole records, never per-field

| case | result |
|---|---|
| not routed | 2A stands |
| routed, 2B succeeds | **2B's whole record replaces 2A's** |
| routed, 2B fails validation | keep 2A, flag `needs_confirmation` |
| the 5% audit sample | **records disagreement only; never changes production** |

No majority vote, no per-field averaging. Mixing produces a record whose fields never
co-occurred in one reading, whose evidence quotes no longer match its relations.

---

## Quota reality

`PROGRESS.md` carries a standing directive: **"QUOTA IS THE STANDING PRIORITY (operator's
call, 2026-07-31). Work that is not a quota lever waits."** Capacity is ~92% of the weekly
window at `--score-limit 40`.

This plan is a consumer, not a lever. Costs to price before committing:

- claude-code costs **0.29pp of the 5-hour session window per call** (~345 calls exhausts
  one window); codex 0.053%/call. Phase 5.2 alone (7 candidates x ~100 postings x K=3) is
  thousands of calls.
- **"The July re-score ran free" no longer prices anything.** `SCORING 4.5`: "The premise
  this design was built on is FALSE, measured 2026-07-31 ... it is **per-TOKEN credits**."
  The new schema is materially larger on both sides.
- Phase 1 is the one part that *is* a lever: discarding at screen cuts intake rather than
  reordering it, and 54% of paid "no"s are `too_junior`.

---

## Verification

| gate | command | bar |
|---|---|---|
| worker unit | `make test-worker` | green, coverage >= 85 |
| web unit + int | `make test-web` | green |
| lint | `make lint` | clean |
| schema drift | CI guard | clean after `make db-push` |
| **screen eval** | `make eval-screen` | **zero false disqualifications** (Phase 1) |
| **seniority eval** | `make eval-seniority` | P >= .975 and no new false rejects vs `eval/last_seniority_run.md`; **matters more under discard semantics, not less** |
| fit gate | `make eval-score` | PASS twice consecutively (`SCORING 8.4`) - **requires the harness rewrite in 5.5 first** |
| drift | `--drift-probe` | per-field flip measured; today's 5% is a per-verdict rate and not directly comparable |
| constant sync | new test beside `test_low_context_threshold_matches_web` | worker == web |

End-to-end: `make doctor`, then a single-posting pass through fetch -> screen -> score ->
notify against a seeded row, asserting `rank_score`, `discard_reason`, and that
`get_notifiable` and `matchedIds()` agree except for the cap.

Migration: re-score ~500 live rows under the new `SCORER_VERSION`.

---

## Order and blocking

*(Superseded by section 2 at the top of this file. Preserved as the ordering that was
worked out, in case the rebuild reopens.)*

```
STEP 0    score >= 60 in get_notifiable + matchedIds + sync test   <- the only part shipping
Phase 1   seniority discard, AFTER the independent confirm path exists
Phase 2   close D2's seven rules, then write the eval harness (5.5)
Phase 5   model selection by successive halving
Phase 2+3+4  ship together
Phase 5.6/5.7  2B router and the 5% audit, last
```

Blocking relations as worked out: **Phase 0 cannot start** while `feat/golden-relabel` is
claimed, and **no production code for Phase 2** until D2's seven rules are closed and the
harness in 5.5 exists - without it there is no way to tell whether any of this is better.
Phase 1 and Phase 5.0/5.2 do not depend on the corpus.

**Corrections to statistics used in the record below**, from the second audit and verified:
the widened pool is **72** (27 + 45), not ~131; `get_notifiable`'s output *today* is **3**
rows, not 27 (27 is the lifetime notified count); the gap above 58 is **ten** points, not
six; the "22 points" empty-group delta is an upper bound, not a per-row measurement; the
"~92% of the weekly window" figure is quoted against `PROGRESS.md`'s explicit instruction
not to reuse message-based arithmetic after the per-token correction.
