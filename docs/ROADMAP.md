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
| MCP read tools, full-text chunks, write tools (applications, triage override, watchlist, preferences, JEV profile) and workflow prompts | Shipped (writes need `ATS_API_KEY`) | Core; becomes the downstream contract under [#256 MCP epic](https://github.com/drink970082/job-matchbook/issues/256) |
| All-jobs inventory with advisory screening | Shipped | Preserve the safe inventory and application-action boundaries |
| Standalone Luna/medium screening | Shipped, operator-selected | Retain as low-cost assistance |
| JEV keep/skip filter | Deployed (`--jev`, #139) over the last 7 days of postings; `skip` hidden by default in MCP | Accepted; eliminates only (ranking is not a goal) |
| Loopback write API `/api/v1` | Shipped (#153) | Foundation for MCP writes |
| Source lifecycle for unscored rows | Closure almost undetected (1 of 11,312 postings expired, 2026-11-20) | [#230 closure from board lists](https://github.com/drink970082/job-matchbook/issues/230) |
| Daily Brief using ATS plus web | Interactive workflow works; unattended acceptance outstanding | A downstream consumer, not the product's core |

## Delivery order

Ordered by the direction's three promises (nothing stale, nothing wrongly removed,
nothing missed), then the docker-first install, then the rest. Sizes are estimates.

| Phase | Order | Epic | Tickets, in order | Depends on | Size |
|---|---|---|---|---|---|
| 1. Truthful sources | 1 | [#229 Sources tell the truth](https://github.com/drink970082/job-matchbook/issues/229) | #230 closure first; #231 board health + verify-on-add; #232, #233, #235 | None | ~5 d |
| | 2 | [#246 Pass record and intake funnel](https://github.com/drink970082/job-matchbook/issues/246) | #247 (write it in the same pass work as #231); #249; #248 after #225 | #231 for shared pass code | ~2 d |
| 2. One profile, safe removal | 3 | [#223 One candidate profile; evaluate once](https://github.com/drink970082/job-matchbook/issues/223) | #224 -> #225 -> #226; #227 after #224 | None (spec approved) | ~6.5 d |
| 3. Docker-first | 4 | [#251 Runtime settings in the web](https://github.com/drink970082/job-matchbook/issues/251) | #252 -> #253, #254, #255 | None | ~4.5 d |
| | 5 | [#256 MCP as the downstream contract](https://github.com/drink970082/job-matchbook/issues/256) | #209 decided (option A) -> hosted tunnel check -> #257; #258 after #226 | #225, #226 | ~4.5 d |
| 4. Tracking and breadth | 6 | [#240 Applications](https://github.com/drink970082/job-matchbook/issues/240) | #242, #243 (independent); #241 -> #244 | None | ~3 d |
| | 7 | [#236 Sources are easy to extend](https://github.com/drink970082/job-matchbook/issues/236) | #237, #238; #239 after #238 and #231 | #231 | ~2.5 d |
| 5. Downstream consumers | 8 | [#94 Scheduled Daily Brief](https://github.com/drink970082/job-matchbook/issues/94) | One observed unattended run | Tunnel; #256 shape | - |
| | Conditional | [#95 Delivery ledger](https://github.com/drink970082/job-matchbook/issues/95) | - | #94; observed repeats | - |

**Research and discussion (no build until decided):**

| Issue | Question | State |
|---|---|---|
| [#209 MCP read path](https://github.com/drink970082/job-matchbook/issues/209) | Can the tunnel front an HTTP MCP server? Then option A or B | [Note](superpowers/specs/2026-11-20-mcp-read-path-research.md): HTTP yes, recommends A; gates #257 |
| [#180 Screen as JEV packs](https://github.com/drink970082/job-matchbook/issues/180) (under [#182 provider-neutral epic](https://github.com/drink970082/job-matchbook/issues/182)) | Can typed question packs match the screen's zero-false-disqualification bar? | Needs operator authorization for paid runs |
| [#222 One criteria model](https://github.com/drink970082/job-matchbook/issues/222) | Is an extension point for new criteria worth a registry? | After #223 |
| [#203 Cold-start onboarding](https://github.com/drink970082/job-matchbook/issues/203) | Taxonomy from the first fetch; which cold-start option | Q1 and Q4 answered (2026-11-20 comment) |

Total build work in phases 1-4 is roughly 28 working days.

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

Take the lowest phase with unblocked work. Within a phase, a ticket whose dependency is
unmet waits; take the next. #95 stays conditional on observed repeats. Web-job import,
agent-invoked refresh and a remaining-set export for non-MCP consumers (for example
Meta's Muse agent) are unselected ideas until a concrete consumer is named. Writes need explicit
provenance, authorization and lifecycle contracts. Prefer source quality, retrieval and
verified user workflows; choose further inference only when observations justify it.
