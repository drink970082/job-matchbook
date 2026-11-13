# Next convergence slice: separate duty classification from preference arbitration

**Status:** implemented on branch; approved for bounded small-sample execution under the
operator's instruction to continue the selected structural correction. The existing USD 10
campaign grant remains; production GO/merge/deployment are not authorized. This slice
extends the retained Stage 1 cap from 40 to 100 through an append-only scoped amendment,
keeping the USD 0.50 stage ceiling, historical charges and global USD 10/5,000 limits.
The next batch is the existing ten development jobs × three fresh draws, at most 40 new
attempts, one in flight and a 15-minute batch deadline; no automatic retries or new sources.
Exact v4 question/profile/policy/batch hashes are frozen before dispatch.

## Current measured constraint

The v5 ten-job/three-draw development sample has full derived-preference repeat agreement.
Skills and work alignment each have 96.7% modal and 93.3% pairwise agreement. Raw duty
classification remains fallible, and skill flags still need exact required/preferred and
background evidence. No independent quality or complete-pool recall is established.

The retained Stage 1 ledger has 99 new attempts against the amended 100 cap and cumulative
USD 0.023251914 across 109 attempts including earlier mechanics calls. No pending or unknown
charge remains. Further workload requires a reviewed append-only stage transition; the
existing single amendment must not be bypassed by a new ledger or modified anchor.

## Selected implementation boundary

Keep the seven independent role questions, engineering-primary and skill/work assessments.
Replace the free model preference-tier question with one duty-avoidance question using
frozen profile avoidances AND accepted-context clarifications. This preserves eleven
questions. Avoidance returns explicit present / absent / unclear and cannot infer a
candidate skill gap, seniority or employer prestige as an avoided duty.

A small pure arbitration function receives validated native answers plus an explicit,
versioned policy mapping first/secondary role IDs, supported/not-supported/unknown values,
engineering-primary and duty-avoidance values. No candidate's role priorities are hardcoded
into generic module source. Preserve every raw answer and distinguish the derived result.

Decision table:

1. Explicit primary-duty avoidance -> avoided; unclear avoidance -> unresolved.
2. No avoidance but engineering-primary no/unknown -> unresolved (including conflict
   with a supported engineering role); do not derive a positive preference from it.
3. No avoidance, engineering-primary yes and any supported first-target family -> primary.
4. No supported first target but a first-target family still unknown -> unresolved priority.
5. All first-target families ruled out and any supported secondary family -> secondary.
6. All declared targets ruled out and engineering-primary yes -> adjacent.
7. Missing/conflicting duties or unsupported branch -> unresolved; never manufacture a pass.

The function cannot guarantee that model role/avoidance facts are correct. Report raw
model errors and derived-policy consistency separately. Do not create a 0–100 score,
new weights, hard eligibility filter, legacy import or database mutation. Unknown/low-fit
postings stay visible in inventory. Skill support and hard constraints remain independent.

## Required next evidence

- Synthetic pure rule truth table, including overlapping roles, unknown first target,
  primary-duty avoidance overriding target match and accepted-context clarifications.
- Same blocked legacy imports/resources execution check; no old Registry/prompt/corpus.
- Extend global campaign accounting through an append-only, explicitly scoped stage/batch
  amendment before further calls. Do not edit original campaign config, reset the ledger,
  treat historical costs as zero or reuse the remaining one attempt for a new campaign.
- Audit unsupported critical-requirement flags against exact required/preferred JD spans
  and approved background evidence. A missing explanation is not evidence of a real gap.
- Freeze the revised eleven-question pack and small diagnostic workload, then compare
  held-fixed job evidence against prior development versions. This cannot become a
  held-out PASS or quality GO. Keep source/model/profile identities and cost accounting.

Implementation owner remains Luna/max; orchestrator owns policy/data/acceptance. The exact
handoff and batch caps must be recorded before dispatch; there is no need to ask the
operator to repeat the three already accepted work-context preferences.

## Bounded implementation handoff

Implement pure versioned `preselection/preference.py`; policies supply first/secondary
role IDs and all value mappings and validate them against frozen questions. Derive tiers
from an otherwise validated native wrapper, expected resolved model and exact question
set; reject malformed evidence rather than manufacturing an unresolved success. Return a
separate decision with tier, reason, policy hash and relied-on question IDs. Never mutate
the raw wrapper or use hidden candidate-specific defaults.

Extend `CampaignLedger` with an append-only attempt-cap amendment and compare-and-swap
against the current event hash. Preserve the original anchor/configuration and all settled
spend and counters. Only increase the effective stage attempt cap, bounded by the frozen
global remaining attempt allowance; require a recorded authorization SHA-256. Refuse
amendments with pending, unknown or over-reserve exposure. Replay validates the event,
previous cap, strict increase and authorization/hash shape. A stale CAS cannot silently
append a second amendment. Snapshot exposes effective cap and last event hash. No amount,
historical-spend or global-budget change belongs in this API.

Luna/max owns source/tests; orchestrator owns docs, private manifests and actual execution.
Run the full worker suite/coverage >=85%, targeted truth-table/amendment tests, actual
blocked-legacy entrypoint execution, schema/privacy/diff checks. No web change is planned.
This slice adds no score bands or runtime integration. The following batches may not reset
or silently extend caps merely because USD 10 remains.
