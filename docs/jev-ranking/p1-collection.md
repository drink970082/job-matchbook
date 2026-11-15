# P1 optional roster snapshot utility

**Status:** inactive. All independent JEV snapshot timers are disabled. Normal ATS
worker fetch + standalone screening supplies ongoing intake; this utility is not a
prerequisite for existing-inventory development or later fresh-data evaluation.

## Utility and retained scope

`apps/worker/tools/jev_collect_roster.py` can capture one bounded observation through
injected fixtures or explicitly selected native APIs. It retains raw payloads, parsed
identities, source/description hashes, exclusion reasons and per-board success/failure.
It makes no model calls or production DB writes. `scope_capture_complete` means every
selected board returned a structurally matching response; `daily_window_complete` is
always false. Point snapshots cannot establish all-day coverage or full JD completeness.

The private frozen scope selects120boards:101Greenhouse,12Ashby,7Lever. Other52boards
and discovery feeds are excluded. Scope SHA256:
`19ada5f2db1b99efb7e6d1256b0fe465b1a14660c2653432979f51230d1c674f`.
The repaired archive `0b84b5b` validates all120safe slugs and passes an offline full-scope
fixture. Its immutable manifest SHA256:
`96b0f227a7a47bec7b0095e97ac03c71201d977c24852a0b272f0540b0b6d745`.
Archives and the pre-HTTP failed receipt remain private and ignored. No observations
are claimed to exist. Do not enable another collection campaign as an evaluation gate.

## Active operating path

The normal `ats-worker.service` is enabled and active, using the existing runtime
checkout and `--screen-only --screen-backend codex --screen-model gpt-5.6-luna
--screen-effort medium --screen-unlimited --screen-workers 1`. It fetches and screens at the
existing daily00:00America/New_York schedule, without fit scoring. User lingering
allows operation after logout; the host must remain awake and online.

Existing completed screen evidence may be used now for exposed development. Select the
same post-screen inventory for both publication and JEV ordering; report lifecycle,
unknown/provider-error and source-relative freshness separately. Cached screen evidence
is advisory and does not prove current profile binding. No candidate facts or screen
outcomes are overwritten for research. See the
[consumer comparison protocol](p1-prospective-consumer-protocol.md).
