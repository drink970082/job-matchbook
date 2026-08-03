# Handoff - 2026-07-31 (eval corpora and screen backends)

> **Sibling note, same day, different session:**
> [`2026-07-31-handoff-and-next-steps.md`](./2026-07-31-handoff-and-next-steps.md) covers
> the unattended quota-levers run. The two overlap on one fact and agree: that session
> found the ChatGPT quota has been **per-token credits since April 2026** (Sol 125 /
> Luna 25 per 1M input), which is the *mechanism* behind this note's observation that 249
> luna screen calls moved the meter 41% -> 41%. Luna is ~5x cheaper per token, and the
> meter never counted messages. The 14:09 luna screen report this session found on disk
> was that session's run, not a stale artifact.


Session note, not a spec. Every number below was measured on this date against the live
DB (`db/applications.db`, read-only) and the live `apps/worker/config.yaml`; re-measure
before quoting any of them.

> **SUPERSEDED IN PART, later the same day — read this box before the four items.**
> The session that wrote the items below went on to measure them, and three of the four
> premises moved. Authoritative record is `PROGRESS.md` (In flight + Defects) and
> `BACKLOG.md`; this note is kept for the reasoning, not the numbers.
>
> 1. **Item 1 (terra re-measurement) is BLOCKED, and worse than blocked.** 22 of the 23
>    rows in `eval/golden.jsonl` name postings no longer in the DB, so `make eval-score`
>    was scoring **one row** and reporting *PASS at 100%*. Pre-existing (the 02:10 backup
>    already had 1/23) and not an application delete — there is no
>    `DELETE FROM job_postings` anywhere. The labels are unrecoverable: remapping by title
>    was tried and two different golden rows fuzzy-matched the same candidates. **So the
>    standing terra rejection rests on a corpus that no longer exists.**
> 2. **Item 2 (title sweep) is DONE** — 1,298 free-gate discards, queue 5,729 -> 4,430,
>    **zero** paid calls, and the web now has a `prefilter` discard cause so those rows are
>    selectable.
> 3. **Item 3 (stale companies) inverted: delete nothing.** The measurement used the wrong
>    join key *and* the wrong population — the watchlist is 172 DB rows, not the 39 in
>    `config.yaml`. Probed live, every slug resolved and no adapter failed. Voleon turned
>    out to be on the **wrong platform**: `ashby/voleon` serves 54 postings where
>    `lever/voleon` serves 0, and it is the only company in that set that has ever produced
>    a notification — deleting it, which is what the item proposed, would have destroyed it.
> 4. **Item 4's corpus was regenerated** at the full negative class (499 rows, not 162) and
>    now writes into `eval/` rather than tracked `tools/`, because those rows carry real
>    company names and titles and this repo is public.
>
> **What the session actually shipped instead:** a same-day screen A/B
> (`ollama` 4 false disqualifications vs `codex`/luna 1, on 12/12 vs 1/24 bad draws), the
> screen corpus expanded 83 -> 103 so both of its blind halves can now fail, and
> `golden.jsonl` made self-contained so it cannot rot the same way twice.

Standing context: **quota is the priority** (PROGRESS.md). Items 2 and 3 are free levers
on intake. Item 1 is the paid lever. Item 4 is the instrument item 1 needs.

---

## 1. Re-measure `gpt-5.6-terra` first

**This is the operator's instruction, and it also stands on its own merits.** Both halves
matter, because the merits are what say how to run it.

Terra was rejected once (SPEC section 7.1, CHANGELOG 2026-07-16): a synthetic probe
favored it - tighter spread, **half the credits** - but on the golden set it lost,
**gate agreement 76% vs sol's 86%**, flip 38% vs 29%. Sol stands today.

The merit is in the denominator. That golden set is **23 rows**. 76% vs 86% of 23 rows is
**17.5 vs 19.8 - a gap of about two rows.** A two-row gap on 23 hand-labeled rows does not
separate two models; it is inside the noise the golden set itself carries (see the
`fit-score-noise` history in SCORING.md). And the thing terra was rejected *against* is now
the binding constraint: it is half the credits, on a system where the weekly Codex window
is the reason work is parked.

So the rejection is not wrong, it is **underpowered** - which is exactly the case for
re-running it on a wider corpus rather than re-arguing it. That is item 4.

**What "first" means operationally:** run terra's re-measurement before spending effort on
items 2 and 3, because item 1 is the only one of the four that can change the spend
*per row*. Items 2 and 3 change the row *count*, and they will still be there afterward.

