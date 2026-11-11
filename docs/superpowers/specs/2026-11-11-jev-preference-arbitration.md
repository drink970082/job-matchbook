# Next convergence slice: separate duty classification from preference arbitration

**Status:** selected technical follow-up under the operator-authorized convergence plan;
implementation and exact next-batch manifest remain pending. No calls beyond the current
Stage 1 attempt limit are authorized by this document alone; cumulative USD 10 grant remains.
No production GO, automatic activation or new personal preference is established here.

## Current measured constraint

The local v2 development run has 30/30 fresh results, zero of the three implemented
first-target contradiction checks, and 96.7% modal / 93.3% pairwise agreement on preference,
skill support and work alignment. That is not full semantic consistency: secondary-family
work can still be labeled adjacent. A preference-only v3 wording probe has nine fresh
results; one generic software role still changes secondary/adjacent across repeats.
These are development observations, not independent accuracy or population recall.

Two wording iterations do not eliminate the classification/arbitration mismatch. More
wording churn is not the next experiment. Stable but unsupported critical-skill flags
also need separate source-evidence audit; do not infer that repeatability makes them right.

## Proposed next implementation boundary

Keep the seven independent role questions, engineering-primary and skill/work assessments.
Replace the free model preference-tier question with one duty-avoidance question using
frozen profile avoidances AND accepted-context clarifications. This preserves eleven
questions. Avoidance returns explicit present / absent / unclear and cannot infer a
candidate skill gap, seniority or employer prestige as an avoided duty.

A small pure arbitration function receives validated native answers plus an explicit,
versioned policy mapping first/secondary role IDs, supported/not-supported/unknown values,
engineering-primary and duty-avoidance values. No candidate's role priorities are hardcoded
into generic module source. Preserve every raw answer and distinguish the derived result.

Proposed decision table:

1. Explicit primary-duty avoidance -> avoided; unclear avoidance -> unresolved.
2. No avoidance and any supported first-target family -> primary.
3. No supported first target but a first-target family still unknown -> unresolved priority.
4. All first-target families ruled out and any supported secondary family -> secondary.
5. All declared targets ruled out and engineering-primary yes -> adjacent.
6. Missing/conflicting duties or unsupported branch -> unresolved; never manufacture a pass.

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
