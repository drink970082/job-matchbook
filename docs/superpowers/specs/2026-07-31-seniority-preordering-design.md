# Free seniority pre-ordering — the shape decisions

**Status:** approved 2026-07-31 (operator chose the ordering mechanism; see Fork 1)

This records the *shape* calls only. The measurement that justifies the layer — the
verdict matrix, the P/R, the veto, the false-demotion analysis — is the first In-flight
entry in [`PROGRESS.md`](../../PROGRESS.md), and the behavior contract is
[`SCORING.md`](../../SCORING.md) §9.4. Neither is repeated here.

## Fork 1 — how a demoted row sorts to the back

The `new` queue is `COALESCE(updated_at,'') DESC, id DESC`. Three ways to push a row
behind its peers:

| | Mechanism | Why not |
|---|---|---|
| **(a)** | A new Prisma column, `deprioritized_at`, leading the `ORDER BY` | **CHOSEN** |
| (b) | Backdate `updated_at` | Corrupts a real timestamp that other queries and the UI read as "when did this row last change". Irreversible: the original value is gone. |
| (c) | `ORDER BY CASE WHEN score_detail LIKE '%…%'` | Cheap and ugly. Puts queue semantics inside a JSON blob, unindexable, and `score_detail` is NULL on a `new` row so it would have to start being written there. |

**(a) is the operator's call**, made 2026-07-31. It is the only one that stays legible in
the web UI and reverses exactly: `UPDATE job_postings SET deprioritized_at=NULL`
restores every row's original position, row for row.

The column is a **timestamp, not a boolean**, for one reason: when the demotion happened
is the thing an operator will want when the layer misbehaves. It costs the same.

## Fork 2 — a separate model call, or folded into the screen prompt

Folding the seniority clause into `prompts/screen.txt` would make it cost **zero** extra
calls, since the screen already runs on every row. It is not free, though: `screen.txt`
is gated by `make eval-screen`, so folding puts the degree / authorization / clearance
extractions behind *this* layer's eval too, and every future seniority tweak re-opens
that gate.

**Decision: a separate prompt file and a separate call**, gated by its own
`make eval-seniority`. Revisit once both gates have been green across a few changes —
the merge is a pure cost win and nothing else.

## Fork 3 — what the layer may do to a row

**Re-order only. Never discard.** The training signal is the strong scorer's own
verdicts, not human labels, so it inherits that scorer's errors — two are on record where
Sol contradicted its own rubric and the free layer was right. Good enough to decide which
row gets the next paid call; not good enough to delete a posting. A false demotion costs
a delay on a row the notify gate was going to drop anyway; the measured count of false
demotions on the notify payoff set (`domain=match`) is **0**, and that is the gate.

## Not built, deliberately

- **A title-token floor** for the "Senior …" titles the model returns an empty object on
  (6 of 19 misses). That is a *discard*-direction floor, so SCORING §9.3 applies and it
  needs its own measurement first.
- **A skip-reason column or a paid audit sample.** The demotion is already observable:
  the row stays `new` and searchable, and the column says when.
