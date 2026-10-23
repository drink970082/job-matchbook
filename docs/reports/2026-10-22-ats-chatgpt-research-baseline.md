# ATS + ChatGPT research workflow baseline

**Capture window began:** 2026-10-22 22:27 EDT (2026-10-23 02:27 UTC).

**Mode:** One interactive, read-only ATS MCP session plus public employer pages.
**Scope:** A small manual shortlist to exercise the current research path for issue #90.

This report records what the tools returned during this capture. It is not a source
freshness guarantee or an unattended-access test. No scheduled task, worker pass, model
evaluation, paid provider experiment, or ATS/database write was run. The local private
profile informed role triage, but its contents, résumé, application IDs/URLs/notes, and
full job descriptions are not reproduced here. Public employer listing links and short
summaries are included; no private application record is identified.

The capture began after the roadmap's 20:00 America/New_York evidence boundary. That is
the interactive read time only; I did not verify whether the worker pass starting at
20:00 had completed.

## Observed results

### ATS retrieval and application history

- `get_ats_overview` returned live table and workflow counts but no `as_of` timestamp or
  per-source last-success/check time. It reported 39 application rows and zero
  `status_history` rows at capture.
- `list_jobs` returned two 100-row pages filtered to `pipeline_status=new`. Both pages
  had `has_more=true`; I followed the first page's cursor for the second. The tool
  described its order as a “live keyset page; not a snapshot.” A separate query returned
  a `discarded` posting. These calls exercise pagination and status visibility, but they
  do not establish one frozen dataset or a source-wide cutoff.
- `list_applications` returned 25 rows and then 14 rows using the next cursor. Every
  row reported `linked_job_count=0`; `get_application` returned an empty
  `linked_job_ids` list for sampled records. `list_application_history` returned zero
  rows, consistent with the overview's empty `status_history` table. I did not retrieve
  application note bodies.
- One unlinked application and one current posting had the same normalized title and
  exact URL, while the posting's `application_id` remained null. That is a URL-identity
  match for this capture, not a stored ATS relation. I treated exact URL equality as
  confirmed URL-level identity for this run. Same-employer checks found no exact URL
  match for the two shortlist postings. Company/title similarity without a URL or
  requisition-ID match remained a probable duplicate and did not suppress a posting.
- The job list exposes a coarse screening state separately from fit score. The two
  shortlisted postings were still `new`, had no fit score, and had a complete screen
  result with `disqualified=false`. That means no hard screen disqualifier was stored;
  it is not a fit recommendation. A separate stored `provider_error` screen state was
  present on a posting whose job description remained available, so screen-provider
  failure must not be read as employer-source failure or job closure.

### Full descriptions and shortlist

I retrieved descriptions to completion by following each returned offset until the
server reported no next chunk. Chunk sizes below were requested through the read-only
`get_job_description` tool. Full text is omitted.

