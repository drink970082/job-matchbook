# Design: Bounded notify retry — a transient Telegram error must not bury a match

**Status:** approved (user fork decision, 2026-07-09 session), ready to implement.
**Date:** 2026-07-09.

## Problem / motivation

`run_notify` wraps the Telegram send in try/except → `db.mark_failed`, and `failed`
is terminal: nothing transitions a row out of it. So a *transient* send error (network
blip, Telegram 429/5xx) on a `scored ≥ threshold` posting marks it `failed` — it
vanishes from the default Discovered-Jobs view (`{scored, notified}`) and is never
re-notified. A prepared, high-scoring match is silently lost unless the user happens
to browse the Failed tab and manually reopens the row. This conflates a transient
notification failure with a genuine pipeline failure (PROGRESS → Defects; SPEC §9
"Failure handling and recovery limits").

The tailoring removal made the fix cheap: notify is now a **single atomic
`sendMessage`** — a failed send delivered nothing, so retrying it cannot double-send
a half-delivered alert.

## Goal

A transient notify failure self-heals (the match is re-notified on a later pass and
never leaves the default view); a *persistent* notify failure (revoked token, wrong
`chat_id`) still surfaces in a visible queue instead of retrying silently forever.

## Non-goals

- No in-pass retry/backoff machinery — the scheduler's pass cadence is the timer.
- No change to fetch/score failure handling (their exceptions still park the row
  `failed` immediately; a score failure means something is wrong with the row or the
  scorer, not the delivery channel).
- No new UI. The existing Failed tab becomes the needs-attention surface.
- No schema change (`attempts` and `pipeline_error` already exist).

## Decision (resolved with the user, 2026-07-09)

**Bounded pass-level retry via `attempts`, cap 3.** On a send error the row **stays
`scored`** — `attempts+1`, `pipeline_error` recorded — so the next scheduled pass
retries the send (`run_notify` re-selects `scored ≥ threshold`). The cap-th
(`NOTIFY_MAX_ATTEMPTS = 3`) cumulative failure parks the row `failed` (terminal,
visible in the Failed tab). A successful send clears `pipeline_error`.

Principles: **P3 err toward keep** (a blip can't bury a match; the row never leaves
the default view while retrying), **P5 fail loud into a visible queue** (the error is
on the row from the first failure; persistent breakage lands in the Failed bucket
after ~3 daily passes), **P6 per-item isolation** (unchanged), **P13 / YAGNI**
(reuses `attempts`, `pipeline_error`, the Failed tab, and the pass cadence; ~10-line
worker diff, no new dependency, no config knob).

Accepted caveat — **at-least-once delivery:** a timeout after Telegram already
delivered raises anyway, so the retry can duplicate one alert. One extra ping beats a
lost match (P3); the single-atomic-send property means nothing worse than a duplicate
is possible.

Semantics of `attempts`: a **cumulative failure counter** for the row. A row manually
reopened from `failed` (attempts already ≥ 3) gets exactly one fresh notify attempt
per reopen — its next failure parks it again immediately.

## Rejected alternatives

1. **Retry forever (always stay `scored`)** — PROGRESS's sketched cheap fix (~3
   lines). Rejected: a *permanent* channel failure (revoked token, wrong chat id — the
   classic Telegram-bot breakage) retries silently forever; alerts just stop arriving
   and nothing lands in any queue a human reviews — exactly P5's smell ("a failure
   path with no row … a human will ever see"), and `attempts` stays dead.
2. **Needs-attention view only (keep terminal-failed)** — web-only louder surface
   (badge/banner) over the existing behavior. Rejected: no self-healing — a blip still
   buries the match until a manual per-row reopen — and it keeps conflating transient
   send errors with genuine pipeline failures. Most new code of the three. The chosen
   design already turns the Failed tab into this view, with retry on top.
3. **Classify Telegram errors transient vs permanent (HTTP status)** — park 401/400
   immediately, retry 429/5xx/timeouts. Rejected: more code and a brittle taxonomy
   (Telegram 400s are not reliably permanent); the attempts cap handles both uniformly.
4. **In-pass immediate retry / backoff** — rejected: adds sleep/backoff machinery
   inside a batch, covers only seconds-long blips, and loses to multi-hour outages;
   the pass cadence retries for free.
5. **Config knob for the cap** — rejected (YAGNI): a constant that never changes per
   deploy; `NOTIFY_MAX_ATTEMPTS = 3` in `pipeline.py`.

## Change list

### Worker — `ats_worker/pipeline.py`

- `NOTIFY_MAX_ATTEMPTS = 3` module constant.
- `run_notify` except-branch: compute `attempt = row["attempts"] + 1`; call
  `db.record_notify_failure(conn, row["id"], error=str(exc), now=now,
  exhausted=attempt >= NOTIFY_MAX_ATTEMPTS)`; print a one-line
  `[notify] send failed (attempt i/3)…` log (retry vs parked), mirroring the feed's
  collapse-warning precedent.
- Module docstring + `run_notify` docstring updated (notify failure is no longer
  "marked failed, as before").

### Worker — `ats_worker/db.py`

- New `record_notify_failure(conn, posting_id, *, error, now, exhausted)`: one
  UPDATE — `pipeline_status = 'failed' if exhausted else 'scored'`,
  `pipeline_error = error`, `attempts = attempts+1`, `updated_at = now`. (`mark_failed`
  stays as-is for the fetch/score paths: always terminal.)
- `mark_notified` additionally sets `pipeline_error = NULL` (a recovered row doesn't
  carry a stale error).

### Schema comment (no structural change)

- `schema.prisma` `job_postings`: update the `attempts` / `pipeline_error` comments
  (auto-retry now exists at the notify stage; error is cleared on successful notify).
  The drift guard strips `//` comments, so the SQL fixture is untouched.

### Docs (same commit as the code)

- **SPEC §9:** state-machine block gains the notify-error transition; the "Notify
  failure buries a high-scoring match" defect clause is replaced by the new contract
  ("Notify send errors are retried, bounded"); traceability table row updated + a new
  row for the retry invariant. §7.1 (`db.py`, `pipeline.py` bullets) and §8 (quoted
  schema comments) and §11 (reliability caveat) updated to match.
- **PROGRESS:** the defect leaves Open work; phase paragraph no longer cites it.
- **CHANGELOG:** Unreleased → Fixed.

## Testing / verification

- `tests/test_pipeline.py`: send error → row stays `scored`, `attempts+1`,
  `pipeline_error` recorded, batch isolation preserved; three failing passes → row
  parks `failed` at attempts 3 (and was retried each pass); fail-then-succeed →
  `notified` with `pipeline_error` cleared.
- `tests/test_db.py`: `record_notify_failure` (keeps `scored` / parks `failed` on
  `exhausted`), `mark_notified` clears `pipeline_error`.
- `tests/integration/test_pipeline_e2e.py`: through the real `run_once` — one pass:
  failing row stays `scored` while its sibling notifies; three passes: failing row
  parks `failed` (attempts 3) and the succeeding sibling is alerted **exactly once**
  (no duplicate alert across passes).
- Gates: `make test-worker`, `make test-coverage` (floor 85), `make test-integration`,
  `make check-schema` (comment-only change). No web code touched → no web suite run.
- Runtime drive: `run_notify` over a throwaway SQLite with the **real**
  `notify_posting` against an invalid token (real HTTP → Telegram 401 → raise):
  observe scored/attempts=1 → parks `failed` on the third pass.
