# Roadmap — an elimination filter for job seekers

**Direction ([approved](superpowers/specs/2026-11-20-elimination-filter-positioning.md)):** every open job the candidate can actually get, none they
can't — for new graduates and international students. Job Matchbook owns collection,
elimination (with stated, rescuable reasons) and tracking; AI clients over MCP and the
human analyze and apply downstream. Priority follows the three promises: nothing stale,
nothing wrongly removed, nothing missed.

This file orders unfinished work. [ARCHITECTURE](ARCHITECTURE.md) defines boundaries;
[SPEC](SPEC.md) defines current behavior; [PROGRESS](PROGRESS.md) owns branch claims;
issues own scope and status.

## Feature readiness

| Feature | Current state | Direction |
|---|---|---|
| Board/feed discovery and JD hydration | Shipped | Core; improve coverage and evidence quality |
| Applications, history, CSV and watchlist UI | Shipped | Core; preserve data and manual workflows |
| MCP read tools, full-text chunks, write tools (applications, triage override, watchlist, preferences, JEV profile) and workflow prompts | Shipped (writes need `ATS_API_KEY`) | Core; the main channel under #152 |
| All-jobs inventory with advisory screening | Shipped | Preserve the safe inventory and application-action boundaries |
| Standalone Luna/medium screening | Shipped, operator-selected | Retain as low-cost assistance |
| JEV keep/skip filter | Deployed (`--jev`, #139) over the last 7 days of postings; `skip` hidden by default in MCP | Accepted; eliminates only (ranking is not a goal) |
| Loopback write API `/api/v1` | Shipped (#153) | Foundation for MCP writes |
| Source lifecycle for unscored rows | Bounded refresh supports SmartRecruiters only | Extend only with verified source-specific identity and closure signals |
| Daily Brief using ATS plus web | Interactive workflow works; unattended acceptance outstanding | Preferred judgment/delivery experience |

## Delivery order

| Order | Deliverable | Dependencies | State |
|---|---|---|---|
| 1 | [#229 Sources tell the truth](https://github.com/drink970082/job-matchbook/issues/229): #230 closure first, then #231-#233, #235 | None | Not started |
| 2 | [#223 One candidate profile; evaluate once](https://github.com/drink970082/job-matchbook/issues/223): #224-#227 | #157 (closed) | Spec approved; #224 next |
| 3 | [#240 Applications: links, status rule, audit](https://github.com/drink970082/job-matchbook/issues/240): #241-#244 | None | Not started |
| 4 | [#236 Sources are easy to extend](https://github.com/drink970082/job-matchbook/issues/236): #237-#239 | #231 for #239 | Not started |
| 5 | [#94 Scheduled Daily Brief](https://github.com/drink970082/job-matchbook/issues/94) | Deployed tunnel and account/workspace task access | Unattended acceptance outstanding; a downstream consumer, not the product's core |
| Parallel | [#181 Repo and docs cleanup](https://github.com/drink970082/job-matchbook/issues/181) | None | Only the onboarding discussion [#203](https://github.com/drink970082/job-matchbook/issues/203) is open |
| Parallel | [#182 Provider-neutral judgment](https://github.com/drink970082/job-matchbook/issues/182) | None | Per-stage providers shipped (#177-#179); [#180](https://github.com/drink970082/job-matchbook/issues/180) research open; `extract` keep/skip unmeasured |
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
