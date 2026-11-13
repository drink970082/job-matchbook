# P0 resource evidence and proposed bound

**Status:** offline audit; initial local research bound accepted provisionally; P1 inventory measurement pending.
Planning source: `ef18116c20b01cc7df7e7a9a8c7594b5a76f3900`; audited research:
`16deac2fd152b57d1648c81dd201f8760315b25d`.

## Local bound origin

Research `apps/worker/ats_worker/preselection/openrouter_jev.py` accepts configurable
`max_request_bytes=20_000`. `complete()` serializes the entire model/state/questions
request with `ensure_ascii=False`, sorted keys, compact separators and `allow_nan=False`,
then UTF-8 encodes it. Its length check precedes HTTP: excess raises
`jev_request_too_large`, `delivery=not_sent`. The research campaign overrides this to
24,000 bytes; its comparator chat path independently uses 24,000. These are decimal
bytes, not KiB, tokenizer counts or provider rejection evidence.

## Reproduced historical distribution

Read-only inspection followed the published report's retained directory name through the
local freeze controller at `/tmp/ats-jev-openrouter-review/freeze_jev_skill_evidence20.py`.
The approved private preparation is beneath the worker's ignored resume/pivot pilot tree;
no profile/JD text is reproduced here. `job-packs.pre-wire.json` SHA-256 is
`6ae45866ea870edb3140e12393a6028a9aa3c4c13c178938b8ad59d3a26d2c61`.
All 21 retained complete `request.pre-wire.json` bodies were parsed, and actual byte
length and SHA-256 matched their manifest entries. No retained file was modified.

| Cohort | n | Min | Median | P90 | P95 | Max | >24,000 | >32,768 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Controls | 2 | 14,240 | 16,082 | 17,924 | 17,924 | 17,924 | 0 | 0 |
| Main with question packs | 19 | 13,053 | 20,745 | 25,237 | 29,092 | 29,092 | 3 | 0 |

Quantiles use nearest rank, median uses the arithmetic middle for even counts. The
requested main roster is 20: one source has no selected technical requirements and no
request; three of the 19 bodies exceed the campaign ceiling. The remaining 16 main
bodies have maximum 22,513 bytes. Four selection-skip records comprise those three
size exclusions and the no-question source. This reproduces the report's size finding;
it is **selected-skill historical evidence**, not the distribution for the new minimal
ranking question pack, daily population or a fresh held-out pool.

## Current official evidence

Documentation inspected 2026-11-13, without authenticated inference:

- [OpenRouter Jev 1.13](https://openrouter.ai/typesafe/jev-1.13) advertises 262,144-token
  context and $0.042/M input tokens, $0/M output tokens. A context advertisement does
  not establish an HTTP byte ceiling, actual per-question accounting or route behavior.
- [TypeSafe models](https://docs.typesafe.ai/models) documents default 64k tokens per
  request and 32k per question (state plus that question), with optional 262k contexts
  using `TypeSafe-Danger-Zone-Long-Context: true`. Long context is documented as slower
  and less accurate. This direct-provider behavior cannot silently be assumed to be
  OpenRouter's behavior; the differing context claims need route-specific verification.
- [TypeSafe request rules](https://docs.typesafe.ai/api/errors) documents 32 MiB bodies,
  UTF-8 JSON, at most 64 nested levels and finite numbers. The body bound also applies
  after decompression. That is evidence for TypeSafe's endpoint, not proof of an
  identical OpenRouter ingress limit.

Exact account rate limits, OpenRouter ingress byte ceiling, route/header handling,
canonical resolved identity, tokenizer availability and billed input accounting remain
unverified. No fixed account RPS/TPS or new cost claim is inferred. Historical report
metadata and charges remain historical observations, not newly queried facts.

## Accepted provisional configurable policy

Use **32,768 serialized request bytes**, provisionally accepted by the operator, as the initial local safety ceiling for the
minimal study: it accommodates all measured retained complete bodies, adds 3,676 bytes
above their maximum, and avoids treating a multi-megabyte provider body limit as a
sensible operating budget. It does not establish that any request fits a token context
or that the provider will accept it. Keep an independent configured token/cost reserve,
response-byte bound, HTTP deadline and campaign attempt/money/time caps; do not infer
exact tokens from bytes or characters. No long-context header, truncation or splitting
is enabled by this proposal.

## Accepted minimal request distribution

After operator acceptance of the eight-domain vocabulary, the offline measurement used
all 22 retained source rows, the unchanged approved full profile and the exact four-question
contract. Complete request serialization includes requested model, state, canonical full
profile/domain candidate context and all native question criteria/instructions.

| Cohort | n | Min | Median | P90 | P95 | Max | >24,000 | >32,768 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Controls | 2 | 17,292 | 18,122.5 | 18,953 | 18,953 | 18,953 | 0 | 0 |
| Requested main | 20 | 14,359 | 17,840 | 19,899 | 19,969 | 23,945 | 0 | 0 |

No source was excluded or truncated; the three former size exclusions and former
no-selected-skill source are included. All 22 description hashes match the frozen roster,
all source IDs reconcile uniquely, the approved profile canonical identity matches its
historical frozen identity, and the pinned native parser validates the four-question pack.
The accepted 32,768-byte local bound accommodates this complete historical development
roster. This does not establish fresh daily coverage or provider acceptance.

Bindings and the private report SHA are recorded in [input binding](p0-input-binding.md).
Reproduce with `python3 /tmp/jev-p0-measure.py`, also retained as ignored
`apps/worker/resume/pivot/jev-ranking-p0-v1/measure.py`. The script imports only the
pinned pure profile/native-contract parsers, reads exact approved input files, builds
requests locally and writes only its new ignored package; it has no transport or DB path.
Actual output: controls n=2/max=18,953; main n=20/max=23,945; excluded=0;
provider_calls=0; exact_tokens=null. Quantiles use nearest rank.

Before P1 freezes its complete daily pools, rerun these measurements against that declared
inventory and accepted bindings. Exact token measurements require a documented compatible
tokenizer or authorized provider usage; unavailable counts stay explicit rather than
characters/4. Overbound remains visible deferred with reason `request_bytes_exceeded`,
unchanged source and `not_sent` delivery. Bounded provider verification belongs to separately
authorized P2. No provider calls, production DB writes or deployment ran.