| Sample | Retrieval evidence | Decision from the full description |
|---|---|---|
| [Citadel — Quantitative Developer, Data Strategies Group](https://www.citadel.com/careers/details/quantitative-developer-data-strategies-group/) | 3,879 characters in 2 chunks; official page opened. ATS state `new`; screen complete, no disqualifier. | **Shortlist first.** The role builds Python tools, research workflows and alternative-data pipelines alongside investment and quantitative-research teams. This is the clearest match to the configured quant-engineering priorities. The official page lists a $200,000–$250,000 base range. It gives no sponsorship statement or years-of-experience threshold, so both remain unknown. |
| [Citadel Securities — Quantitative Developer/Research Engineer](https://www.citadelsecurities.com/careers/details/quantitative-developer-research-engineer/) | 2,239 characters in 2 chunks; official page opened. ATS state `new`; screen complete, no disqualifier. | **Shortlist second, with a scope question.** The role builds automated-trading software with quantitative researchers; Python is one of the listed languages, and New York is among the locations. The official page lists a $250,000–$350,000 base range and accepts a bachelor's, master's or PhD. Sponsorship and an experience threshold are unstated; the description does not settle how much of the work is low-latency systems engineering. |
| [Goldman Sachs — Software Engineer, Global Banking & Markets, Trading Technology](https://higher.gs.com/roles/182893) | 7,789 characters in 4 chunks; official page opened. ATS state `new`; screen complete, no disqualifier. | **Do not shortlist on the current profile.** The trading context is relevant, but the full description explicitly centers low-latency systems and requires 2+ years of professional Java experience. The listed location is Salt Lake City. The page gives no salary or sponsorship statement. The title alone would have overstated fit. |
| [Two Sigma — Software Engineer, Trading Engineering](https://careers.twosigma.com/careers/JobDetail/New-York-New-York-United-States-Software-Engineer-Trading-Engineering/13462) | ATS stores 533 characters, returned in 1 chunk. The public-page request failed with HTTP 406 Not Acceptable. | **Hold for source verification.** The stored text is a team/company introduction without role requirements or compensation. The 406 may be access protection; it does not prove the requisition is closed. Pay, sponsorship, level and detailed duties remain unknown. |

The shortlisted Citadel pages disclose base salary but no sponsorship/visa policy. The
Goldman Sachs page discloses neither in the retrieved text. Two Sigma could not be
verified through the public-page reader. “Not stated” means unknown, never “no.”

## Current tool gaps observed

- `list_jobs.search` matches title, company or location; it does not search full JD text.
  The list can filter coarse `screen_state`, but not the screen outcome or reason, and
  it has no filter for screening-update time. Items expose attempt/completion metadata,
  but inspecting the result requires separate `get_job` calls. Posting-created/posted
  date filters are not assessment-time filters.
- Pages are live keyset traversals rather than a shared snapshot. The overview has live
  counts but no response timestamp or source freshness watermark. Watched-company rows
  have no last-check/last-success field; unresolved-feed rows have per-row reasons and
  timestamps, not source-wide freshness. Per-row timestamps do not establish when a
  board was last checked or whether a listing is still open.
- Pay and sponsorship are not normalized ATS fields. They must be read from complete JD
  text or the official page, with absent statements recorded as unknown.
- Application records can be listed and histories queried, but the captured dataset had
  no application-to-posting links and no status-history rows. The tools do not expose a
  cross-table exact-URL/requisition-ID dedup operation. The local private preference
  profile is also outside the ATS MCP surface.
- This session exposed interactive read-only MCP calls only. No scheduled ChatGPT run
  was attempted, so this does not prove unattended tunnel access or delivery.

The public Two Sigma request returned 406, an observed page-retrieval failure. Separately,
the ATS contained a screen `provider_error` state while retaining a description. Those
are different failure domains; neither is evidence that the employer closed a job.

## Proposed follow-up for #91, #93 and #94

These are recommendations from the sample, not changes made by this report.

- **#91 research queries:** expose screen outcome/reason summaries, allow retrieval by
  assessment-update window, and add opt-in literal full-JD search. Keep pagination's
  live-state limitation explicit; callers need overlap/reconciliation rather than a
  false snapshot promise.
- **#93 source lifecycle:** expose per-source last-check/availability and distinguish
  blocked, stale, ambiguous and confirmed-closed evidence. Keep source freshness separate
  from screen completion and per-row `updated_at`.
- **#94 scheduled Brief:** verify an actual scheduled invocation through the deployed
  tunnel. Require official URLs, full-JD-grounded rationale, explicit unknown pay and
  sponsorship, a source/data cutoff, and a visible source-failure result. Compare
  application URL or requisition identity before calling a prior application confirmed;
  text similarity alone only raises a review flag. Keep cross-day recommendation
  deduplication best-effort until a separately approved ledger exists.

The existing #91 batch plan already covers research-oriented filters and search. This
baseline does not expand that approved implementation scope or substitute an interactive
run for #94's unattended acceptance.

## Reusable non-private workflow template

```text
Capture time and timezone:
Run mode: interactive / scheduled (name the actual task and invocation if scheduled)
Evidence cutoff: exact time of the retrieved data; source cutoff: known / unknown

ATS traversal
- Overview response time and relevant counts:
- Query filters and page size:
- Pages followed / has_more / cursor behavior:
- Traversal consistency: snapshot / live pages / unknown

Candidate [A]
- ATS lifecycle and screen state; keep screen separate from fit:
- Full description: total characters, chunks followed, complete / incomplete:
- Official URL and retrieval result:
- Role evidence for fit and disqualifiers:
- Base pay: stated / unknown; sponsorship: stated / unknown:
- Application history: linked requisition ID or exact URL match / probable text match / none:
- Decision: shortlist / hold / pass, with reason and confidence:

Source failures and unknowns
- Failed source and observed error (do not infer closure from a fetch error):
- Unknown pay, sponsorship, freshness or eligibility facts:
- Missing tool capability that prevented a decision:

Privacy and side effects
- Use aliases in the report; do not include profile/resume text, application IDs/URLs,
  note bodies, private JDs, credentials or database artifacts.
- Record whether any task was scheduled, model eval was run, or ATS/database write
  occurred. An interactive run never proves unattended access.
```