**Do not** promote terra on the expanded corpus alone. `make eval-score` over the 23 human
rows stays the gate; the expanded corpus is evidence for *whether it is worth running the
gate again*, not a substitute for it. See the caveats in item 4.

**Price the run before starting it, because it is not free.** The corpus is 499 rows and
only terra pays - sol's verdicts are already in the DB as the labels. At roughly one message
per row that is **~499 messages, on the order of 25% of the weekly Codex window**, against a
budget already set to `--score-limit 40` to stay near 92%. Two consequences: it competes
directly with the daemon's own spend, so run it in a window with headroom or pause the
daemon for it; and if it needs a second pass to settle a disagreement, budget for that up
front rather than discovering it at 50%. A cheaper first cut is the 30 `keep` + 89 `near`
rows only (~119 messages, ~6%), which answers the question that actually decides the swap
and leaves the false-positive check for a follow-up.

---

## 2. Title filters: 23% of the queue is already excludable by terms you have

**Sweep. Do not add terms.**

Measured today over the live `new` queue (5,729 rows), re-applying the *current*
`title_filter` / `title_exclude` from `config.yaml`:

| refused by | rows | share |
|---|---|---|
| positive `title_filter` | 0 | 0.0% |
| `title_exclude` | **1,298** | **22.7%** |
| **title, both filters - what phase 0 sweeps** | **1,298** | **22.7%** |
| age alone (`max_age_days=30`) | 491 | 8.6% |
| title + age together | 1,695 | 29.6% |

All 1,298 title refusals are one term: **`senior`**. No other `title_exclude` entry hits a
single row in the queue. The positive keep-list refuses nothing, which is expected - these
rows already passed it at ingest. **0 rows carry a null `posted_at`**, so nothing is
surviving the age gate by the err-toward-keep path.

Only the 1,298 is actionable. The age half of this is **deliberately refused** - a title
refusal is recoverable and an age refusal is not, and 474 of a comparable 587 aged out
*waiting in the queue* rather than arriving stale. `run.py`'s `stale_fn` passes
`max_age_days=0` for exactly this reason. See BACKLOG.md for the full argument; do not
re-propose the age sweep as an obvious symmetry.

**Trap, and it cost this note a wrong number - for the SECOND recorded time.**
`prefilter_postings(..., now=None)` does not mean "now": `_too_old` does
`date.fromisoformat("None"[:10])`, raises, and the `except` returns keep, so **a `now=None`
silently disables the age gate entirely.** An earlier draft of this section reported "age
refuses 0 rows (0.0%)" off exactly that mistake.

BACKLOG's intake-cut entry already documents it - a first pass there reported "438, and
essentially none on age" for the same reason, and concluded *"any offline use of this helper
must pass `now`"*. The rule was written down and still did not survive contact. **That is
the argument for changing the default rather than the documentation:** the err-toward-keep
`None` is right for production and quietly wrong for measurement, and two independent
sessions have now walked into it.

**Why they are still queued, and this is the actionable part.** `run_score`'s phase-0 sweep
already re-applies both title filters over the *whole* queue, free and outside the quota
budget (`pipeline.py:_sweep_free_gates`, `run.py:stale_fn`). It should have taken these
rows. It did not, because the running daemon is holding an older config:

- `apps/worker/config.yaml` mtime: **2026-07-31 13:29:51 EDT**
- `ats-worker` daemon (pid 2873899) started: **2026-07-31 09:17:07 EDT**
- passes ran 04:42, 08:44, 12:43 - all before the config edit

So the term was added after the daemon loaded its config. **The fix is a restart, not a
config change:** `systemctl --user restart ats-worker`, then read the next pass's phase-0
tally. Expect on the order of 1,298 free discards on the first pass after the restart, at
zero quota cost and ~0.26 ms/row.

At the measured ~0.8 paid messages/row, those 1,298 rows represent ~1,040 messages of
scoring on postings the operator's own config refuses - though the *live* exposure is much
smaller than that headline, for the same reason BACKLOG.md gives about the 655-row
measurement: the queue is newest-first, so most of these are parked by construction and
cost nothing until someone deliberately drains the backlog.

**The `sweep, don't add` conclusion:** the lever here is not a wider `title_exclude`. It is
making the sweep actually see the list that already exists. Adding terms before the restart
would measure nothing and risk over-refusing on a list nobody has validated against a live
pass. Note also that `senior` as a plain substring is the kind of short entry `config.yaml`'s
own comment warns about - it is a whole word here, so it is fine, but confirm the discard
sample after the first swept pass rather than assuming it.

