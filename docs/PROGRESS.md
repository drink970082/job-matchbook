# ATS — Progress Tracker

> Living status of the project. Pairs with [`SPEC.md`](./SPEC.md) (what the system
> *is*); this file is what's **done, in flight, and open**. Update it in the same
> change as the work it describes — see [How to update](#how-to-update) at the
> bottom.

**Current phase:** v0.2.0, **post-hardening checkpoint.** Both services are
feature-complete and stable; the last development push was entirely
testing / audit / CI hardening (coverage gates, integration + Playwright e2e,
schema-drift guard). The **documentation system** (SPEC + this tracker + auto-loaded
`CLAUDE.md`) is now in place; no application features are in flight.

Legend: ✅ done & stable · 🚧 in progress · ⛔ not started

---

## Feature status

### Web app (`apps/web`)

| Feature | Status | Notes |
|---------|:---:|-------|
| Applications table (paginated, filterable, searchable) | ✅ | filters: status, historical status, category, free-text |
| Inline status editing + status history | ✅ | each change appends a `status_history` row |
| KPI strip | ✅ | Applied / Active / Assessment / Interviewing / Rejected / Offer |
| Status history modal (add/edit/delete entries) | ✅ | delete recomputes current status |
| Activity heatmap | ✅ | 365-day GitHub-style, hand-rolled SVG |
| Category donut | ✅ | Recharts |
| Status funnel | ✅ | hand-rolled SVG, count + % |
| Status flow (Sankey) | ✅ | reconstructed from `status_history`, desaturated palette |
| CSV import / export | ✅ | hand-rolled RFC-4180 parser; enum validation; dedup |
| Discovered Jobs tab (scored queue + triage) | ✅ | default queue = scored/tailored/notified |
| JD + score-detail dialog | ✅ | matched/missing keywords, reasoning, screen verdicts |
| Tailored resume download | ✅ | `GET /api/resume/[id]`, path-traversal guarded |
| Mark Applied (promote posting → application) | ✅ | atomic transaction + back-link |
| Discard / Reopen posting | ✅ | reopen → `scored`, keeps disqualification reason |
| Responsive / mobile layout | ✅ | stacks below ~640px |

### Worker pipeline (`apps/worker`)

| Feature | Status | Notes |
|---------|:---:|-------|
| Fetch — Greenhouse / Lever / Ashby | ✅ | public board APIs |
| Fetch — Workday | ✅ | CXS list + per-job detail (N+1); slug = tenant/datacenter/site |
| Fetch — Pinpoint | ✅ | `{slug}.pinpointhq.com/postings.json` |
| Title pre-filter (fetch-time) | ✅ | optional, title-substring only |
| Score (local Ollama) | ✅ | `qwen3.5:4b`, JSON score + keywords + reasoning |
| Hard-constraint screening | ✅ | inside score; semantic; disqualified → `discarded` |
| Tailor (Claude + tectonic, one-page loop) | ✅ | `claude-sonnet-4-6`, ≤ `max_single_page_rounds` |
| Notify (Telegram message + PDF) | ✅ | degrades to message-only if PDF missing |
| Pipeline state machine | ✅ | new→scored/discarded→tailored→notified; failures isolated |
| Scheduler (APScheduler) | ✅ | immediate pass + every `schedule_hours`; `--once` for tests |
| Config load/validate (`config.yaml`) | ✅ | validates source, candidate block, thresholds |
| Auto-retry of `failed` postings | ⛔ | `attempts` is recorded on failure but no retry loop exists |

### Infrastructure & quality

| Area | Status | Notes |
|------|:---:|-------|
| Docker Compose (web + worker) | ✅ | shared db directory mount, UID/GID passthrough |
| Shared SQLite (WAL, cross-container) | ✅ | directory mount + busy_timeout |
| Web tests (Jest unit + integration) | ✅ | coverage-gated |
| Web e2e (Playwright) | ✅ | seeded throwaway DB; gated CI job |
| Worker tests (pytest, fully mocked) | ✅ | `fail_under = 85` |
| CI (GitHub Actions) | ✅ | both suites, coverage gates, schema-drift guard, gated e2e |
| Schema-drift guard | ✅ | `tools/check_schema_drift.mjs` |
| Documentation system (SPEC + PROGRESS + CLAUDE.md) | ✅ | committed 2026-06-16 |

---

## Known gaps / possible next steps

Lightweight and **uncommitted** — surfaced from the code and history, not a roadmap.

- **`failed` is a dead-end; transient notify failure buries tailored work.** Any
  stage exception marks a row `failed` and nothing transitions it back; `attempts` is
  recorded but never acted on. Worse, a transient Telegram error marks an
  *already-tailored* posting `failed`, hiding it from the default queue with no
  re-notify. Options: notify failure leaves the row at `tailored` (retried next pass);
  a "needs attention" view for `failed`; wire the auto-retry the `attempts` column
  anticipates. (SPEC §9.)
- **No output-level fabrication check.** "Never fabricates" is prompt-instructed
  (`FABRICATION_GUARD`) + human-verified only — no deterministic gate. A defensible
  check could warn on numbers / years / proper nouns present in the tailored resume
  but absent from `master.tex` (warn, not hard-block — "new fact" is fuzzy). (SPEC §9.)
- **Untested path-traversal guard.** The resume route's 403 guard
  (`api/resume/[id]/route.ts`) has no automated test. (SPEC §9 traceability.)
- **No schema migration path.** `prisma db push` keeps no migration history, so a
  destructive schema change can lose retained data — back up `db/applications.db`
  first. (SPEC §8.)
- **More board adapters.** The adapter pattern (`fetch/<source>.py` +
  `ADAPTERS` + `VALID_SOURCES`) makes new sources cheap; JobSpy was noted as a
  possible fallback aggregator.
- **Deployment / monitoring.** No health checks, metrics, or alerting beyond the
  per-job Telegram notification; failures are only visible in the DB / logs.
- **Batch / smarter tailoring.** Tailoring is per-posting and serial; no batching
  or caching of near-identical JDs.

---

## How to update

- When you finish a feature or change behavior, flip its row here **and** update the
  relevant section of [`SPEC.md`](./SPEC.md) in the same commit.
- Add a `CHANGELOG.md` entry for anything user-visible.
- Keep "Known gaps" honest: move items to the status tables once built; add new
  ones as you discover them. This section is observations, not promises.
