# Bounded OpenRouter Haiku comparison

**Status:** approved for the bounded comparison by the operator's affirmative reply to
max60attempts/USD1within the existingUSD10grant,10exposed controls plus20newJDs×2.
This approves no automatic model selection, production wiring, merge or deployment.
Session-boot's implementation ownership applies: Luna/max implements; orchestrator owns
private source/proxy preparation, resource manifests, review and live execution.

## Exact route and inputs

Only POST `https://openrouter.ai/api/v1/chat/completions`. ModelIdentity provider is
`openrouter-chat-completions`, requested model `anthropic/claude-haiku-5.5`, resolved
advertised backend `anthropic/claude-haiku-5.5-20261007`. Freeze/revalidate public endpoint
metadata immediately before the batch; require the Anthropic endpoint's advertised dated
backend, supported strict schema parameters and rates. An alias response alone does not
independently attest the snapshot: preserve metadata-versus-response provenance.
Response provider must be exactly `Anthropic`; response model must be the selected alias
or snapshot. Request provider is only `anthropic`, `allow_fallbacks:false`,
`require_parameters:true`; no alternative model array, tools, search or retries.
Use `reasoning:{enabled:false}` and `max_tokens:2048`, bounded including reasoning.

One complete JD/source metadata plus existing approved full profile2.0.4per request.
No new resume files, applications, notes, legacy score/eval inputs or prompts. Missing JD
facts are unknown. Qualitative first/secondary families have no invented internal weights.
Freeze exact20new sources, proxy expectations, six independent typed questions, profile,
model/routing/schema/request hashes before calls. The10exposed controls are development,
not holdout; new sources remain untouched until frozen. Labels are operator proxies, not
independent human gold. A new model is not a paid judge or training target.

## Minimal injected transport

Add only an isolated direct-assessment transport and pure exact-wire builder. Accept
existing generic `Invocation`/`QuestionSet`/`ProviderReply` contracts, never impersonate a
native JEV response. Reject extraction/native JEV/nonselected identities before HTTP.
Require a caller-injected requests-like HTTP object, key,45second timeout,24KBrequest,
128KBresponse and frozen observed ISO date. No env/key/metadata/file/DB discovery in it.
One synchronous streaming POST per attempt, redirects disabled. The caller installs no
HTTP retries. Bound/validate JSON depth, duplicate members and response cardinality.

Deep-copy the supplied generic answer schema; refine evidence items to exact objects
`{source: jd|candidate_context, quote: nonempty string}`. Do not ask the model to count
characters. After parsing, uniquely locate each exact quote in the supplied full source,
then derive offsets and pass the ordinary typed assessment validator. Missing/ambiguous
quotes, invalid source, refusal, non-stop finish, wrong provider/model or malformed data
fail visibly; no semantic answer repair. Preserve raw HTTP separately from normalized
answers and deterministic spans. Programmatic quote matching proves provenance, not that
a quote supports a model's interpretation. Positive claims without evidence remain errors
or unresolved, never verified eligibility/ability.

Parse usage/actual `usage.cost` before semantic validation. Preserve known Charge/Usage in
provider failures; missing price/delivery is unknown, not zero. Charge currency USD, unit
request, rate date from the frozen metadata observed UTC date, rate source
`openrouter.response.usage.cost`. Error strings/bodies must not expose keys or private text.

## Bounds and retained accounting

Maximum60attempts including failures, one in flight,15minute segment, no retries;
USD1new-pilot limit and cumulativeUSD10global ceiling. The old JEV ledger remains retained
and is not resumed as a side effect. Its frozen850attempts/USD0.140438676are carried forward
as explicit historical attempts/spend in a linked new-stage ledger, with old-ledger full
hash and final event hash checked before every new reservation. This is an audit-linked
stage bridge, not a fresh budget/counter reset or general unattended multi-phase scheduler.
Stop if the predecessor changes, either stage has unresolved accounting, or any cap fails.
All prior failed/lost calls count. Campaign/controller locking serializes selected work.

Freeze model-specific reservation from the maximum advertised context/tier rates plus
bounded output and a documented margin; do not estimate tokens from bytes. Current
metadata's worst input tier0.0000005/token×1000000context plus2048output×0.0000025,
with20%margin, fits USD0.65reserve. Revalidate before execution. The new-stage monetary
ceiling is historical spend plusUSD1; global/ordinary ceilings remainUSD10/USD9. Unknown
charges stop rather than buying credit, changing auto top-up, switching models or retrying.

## Verify and interpret

Test pure wire/routing, quote-only schema refinement and exact-offset normalization;
known-cost bad quotes/provider/model/finish and malformed/deep/oversized response errors;
network/unknown charge; actual generic supervised journal roundtrip and blocked legacy
execution. Full worker coverage>=85%, schema drift, privacy and diff checks must pass.
Update SPEC current tooling/traceability, PROGRESS residual and CHANGELOG with source.
No Web surface changes or live provider calls in tests.

Report each axis, exact evidence, completion failures, ambiguity and repeat disagreements.
Do not claim causal model superiority from changed protocol, scalar fit accuracy from
proxies, complete requirement coverage from selected facts or a production GO.