---

## 3. The stale `companies:` block

**CORRECTED. The first version of this section was wrong twice, and BACKLOG had already
recorded one of the two mistakes.**

1. **Wrong join key.** It matched postings to watchlist rows on `company_name`. BACKLOG's
   intake-cut entry says explicitly: match on `(source, slug)`, the watchlist's actual key,
   and names the Headlands case where the display name differs between the two. Same
   mistake, made again.
2. **Wrong population.** It measured the 39 rows in `config.yaml`. The live watchlist is
   **172 rows in `watched_companies`**; config is a minority of it.

Re-measured on `(source, slug)`: **5 of 39 config rows and 16 of 172 DB rows have zero
ingested postings over all history.** BACKLOG already carries this at "eighteen" (now 16 —
two have since ingested), including the correction from an earlier nineteen.

**What survives, and it is the part BACKLOG does not have: the mechanism.** BACKLOG says
"zero is not proof of a broken slug — a small board may genuinely carry nothing past
`title_filter`". Probed live 2026-07-31 through the production `fetch_company`, the binding
gate is **not** `title_filter`, it is **age**. Every slug resolved, every adapter returned
cleanly, and not one of the 15 boards probed was broken.

**The three that are genuinely empty boards** - valid slug, adapter fine, zero postings
served: **Voleon** (lever), **TGS** (lever), **Millennium** (workday `mlp/wd5/mlpcareers`).
Nothing to fix. Millennium is worth a re-probe later - a workday tenant that large serving
nothing is odd, though the adapter itself is behaving.

**The other twelve are alive and serving postings that pass the title filters. Their
inventory is simply older than `max_age_days=30`:**

| company | served | pass title | survive full prefilter | newest title-ok posting |
|---|---|---|---|---|
| Virtu Financial | 48 | 31 | 0 | 2026-06-02 |
| Maven Securities | 36 | 18 | 1 | 2026-07-02 |
| TransMarket Group | 15 | 4 | 0 | 2026-06-02 |
| Geneva Trading | 14 | 10 | 0 | 2026-06-26 |
| GSA Capital | 10 | 5 | 1 | 2026-05-27 |
| Aquatic Capital Management | 9 | 7 | 0 | 2026-06-16 |
| Radix Trading (campus) | 8 | 7 | 0 | 2026-04-23 |
| Radix Trading (experienced) | 7 | 6 | 0 | 2026-06-26 |
| Valkyrie Trading | 6 | 5 | 0 | 2026-06-18 |
| Ansatz Capital | 5 | 4 | 0 | 2025-02-19 |
| Tudor Investment Group | 4 | 2 | 0 | 2025-06-11 |
| Chicago Trading (CTC) | 2 | 1 | 0 | 2026-01-05 |

**The 14-day metric was also the wrong instrument, independent of the join key.** "Rows
ingested in the last 14 days" counts INSERTS, and `upsert_postings` is
`ON CONFLICT DO NOTHING`. A board whose inventory is stable inserts nothing while being
perfectly healthy - the two rows GSA and Maven still have inside the window are already in
the DB, so they generate no new row and the board reads as dead. On a watchlist of boutique
trading firms with slow-moving reqs, behind a 30-day freshness gate, **near-zero insert
churn is the expected steady state, not a fault signal.** The shared 2026-07-13 last-seen
date needs no explanation on our side; it is just the last time these boards published.

**And it explains the zero-lifetime rows that still serve postings** (Geneva Trading, Radix
experienced): every title-passing posting they carry predates the freshness window, so
nothing has ever been eligible to insert. That is the age mechanism, measured - not a
`title_filter` effect and not a broken slug.

**What to do: nothing, and that is the useful answer.** Dropping low-yield boards is one of
the three named intake levers (PROGRESS.md), but there is no yield to reclaim here - these
boards already cost nothing past the fetch, because the age gate refuses their inventory
before any screen or paid call. The spend is one HTTP listing call per board per pass, and
at 6 passes/day that is the only thing dropping them would save. **Treat this as closed, not
as hygiene.**

**The one thing worth a follow-up:** if a board is fetched 6 times a day and its entire
inventory is age-refused every time, that fetch is pure waste. A cheap "no title-ok posting
inside the window for N consecutive passes -> skip this board for a day" rule would cover it.
That is an enhancement, not a defect, and it needs a measurement of what board fetches
actually cost before it is worth building.

---

## 4. The expanded score corpus

