# Explicit unlimited standalone screening

**Status:** approved

The operator explicitly requests no Codex screen-call limit in the production worker.
This supersedes the mandatory production cap in the original screen/MCP plan. It does
not authorize deleting application records; old-job cleanup is a separate operator task.

## Contract

- Add `--screen-unlimited`, valid only with `--screen-only`, mutually exclusive with an
  explicit `--screen-limit`. It overrides the environment/default limit. A numeric
  `--screen-limit` still must be positive and defaults to 40; zero is not an alias.
- Represent explicit unlimited operation as `screen_limit=None` in `run_once` and
  `limit=None` in `pipeline.run_screen`. No new global backend/model defaults or schema.
- With unlimited selected, process all eligible work in existing queue order. Successful
  results stay cached; retryable errors remain fairly ordered after fresh work. Keep the
  existing provider circuit breaker, single-worker production setting and per-DB lock.
  Unlimited removes only the per-pass call count bound, not provider-error handling.
- Screen-only still never invokes fit, legacy retry, notifications or quota telemetry;
  posting lifecycle, application data and fit fields retain their existing guarantees.
- Deployment uses Codex Luna/medium and `--screen-unlimited`. Preserve existing config,
  DB, application records, Sure service and MCP read-only access.

## Design and verification

An explicit CLI switch follows PRINCIPLES 1 and 4 (operator-owned paid-call opt-in),
while the retained breaker follows principle 5 and the systemic-failure policy. Success
caching and deterministic gates preserve principles 2 and 4. Using zero as unlimited
would silently reverse the existing invalid-zero contract; a huge integer would remain
an arbitrary cap, so neither is the selected interface.

Synthetic tests must process more than 40 calls in unlimited mode, reuse success cache,
retain the breaker on a dead provider, thread None from CLI through the runner, reject
conflicting or out-of-mode use before side effects, and preserve bounded defaults.
Run worker coverage/integration, schema/privacy checks, CI and independent review.
Deploy only between passes; verify the resolved daemon command. No bulk model eval
or additional live backlog pass is needed for this control-flow change.
