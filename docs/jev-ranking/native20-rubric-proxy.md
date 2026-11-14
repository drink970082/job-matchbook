# Native20 P0 rubric model proxy

A second independent model proxy applies the exact four P0 dimensions to all 20 full stored JDs and the approved profile, with preference based on primary duties. Eligibility caveats are private, separate, and do not determine priority. Genuine duty/domain uncertainty receives review without a target review count. Deterministic projection and sorted independent review reasons follow `ranking-projection-v1`.

The private artifact was frozen with exclusive creation (no overwrite) and read-only mode `0400`.

- Artifact SHA-256: `6ac37f58e152dd2e5e614b6f56c4cd23e9aefa00eb7b910c0d601a9d2504cec7`
- Guide version: `p0-four-dimension-duty-preference-proxy-v1`
- Guide SHA-256: `615dea72fe495276adbfad1902a09c410a845e8b14c9c2d47695e8cc6564b84f`
- Source-file SHA-256: `996f198e4e799a75a648ae25ab3fe261f84bfea03170bf28c3978846e4074327`
- Full profile-binding-file SHA-256: `bb33a4996dc1a388d6198d479d9bd2649ca6042cfab114ae6be361c56cb74986`
- Domain-manifest-file SHA-256: `c9121de6985ab6ddf12bb15e1ce1f292a153370015f648fcbcdd0269a956d50c`
- Question-pack-file SHA-256: `b88dac97b717b6b9cb93ff7cc4df2bbae23d9e7dcb02bcbf327d23c40d8517e7`
- Pinned P0 contract-content SHA-256 (`1308f47`): `c9c1955c4308972d65be3ddb79d3d27a9930e868808650e65b737fd08e9a1b26`

Aggregate counts only:

```json
{
  "ambiguity": {
    "clear": 16,
    "review": 4
  },
  "domain": {
    "agentic_llm_applications": 1,
    "analysis_decision_support": 7,
    "general_software_engineering": 6,
    "mixed": 2,
    "ml_engineering": 3,
    "unknown": 1
  },
  "needs_review": {
    "false": 16,
    "true": 4
  },
  "preference": {
    "plausible": 4,
    "strong": 5,
    "unknown": 1,
    "weak": 10
  },
  "priority": {
    "null": 1,
    "high": 4,
    "low": 10,
    "medium": 5
  },
  "relevance": {
    "partial": 8,
    "supported": 12
  },
  "review_reasons": {
    "domain_mixed": 2,
    "domain_unknown": 1,
    "duties_or_signals_unclear": 4,
    "preference_unknown": 1
  },
  "rows": 20
}
```

This is a model-generated reference, not human truth or calibrated accuracy. Outcome blinding does not remove same-family correlated-error risk. It is bounded to the already exposed 20-row development subset, never held-out or GO evidence. No native outputs, previous proxy, comparison report, old scores or screening labels were opened. No paid HTTP calls or production database writes were made. No agreement or accuracy claim is made here.
