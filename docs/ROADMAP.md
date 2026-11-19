# Roadmap — AI-orchestrated job research

**Direction:** Job Matchbook supplies reliable job evidence, tracking and tools; the AI
assistant supplies judgment, supplemental search and recommendation delivery, and
(epic #152) orchestrates the system through MCP. The hard-requirements screen and the
JEV keep/skip filter are optional assistance.

This file orders unfinished work. [ARCHITECTURE](ARCHITECTURE.md) defines boundaries;
[SPEC](SPEC.md) defines current behavior; [PROGRESS](PROGRESS.md) owns branch claims;
issues own scope and status.

## Feature readiness

| Feature | Current state | Direction |
|---|---|---|
| Board/feed discovery and JD hydration | Shipped | Core; improve coverage and evidence quality |
| Applications, history, CSV and watchlist UI | Shipped | Core; preserve data and manual workflows |
| MCP read tools, full-text chunks, write tools (applications, triage override, watchlist, preferences) and workflow prompts | Shipped (writes need `ATS_API_KEY`) | Core; the main channel under #152 |
| All-jobs inventory with advisory screening | Shipped | Preserve the safe inventory and application-action boundaries |
| Standalone Luna/medium screening | Shipped, operator-selected | Retain as low-cost assistance |
| JEV keep/skip filter | Deployed (`--jev`, #139) over the last 7 days of postings; `skip` hidden by default in MCP | Acceptance open (#139); ranking stays gated under #135 |
| Loopback write API `/api/v1` | Shipped (#153) | Foundation for MCP writes |
| Source lifecycle for unscored rows | Bounded refresh supports SmartRecruiters only | Extend only with verified source-specific identity and closure signals |
| Daily Brief using ATS plus web | Interactive workflow works; unattended acceptance outstanding | Preferred judgment/delivery experience |

## Delivery order

| Order | Deliverable | Dependencies | State |
|---|---|---|---|
| 1 | [#152 AI-orchestrated ATS](https://github.com/drink970082/job-matchbook/issues/152): #157 preferences/profile in the DB | #153 (merged) | In flight |
| 2 | [#94 Scheduled Daily Brief](https://github.com/drink970082/job-matchbook/issues/94) | Deployed tunnel and account/workspace task access | Unattended acceptance outstanding |
| 3 | [#135 JEV ranking -> MCP](https://github.com/drink970082/job-matchbook/issues/135) | Keep/skip filter (#139) deployed | Ranking activation gated |
| Conditional | [#95 Delivery ledger](https://github.com/drink970082/job-matchbook/issues/95) | #94; observed repeats | Deferred |

## Daily Brief acceptance (#94)

Use the [Daily Brief task instructions](DAILY_BRIEF.md); interactive runs already cover
MCP pagination, complete JD chunks and application comparison, not unattended access.
The ChatGPT Scheduled task must be created in ChatGPT web or desktop, its connection must
discover the current `list_jobs` schema, and it must reach the private preference and
résumé files (web tasks use uploaded files or connected sources; desktop tasks a local
directory). Acceptance needs one observed unattended run with durable private preferences,
full JD reading, application-history deduplication without posting links, unknown
sponsorship/pay reporting and source-failure reporting. Company/title similarity is a
review signal, not verified requisition identity. At 20:00 America/New_York the brief
must disclose its evidence cutoff; the worker pass starting then is not guaranteed
complete. If scheduling is unavailable, record the blocker and the manual fallback; do
not silently introduce paid API orchestration.

## Pick rule

#95 may precede model work if repeated recommendations become the actual bottleneck.
Web-job import and agent-invoked refresh are unselected ideas. Writes need explicit
provenance, authorization and lifecycle contracts. Prefer source quality, retrieval and
verified user workflows; choose further inference only when observations justify it.
