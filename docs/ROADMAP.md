# Roadmap — ChatGPT-first job research

**Direction:** Job Matchbook supplies reliable job evidence, tracking and tools;
ChatGPT supplies primary judgment, supplemental search and recommendation delivery.
**Screening and the scorer remain supported optional assistance.** This is not a plan
to delete them or require every posting to receive a fit score.

This file orders future work. It does not claim the features below are shipped or
change CLI defaults. [ARCHITECTURE](ARCHITECTURE.md) defines boundaries;
[SPEC](SPEC.md) defines current behavior; [PROGRESS](PROGRESS.md) owns branch claims.

## Feature ownership and readiness

| Feature | Current state | Direction |
|---|---|---|
| Board/feed discovery and JD hydration | Shipped | Core; improve coverage and evidence quality |
| Applications, history, CSV and watchlist UI | Shipped | Core; preserve data and manual workflows |
| Read-only MCP and full-text chunks | Shipped | Core; improve research-oriented queries |
| Standalone Luna/medium screening | Shipped, operator-selected | Retain as low-cost assistance |
| Fit scorer and Telegram notifications | Shipped; bypassed by operator's screen-only mode | Retain opt-in compatibility; no automatic retirement |
| Browsing unscored jobs in the UI | Fit buckets limit visibility | Priority feature |
| JD refresh and liveness for unscored rows | Incomplete | Priority data-quality work |
| Daily Brief using ATS plus web | User workflow, unattended acceptance outstanding | Preferred judgment/delivery experience |
| Saved recommendation history and web-job imports through MCP | No write tools | Deferred, separately designed |
| JEV/System One assistance | Not implemented in ATS | Optional experiment, after a measured need |

## R1 — Research queries and visible job inventory

Build a small, read-only slice first:

- Add explicit screen verdict summaries/filters, including unknown, without treating
  `complete` or `disqualified=false` as universal qualification.
- Support incremental completed/changed assessment queries with defined timestamps,
  stable pagination and overlapping windows; do not select solely by job creation date.
- Expose eligible screen backlog, pass/disqualification/error counts and data cutoff.
- Let the web UI browse unscored jobs and inspect standalone results independently
  of the Matched fit view. Preserve application actions and existing result access.
- Improve title/company/location/JD search without requiring an external search service.

**Acceptance:** an older posting completed today can be found; pages neither repeat nor
skip rows under the declared traversal contract; provider errors remain visible; a new
unscored posting is reachable in UI and MCP; 39 or any other live application count is
never hard-coded into tests. Use isolated fixtures for state and pagination boundaries.

## R2 — Source quality and collection policy

- Separate documented collection scope from personal eligibility/ranking preferences.
  Inventory fetch/title/location gates before changing any of them. Retain reviewable
  exclusions or queryable tags where policy requires them; do not silently broaden intake.
- Define and implement content refresh, last-seen and closure semantics independent of
  fit state. Reuse existing adapters and verified source signals.
- Retain full JD/provenance and identify thin, missing, unknown and fallback-date data.
- Define age retention independently from closure; preserve applications and associated
  evidence. Past one-off cleanup is not an automatic retention policy.

**Acceptance:** an unscored job is rechecked; a changed JD is distinguishable from its
previous assessment input; timeout/blocked/ambiguous pages do not become definite closure;
application/history rows and protected associations survive lifecycle maintenance.

## R3 — ChatGPT workflow acceptance

- Prepare user-controlled background/preferences and a durable Daily Brief instruction set.
- Use ATS candidates plus supplemental web search; fetch full JD before final judgment.
- Compare applications even when `application_id`/`linked_job_count` is empty. Use source
  requisition identity and normalized official URLs; company/title similarity is a review
  signal, not permission to merge distinct requisitions.
- Run an unattended task through the ATS tunnel, including multiple list pages, JD chunks,
  source failure and empty-result cases. At 20:00 America/New_York disclose the data cutoff.
- State honestly that cross-day recommendation deduplication is best-effort until a
  persistent delivery ledger exists; task context is not that ledger.

**Acceptance:** each actual recommendation has an official URL and evidence-based
eligibility/fit reasoning, excludes verified prior applications, identifies unknown
sponsorship/pay facts, and reports unavailable sources without claiming an empty market.
No fixed ATS/web quotas or requirement to analyze every stored JD.

## R4 — Optional scorer maintenance

Keep the existing screen and fit adapters, result contracts, tests and manual eval tools.
Do not make a full fit-corpus rebuild a prerequisite for R1–R3. Preserve isolation from
fetch-only/screen-only and from primary ChatGPT recommendations.

A request to change the fit model/rubric, make Luna/medium the fit backend, or let a
classification hide jobs gets a scoped design and representative evaluation. Existing
screen results do not validate Luna fit ranking. See [EVALUATION](EVALUATION.md).
Retire redundant documentation and obsolete universal eval obligations, not useful
coverage or the scorer itself. No new automatic Telegram rollout is part of this roadmap.

## Deferred extensions

- Durable brief delivery/assessment history and narrow write tools.
- Web-discovered job import, official-page refresh and fetch tooling for agents.
- Standard `search`/`fetch` compatibility for research clients that require that schema.
- JEV/System One fact classification or review prioritization, shadow-tested before gating.
- Additional model/provider coverage only for a demonstrated operator need.

These are candidates, not approved schemas, dependencies, budget allocations or scheduled
paid runs. Select one bounded feature and design its failure/authorization contract first.

## Pick rule

Prioritize discoverability, freshness, retrieval and successful user workflows. Spend
model allowance where it improves decisions, with an explicit model/effort/workload.
Do not cut useful discovery merely to drain an old fit backlog, and do not rerun old
Sol/Terra/caching experiments without a new question the existing evidence cannot answer.
