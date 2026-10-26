# Job triage classification

**Status:** implemented

The operator requests Web/MCP distinguish rule-based rejection, standalone screening
rejection and retained candidates. This approval covers presentation/query correction,
not changed screening judgments or deployment of fit pre-ranking (#96).

## Contract

Add a derived, consistent job-triage summary/filter to Web inventory/detail and MCP
list/detail/overview. Do not change existing standalone screen_outcome semantics,
source lifecycle or stored pipeline state. No new database columns or migrations.

- `rule_disqualified`: supported stored evidence of a deterministic location/internship
  failure. Require valid typed disqualified=true with a failing code-only check and a
  screen containing only the documented deterministic location/internship checks;
  classify active stored rejection evidence, not the word discarded alone. Legacy
  score_detail must be a discarded row, with no fit assessment/provenance, and meet
  that narrow shape. An unrelated model or legacy rejection is never called rule-based.
  A rule-only standalone record can also carry deterministic rejection: standalone
  storage does not prove that a provider was invoked.
- `screen_disqualified`: valid completed standalone disqualification with supported
  failing checks that is not a rule-only rejection.
- `candidate`: valid standalone no_disqualifier_found on a nonterminal posting (new,
  scored or notified). This is retained for fit research, not fully qualified, open,
  recommended, sponsorship-confirmed or applied status. Source/assessment freshness
  remains separate and visible.
- `needs_review`: no assessment, provider error, malformed/contradictory assessment,
  unsupported legacy evidence, terminal/manual state inconsistent with candidate,
  or unknown lifecycle. Preserve a bounded explanatory reason; do not silently reject
  or promote. Current standalone evidence takes precedence over legacy embedded data.
- Duplicate object members at the supported evidence root, screen map, or check object
  make that evidence ambiguous and therefore `needs_review`.
- Legacy `source_content_revision` may be absent or null. When non-null, accept only a
  mathematically integral JSON number from 1 through JavaScript's maximum safe integer;
  decimal and exponent notation such as `3.0` and `3e0` are valid when the value is an
  integer. Booleans, fractions, non-positive and unsafe values are unsupported.

Expose a bounded provenance/reason with triage status, without raw JSON/JD/errors.
Overview counts must partition every stored posting, with scope explicit. Filtering
must happen before pagination and use the same semantics as list/detail/counts.
Existing standalone outcome filters remain backwards compatible. UI calls the missing
record condition "No standalone record", not an overall unscreened claim, and clearly
labels legacy fit buckets independently of the new triage filter. Old fit actions and
bulk safety scopes stay unchanged. Raw no-record state is not a processing backlog.

## Principles and alternatives

Principles 2/3/5 require deterministic evidence-based classification, unresolved states
kept visible, and no invented provenance. Principle 4 keeps fit assessment optional.
Principles 9/12 preserve schema ownership and private data. Rejected: infer all discarded
as rule rejection; overwrite screen_outcome with a different concept; rerun production
screening or delete old rows to make counts look consistent.

## Acceptance

Use a shared synthetic fixture to prove Web/Python parity for rule location/internship,
standalone model rejection/pass/provider error, absent rows, malformed JSON, booleans
versus strings, unsupported legacy model/fit evidence, rule-only standalone records,
conflicting legacy/current evidence and terminal/unknown posting states. Verify list,
detail, overview and paginated filters agree; safe existing filters/actions stay intact.
Run worker/web/coverage/lint/integration and schema/privacy checks. Drive the changed UI
on synthetic data or a read-only production-like snapshot. Fresh independent exact-head
review and CI are merge gates. No real provider calls required for derived semantics.