`apps/worker/tools/expand_golden.py` - untracked as of this note. Builds
`golden_expanded.jsonl` from rows Sol has already scored, deliberately as a **separate file**
from `eval/golden.jsonl`.

Output as regenerated today, after raising `MAX_CLEAR_NEGATIVES` from 30 to 400:

```
candidates with a Sol verdict: 499
  notified                     27
  domain=match (unnotified)    16
  domain=adjacent              89
  domain=mismatch             367  -> sampled 367

wrote 499 rows
bands:     keep 30 | near 89 | skip 380
seniority: match 244 | too_junior 255
domain:    match 43 | adjacent 89 | mismatch 367
overlap with the 23 human-labelled rows: 0
```

**499 rows against 23 is the point: it is the denominator item 1 needs.** And at 400 the cap
no longer binds - 367 of 367 negatives are kept, so the corpus is now the COMPLETE
population of rows Sol has scored, not a sample of it. The first draft of this note ran at
the old cap of 30 and produced 162 rows; that version is superseded.

### The four caveats

These are not disclaimers. Each one changes how a terra-vs-sol number off this corpus may
be read, and each one has a way it will be misread.

**1. The labels are Sol's own verdicts, not human labels.** This corpus measures
*agreement with the incumbent*, not correctness. The failure mode is specific and
counter-intuitive: **a terra that is genuinely better than sol scores as a regression here**,
because every row where it correctly disagrees counts against it. Treat a high agreement
number as "safe to swap" evidence and a low one as "look at the disagreements by hand" -
never as "terra is worse". This is the same trap `seniority_eval.py` documents in its own
header, and it is why the file is separate: merging it into `golden.jsonl` would silently
downgrade the authoritative gate from human labels to machine labels.

**2. The class balance is the SCORED population, not the raw queue - RESOLVED as a sampling
concern, but read it correctly.** At the old cap of 30 this was a live defect: the corpus
over-weighted `adjacent` 3x (55% of rows vs 18% of the pool) and the aggregate meant nothing.
At 400 there is no sampling left, so the balance is now exactly the production balance -
**for rows that reach the paid scorer.** That is the right denominator for a
terra-vs-sol decision and the wrong one for anything about intake: these 499 are all
post-prefilter, post-screen survivors. Do not quote a rate off this corpus as a statement
about the queue.

**3. The negative class dominates, and that is what makes the corpus useful - but it also
makes the headline number lazy.** 367 of 499 rows (74%) are `domain=mismatch`. A model that
answered "mismatch" to everything scores **74% agreement** on this corpus while being
worthless. **A single aggregate agreement number is therefore not a result.** The decision
needs, at minimum: agreement on the 30 `keep` rows (the notify positives - the expensive
half to get wrong), agreement on the 89 `near` rows (the band the gate turns on), and the
false-positive rate on the 367 negatives. Report all three or report nothing.

**4. Zero overlap with the 23 human rows, and the labels expire.** Overlap is 0 by
construction, so this corpus is a **complement, never a replacement** - `make eval-score`
over the human set stays the gate that decides anything. And every label here was stamped by
the *current* `score.txt` and `personal_profile.txt`. Any edit to either invalidates the
whole file, silently: the rows keep their labels and the labels stop meaning what they meant.
Regenerate after any prompt or profile change, and treat a corpus older than the last
`score.txt` commit as unusable.

### Where it writes, and why that matters

The script is read-only on the DB and writes `golden_expanded.jsonl` into
**`apps/worker/eval/`**, which `.gitignore:32` excludes wholesale. That directory is ignored
because the corpora carry real company names and job titles from live postings and this repo
is public - the same reason `screen_golden.jsonl` stores excerpts rather than whole JDs.
The first version wrote into `tools/`, which is tracked, and would have published exactly
that data on the next commit.

The script itself is tracked; its output is not, by the same rule that already covers
`golden.jsonl` and `screen_golden.jsonl`.

---

## Order, and why

1. **Terra re-measurement** - the only paid-per-row lever, and the operator's call.
   Needs item 4's corpus to be worth running.
2. **Restart the daemon** - one command, unblocks 23% of the queue for free, and is a
   prerequisite for reading anything about items 2 or 3 correctly.
3. **Stale companies** - DONE, and the answer is "delete nothing". Probed live 2026-07-31;
   all 15 boards healthy, the metric was counting inserts behind `ON CONFLICT DO NOTHING`.
4. **The corpus** - built and measured; the open question is only whether it gets tracked.

Item 2's restart is 30 seconds and gates the observability of everything else. If only one
thing gets done, do that.
