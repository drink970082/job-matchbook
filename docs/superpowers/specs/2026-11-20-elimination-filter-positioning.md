# Product direction: an elimination filter, not a recommender

**Status:** approved product direction (operator, 2026-11-20). Implementation slices need
their own scoped designs. This document governs future work.

## Decision

Job Matchbook gives a job seeker **every open job they can actually get, and none they
can't**.

- It collects postings from company-owned sources.
- It removes the ones the candidate is provably ineligible for, or has explicitly
  excluded.
- It says why each one was removed, and lets the human rescue any of them.
- It does not rank the rest by "fit". Remaining postings are ordered newest first.

The promise is about **recall with safe elimination**, not about precision at the top of
a list. Match scores are not a product goal. In this repo, fit scores were measured as
rubric-band noise, and ranking within `keep` tied publication-time order (SCORING.md,
SPEC section 7.1).

**Audience:** new graduates and international students. These are high-volume applicants
for whom hard requirements decide most outcomes: work authorization and sponsorship,
degree, clearance, required years of experience. Career switchers are a secondary fit.

## What the system owns, and what it hands off

| Layer | Owner | Output |
|---|---|---|
| Collection | Job Matchbook | Postings from company boards and recipes, plus feeds resolved back to boards; full JD; source state (open / closed) |
| Elimination | Job Matchbook | Per posting: kept or removed, with the requirement or exclusion that removed it (requirements stage, triage stage, operator override) |
| Tracking | Job Matchbook | Applications and status history, linked to postings when one exists |
| Analysis, prioritization, writing | Downstream: the human, or an AI client (Claude, ChatGPT) over MCP | Whatever the user wants from the remaining set |
| Applying | The human, or a tool the human runs and triggers | Job Matchbook never submits an application (PRINCIPLES 1) |

The remaining set is a contract for downstream consumers. MCP is the interface for AI
clients today. A non-MCP consumer (for example, a user's own apply tool) needs an export
of the remaining open set, and that export is not built yet.

The worker's judgment stages exist to **eliminate**. The triage preference question
removes only roles the profile explicitly excludes (`weak`). It is not a suitability
score.

## The three promises, and where each stands

| Promise | Meaning | Gap today |
|---|---|---|
| Nothing missed | Every eligible posting from the user's sources and feeds is collected | Breadth depends on a curated watchlist and one feed; adding recipe boards needs a local checkout (#236, #203) |
| Nothing wrongly removed | Every removal has a stated reason, is visible, and can be rescued | Measured (screen: zero false disqualification; triage: 0 of 7 real applications skipped), but reasons and rescue are not first-class in the UI (#226, #227) |
| Nothing stale | What is shown is still open | Closure is almost undetected (#230) |

The **intake funnel** is the product's main view: fetched -> removed by reason -> open
and eligible. It is #227's intake summary, promoted from onboarding to the dashboard.

## Principles

- **1 (human owns the trigger):** downstream tools may apply on the human's instruction.
  Job Matchbook itself never does.
- **2 (deterministic for facts):** elimination rests on extracted facts decided by code,
  wherever a rule can be written.
- **3 (err toward keep):** the product's core risk is a wrong removal, because a lost job
  is invisible. Removals must be visible and rescuable. Missing facts keep a posting.
- **4 (cheap assistance):** no posting must buy a paid judgment to be visible.
- **5 (fail loud):** a broken source or an aged-out posting is counted on screen.

## Rejected alternatives

- **Recommender (ranked "best matches").** Rejected: measured noise and ties with
  chronology, and it promises something nobody delivers reliably.
- **Mass-apply tool (auto-submit).** Rejected: it breaks PRINCIPLES 1, the space is
  served by Jobright-style agents, and volume without eligibility filtering is the
  problem this product solves.
- **AI-client-first (ChatGPT owns judgment and recommendations).** Superseded. The AI
  client remains a first-class consumer over MCP, but the product's own value, the open
  and eligible set, must stand without one.

## Consequences

- #135 (JEV ranking -> MCP) is closed. `preselection/` stays as offline evaluation
  tooling.
- Priority goes to the three promises: #230 (stale), #226 / #227 (wrong removal,
  visibility), #223 (one profile), then breadth (#236, #203).
- Evaluation priority follows the audience: work-authorization and sponsorship removal
  accuracy first.
- A remaining-set export for non-MCP consumers is a candidate deliverable once a concrete
  consumer is named.
