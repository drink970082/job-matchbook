# Quota ledger — 2026-07-31 unattended run

Budget authorized by the operator before the run: **60 paid Codex calls (~5% of the
weekly window)**. Hard cap. At 60, stop and report — do not spend a 61st for any reason.

Plan: [`../plans/2026-07-31-quota-levers-caching-and-vetoes.md`](../plans/2026-07-31-quota-levers-caching-and-vetoes.md)

**Every paid call gets a row here, written at the time it is spent.** A session that
picks this run up mid-way reads the total from this table, not from a guess.

| # | when (EDT) | phase | calls | running total | what it bought |
|---|---|---|---|---|---|
| — | 11:47 | 0 | 0 | **0** | worktree + validation, all free |

## Window state at the start of the run

**37%** of the weekly primary window used; it resets 2026-08-05 (epoch 1785905532).

**Where that number came from matters, because the repo has a standing warning about it.**
PROGRESS's Defects section says "do not read `db/scorer_usage.json` without checking its
mtime" — a 07-30 reading of "23%" was 8 hours stale and made a `--score-limit` decision
~17 points optimistic. This 37% is **not** from that file: it is a direct read of
`GET /backend-api/codex/usage` at 11:30 EDT, the endpoint `capture_usage` itself calls,
bypassing the snapshot. The on-disk snapshot at that moment said 35% with an `as_of` of
04:46 — stale, exactly as the warning predicts. That gap is a live instance of the
still-open `capture_usage` defect, not a number to quote.

Measured separately from 212 historical rollouts: **12.2 calls per 1% of the window**, so
a full window is roughly **1,225 calls of this prompt shape**, and 60 calls is about
**4.9%**.

**Read that conversion as an estimate with a moving denominator.** Billing is per token,
not per call — that is this run's whole thesis — so "calls per 1%" only holds while the
prompt shape does. Phase 1 exists to cut credits per call by up to 57%, and a Luna call
costs roughly a fifth of a Sol call. The 60-call cap is the operator's authorization taken
verbatim; the window percentage moves in the operator's favour as the run proceeds.

## Rules for spending

- Nothing is spent until the free forensics for that phase have run and justified it.
- A probe that comes back ambiguous is re-run **once**, then abandoned — no third try.
- The Luna A/B (Phase 4) is capped at 50 and only runs if Phases 1 and 2 landed green.
- If the daemon trips a circuit breaker or logs a traceback, stop spending and report.
