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

`db/scorer_usage.json`, read live at 11:30 EDT: **37%** of the weekly primary window
used, window resets 2026-08-05 (epoch 1785905532). Measured separately from 212
historical rollouts: **12.2 calls per 1% of the window**, i.e. a full window is roughly
**1,225 calls** of this prompt shape. So the 60-call budget is about **4.9%** — the
authorization and the arithmetic agree.

## Rules for spending

- Nothing is spent until the free forensics for that phase have run and justified it.
- A probe that comes back ambiguous is re-run **once**, then abandoned — no third try.
- The Luna A/B (Phase 4) is capped at 50 and only runs if Phases 1 and 2 landed green.
- If the daemon trips a circuit breaker or logs a traceback, stop spending and report.
