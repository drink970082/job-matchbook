# P1 bounded roster snapshot collector

**Status:** implementation prepared and tested with fake responses; live activation pending.
This is a proposed limited daily-snapshot study, not complete all-day intake coverage.

## Explicit scope

The read-only watchlist export contains 172 boards. The candidate selects the 120 boards
whose existing native APIs supply one complete list response: Greenhouse 101, Ashby 12,
Lever 7. The other 52 watchlist boards and all discovery feeds are excluded explicitly.
No browser/custom adapter or detail hydration is invoked. Existing global title/age and
candidate location/internship gates are copied into the private scope; no filter changes.

Private candidate: `apps/worker/resume/pivot/jev-ranking-p1-v1/scope-candidate.json` in the
operator's original checkout, mode 0600, ignored by git. Canonical UTF-8 compact sorted
JSON SHA-256: `19ada5f2db1b99efb7e6d1256b0fe465b1a14660c2653432979f51230d1c674f`.
The scope and candidate settings must remain frozen across observations.

Each output retains the exact decoded native JSON payload, raw identities, parsed full
posting values/hashes, deterministic filter reasons, missing-body records, duplicate
identity links and per-board success/failure/unsupported receipts. Raw/parsed IDs reconcile
for captured boards. A returned body is not proof the source supplied a complete JD.
Cross-day requisition/template grouping remains P1 preparation work.

`scope_capture_complete` means every selected board returned a structurally valid matching
list. `daily_window_complete` is always false: a point observation cannot observe jobs
that appeared and disappeared between observations. No result claims full original P1
held-out completeness. The operator must accept this 120-board snapshot study scope before
activation; a failed board makes that observation incomplete and is not silently replaced.

## Concrete activation candidate

Proposed dates are 2026-11-14, 2026-11-15 and 2026-11-16 at 12:00 UTC
(07:00 America/New_York), with each enclosing UTC day declared in the manifest.
If activation occurs after the first cutoff, choose three later distinct dates before
starting rather than manufacture a missed observation. Each run permits at most 120
requests, 1,800 seconds of cooperative network elapsed time, 134,217,728 total response
bytes and 268,435,456 serialized output bytes. Blocking reads can overrun the cooperative
time cap by the configured read timeout (at most 20 seconds); this is not a process-kill
deadline. There are no retries, redirects, model requests, production DB writes or schedule
changes. Three runs permit at most 360 public-board requests. No run is activated here.

Create the private output directory with mode 0700. For each accepted day substitute its
UTC start/end and a unique private output filename:

```sh
python3 apps/worker/tools/jev_collect_roster.py \
  --scope /home/halcyon/root/ats/apps/worker/resume/pivot/jev-ranking-p1-v1/scope-candidate.json \
  --output /PRIVATE/observations/YYYY-MM-DD.json \
  --window-start YYYY-MM-DDT00:00:00Z \
  --window-end NEXT-DAYT00:00:00Z \
  --live --max-requests 120 --max-seconds 1800 \
  --max-response-bytes 134217728 --max-output-bytes 268435456
```

Output is reserved exclusively with mode 0600 before network dispatch. Existing or
unwritable output paths fail before any request. Interrupted/failed writes are not a
sealed valid JSON observation and must be reconciled before rerunning; the collector
never overwrites a previous path. A zero CLI exit means selected-scope capture succeeded,
not daily coverage or ranking quality. Exit 2 reports incomplete capture.

## Executed fake demonstration

A synthetic Greenhouse board with one posting was captured using `--fixture`, `--now`
and a declared UTC window. Actual summary: expected/captured boards 1/1, raw/parsed rows
1/1, retained 1, excluded 0, model_calls 0, database_writes 0,
scope_capture_complete true, daily_window_complete false. Reusing the output path fails.

Targeted tests cover native identity reconciliation, title/age/location/internship and
missing-body reasons, duplicate identity, malformed payload retention, unsupported/error
boards, timestamps/slug validation, fixture CLI and no-clobber-before-live behavior.
No live endpoint or production service was exercised.
