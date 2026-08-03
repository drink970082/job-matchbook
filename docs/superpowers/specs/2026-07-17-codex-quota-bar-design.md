# Codex quota usage bar — design

> **PREMISE CORRECTED 2026-08-01 — this document reasons from a quota model that is
> false.** The ChatGPT subscription bills **per-TOKEN credits**, not messages
> (measured 2026-07-31; SCORING §4.5). This is a dated design record and is left
> as written; do not carry its message-bound premise, or any sizing derived from
> it, into new work.

**Date:** 2026-07-17
**Status:** shipped 2026-07-17 (v1.0.0)
**Supersedes:** the "Codex message-quota usage tracker" item in
[`docs/PROGRESS.md`](../../PROGRESS.md) — see [What this replaces](#what-this-replaces).

## Problem

The `codex` fit-score backend runs on a ChatGPT-Plus subscription whose quota is
**message-bound with an opaque ceiling** — and the operator flies blind on how much
budget is left before a large re-score (the ~640-row backfill) blows it. The prior
plan (a homegrown call-counter estimating a rolling 5-hour window, plus exit-1 stderr
"capped" fingerprinting, plus a pacing gate) was built on two wrong assumptions,
corrected during this design:

1. **The limit is not 5-hourly.** The live snapshot reports
   `window_minutes: 10080` — a **weekly** window. (A shorter secondary window may also
   appear; see the data shape.)
2. **We don't need to estimate usage.** `codex` already computes it. Every API response
   carries a `rate_limits` record with `used_percent`, `resets_at`, and `plan_type` —
   exactly what the interactive `/status` slash-command displays. There is no
   non-interactive `codex status` subcommand, but the data is emitted on the response
   stream and we already make the responses.

So the feature collapses to: **capture what codex already tells us, and draw a bar.**

## Observed data shape

The `rate_limits` record, pulled live from a session rollout on 2026-07-17
(`~/.codex/sessions/.../rollout-*.jsonl`, `event_msg` → `payload.rate_limits`):

```json
{
  "limit_id": "codex",
  "limit_name": null,
  "primary":   { "used_percent": 32.0, "window_minutes": 10080, "resets_at": 1784839672 },
  "secondary": null,
  "plan_type": "plus",
  "rate_limit_reached_type": null
}
```

`primary` is the weekly window here; `secondary` is `null` on this account/moment but
the field exists (a shorter window on other plans/usage). The design renders whatever
non-null limits are present — it does not hardcode "weekly."

## Capture is free (piggyback, no probe)

`codex exec --json` prints these same events to stdout as JSONL. The scorer already
spends one `codex exec` message per `fit()` call; adding `--json` lets it read the
`rate_limits` off **its own response** — zero extra quota cost. A standalone "refresh"
would cost a message (the exact resource we're conserving), so it is out of scope: the
bar reflects the **last scoring call**, labeled "as of <time>". That is a budget
indicator, not a live meter — an accepted tradeoff.

Ephemeral scoring calls (`--ephemeral`) don't persist a rollout file, so reading
`~/.codex/sessions/` after the fact is not an option — capture must come off the live
stream. Hence `--json` on the scoring call itself.

## Components

Three small pieces, one per language boundary. Real file anchors below.

### 1. Capture — worker, `apps/worker/ats_worker/score.py`

In `make_codex_scorer`'s `fit()` closure (currently ~`score.py:901`), the `codex exec`
command gains **`--json`**. `--output-schema` / `--output-last-message` are unchanged —
the final scorecard still lands in `out.json` and is parsed exactly as today; `--json`
only changes stdout to JSONL events, which we additionally scan.

A small module-level helper (best-effort, never raises into the score path):

```python
def _capture_usage(stdout_text: str, path: str) -> None:
    """Scan codex --json stdout for the last rate_limits event and atomically
    write a snapshot to `path`. Any failure is swallowed — telemetry must never
    break a score."""
```

- Scan stdout lines for the last JSON object whose `payload.rate_limits` (or nested
  `rate_limits`) is present; take the newest.
- Reduce to the snapshot shape below (only non-null limits).
- **Atomic write:** write to `path + ".tmp"`, then `os.replace` — the web reads
  concurrently across the container boundary.
- Wrap the whole thing in `try/except Exception: pass`. A scoring pass must not fail
  because usage capture hiccuped.

Called after a **successful** `codex exec` (non-zero exit still raises `ScoreError`
first, unchanged). Fallback singles also flow through `fit()`, so they update the
snapshot too — fine, latest wins.

**Snapshot file** — `codex_usage.json`, written into the shared DB directory (the same
`db/` bind mount the SQLite file lives in; gitignored). Path derived from the worker's
existing DB-dir config, no new setting if avoidable.

```json
{
  "plan_type": "plus",
  "limits": [
    { "key": "primary", "used_percent": 32.0, "window_minutes": 10080, "resets_at": 1784839672 }
  ]
}
```

No `captured_at` field — the web uses the **file mtime** for "as of <time>", one less
thing to write and no clock to inject.

### 2. Store — a single JSON file

`db/codex_usage.json`, in the shared bind mount (`/data/codex_usage.json` inside
containers). Single writer (worker), single small overwrite-in-place file.

**Why a file, not a Prisma table:** the worker issues **no DDL** (Prisma owns the
schema), so a table means a `schema.prisma` edit + `make db-push` + a `check_schema_drift`
update + a raw-SQL writer — and `prisma db push` keeps no migration history (the "no
schema migration path" risk in PROGRESS). A one-row snapshot needs none of that. The
file sidesteps the entire fork. (Considered and rejected: single-source-of-truth via
SQLite. Not worth a migration for one cosmetic blob.)

### 3. Surface — web, `apps/web`

- **Route** `src/app/api/codex-usage/route.ts` — mirrors the existing
  `src/app/api/health/route.ts` pattern (`export const dynamic = 'force-dynamic'`).
  Reads `/data/codex_usage.json` via `fs`, returns `{ ...snapshot, as_of: <mtime ISO> }`.
  Missing file → `{ limits: [], as_of: null }` (200, empty state), not a 500 — the
  worker may not have scored yet.
- **Component** `src/components/CodexUsageBar.tsx` (client) — renders one bar per limit:
  `used_percent` fill, a friendly window label (`window_minutes` → `10080`=“weekly”,
  `300`=“5h”, else “{n}m”, or `limit_name` when codex provides one), the percent, and
  “resets in Nd Hh” computed from `resets_at` vs wall clock, plus an “as of <time>”
  caption. Empty state: “No codex usage recorded yet.” Polls the local route every
  ~60 s while mounted — free (reads the local file, never calls codex).
- **Placement** — **Discovered Jobs view only**, above the table. Rendered in
  `Dashboard.tsx` immediately before `<DiscoveredJobsTable>` (~`Dashboard.tsx:536`), so
  it does not clutter the main tracker. It sits where scoring and re-scores are the
  whole point.

## Error handling

- Worker capture is best-effort and swallowed; a broken capture leaves the last-good
  snapshot in place (stale but harmless) and never touches the score.
- Route returns an empty snapshot (not an error) when the file is absent or unparseable,
  so the UI degrades to "no usage recorded yet."
- The bar never triggers a codex call, so it cannot itself consume quota.

## Testing

- **Worker:** unit-test `_capture_usage` — (a) a realistic `--json` stdout with a
  `rate_limits` event produces the expected snapshot file; (b) `secondary` non-null is
  included; (c) malformed / absent event writes nothing and raises nothing; (d) the
  atomic write leaves no `.tmp` behind. No network, no real `codex` (feed captured
  stdout text). One assertion-based test file, in keeping with the worker's DI/mocked
  style.
- **Web:** a small test for the route's empty-file fallback and the component's
  window-label + "resets in" formatting (Jest, mirroring existing component tests).
- **Not tested end-to-end automatically:** the `--json` stream actually carrying
  `rate_limits` in this codex version — confirmed by one live scoring call during
  rollout (the nightly pass does this for free); noted as a rollout check, not a unit
  test, since it costs a message.

## What this replaces

On merge, update the docs in the same commit:

- **`docs/PROGRESS.md`** — the "Codex message-quota usage tracker" enhancement item and
  the "5h window" framing in the re-score economics passages are **corrected/closed**:
  the limit is weekly and codex-reported; the JSONL counter, stderr "capped"
  fingerprinting, and pacing-gate are dropped as unneeded. The remaining open question
  (how to *pace* a >100%-weekly re-score) is now answerable by reading the bar, not by
  building an estimator.
- **`docs/SPEC.md`** — add the usage-bar capability (capture point, snapshot file, route,
  component) to the capability map (§ web + § worker/score).
- **`CHANGELOG.md`** — feature entry.

## Out of scope (YAGNI)

- Manual "refresh now" button — costs a quota message; rejected by design.
- Active pacing gate that auto-sleeps a re-score near the cap — the bar makes pacing
  operable by hand; revisit only if unattended multi-window re-scores become routine.
- Historical usage graph / retention — the snapshot is latest-wins, one row.
- Prisma table / cross-service schema — see [Store](#2--store--a-single-json-file).
