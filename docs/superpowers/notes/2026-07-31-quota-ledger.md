# Quota ledger — 2026-07-31 unattended run

Budget authorized by the operator before the run: **60 paid Codex calls**. **RAISED to
300 on 2026-07-31 ~13:30**, to fund the luna-as-screen gate (249 calls) for users with no
local LLM. Hard cap at 300. At 60, stop and report — do not spend a 61st for any reason.

Plan: [`../plans/2026-07-31-quota-levers-caching-and-vetoes.md`](../plans/2026-07-31-quota-levers-caching-and-vetoes.md)

**Every paid call gets a row here, written at the time it is spent.** A session that
picks this run up mid-way reads the total from this table, not from a guess.

| # | when (EDT) | phase | calls | running total | what it bought |
|---|---|---|---|---|---|
| — | 11:47 | 0 | 0 | **0** | worktree + validation, all free |
| 1 | 12:56 | 1b | 6 | **6** | prefix-cache probe: 3 random `-C` + 3 stable `-C`, sequential, no scheduled pass in flight. **NEGATIVE** — see below. Probe rollouts deleted after reading (they carry the résumé + JD). |

## Window state at the start of the run

**37%** of the weekly primary window used; it resets 2026-08-05 (epoch 1785905532).

**Where that number came from matters, because the repo has a standing warning about it.**
PROGRESS's Defects section says "do not read `db/scorer_usage.json` without checking its
mtime" — a 07-30 reading of "23%" was 8 hours stale and made a `--score-limit` decision
~17 points optimistic. This 37% is **not** from that file: it is a direct read of
`GET /backend-api/codex/usage` at 11:30 EDT, the endpoint `capture_usage` itself calls,
bypassing the snapshot. The on-disk snapshot at that moment said 35% with an `as_of` of
04:46 — stale, exactly as the warning predicts. That gap is a live instance of the
still-open `capture_usage` defect, not a number to quote.

Measured separately from 212 historical rollouts: **12.2 calls per 1% of the window**, so
a full window is roughly **1,225 calls of this prompt shape**, and 60 calls is about
**4.9%**.

**Read that conversion as an estimate with a moving denominator.** Billing is per token,
not per call — that is this run's whole thesis — so "calls per 1%" only holds while the
prompt shape does. Phase 1 exists to cut credits per call by up to 57%, and a Luna call
costs roughly a fifth of a Sol call. The 60-call cap is the operator's authorization taken
verbatim; the window percentage moves in the operator's favour as the run proceeds.

## Rules for spending

- Nothing is spent until the free forensics for that phase have run and justified it.
- A probe that comes back ambiguous is re-run **once**, then abandoned — no third try.
- The Luna A/B (Phase 4) is capped at 50 and only runs if Phases 1 and 2 landed green.
- If the daemon trips a circuit breaker or logs a traceback, stop spending and report.

---
| 2 | 13:20 | 1b-bis | 2 | **8** | prompt-diff probe: two consecutive calls, byte-compared. All 54,542 chars IDENTICAL, and still `cached_input_tokens: 0` AND `cache_write_input_tokens: 0` — the cache is not even written. Settles it: the prompt is perfectly cacheable and the platform is not caching this traffic. Rollouts deleted. |
| 3 | 13:35 | luna-screen | 249 | **257** | `SCREEN_BACKEND=codex SCREEN_MODEL=gpt-5.6-luna make eval-screen`, 83 rows x K=3. **PASS: 0 false disqualifications** (the local 4B is RED at 2-3), recall 29/37. Window moved **40% -> 41%**, so ~250 luna calls per point. |

## Phase 1b outcome — the caching lever does not exist on the current CLI

**6 calls bought a clean negative.** Both arms cached **zero**:

```
random  call 1/2/3   input=17169   cached=0
stable  call 1/2/3   input=17183   cached=0
```

`cached_input_tokens` is present and reads `0`, so this is real absence, not missing
telemetry. Identical prompt on all six, 17-21s apart, no pass running.

**The control arm is the surprise.** It should have reproduced the 11,008-token hit that
42 of 42 historical production calls recorded. It cached nothing either — so whatever
changed did not change with the `-C` directory, and the stable-`-C` hypothesis is
untestable right now rather than refuted.

**The one strong correlate:** every historical rollout that cached ran on **codex-cli
0.144.4 / 0.144.5** (48 + 167 sessions). The installed CLI is **0.146.0**. That fits the
data exactly, but it is one version transition with no A/B behind it — leading hypothesis,
not a finding.

**Consequences, which are the reason this is written down rather than retried:**

1. **The stable-`-C` change is NOT shipped.** The plan's stop condition said so
   explicitly: "record it and stop Phase 1c rather than shipping a change with no measured
   effect". The reasoning still looks sound — the random cwd really does sit in the prompt
   ahead of the scoring prefix, and the 11,008 ceiling was real — but a change whose only
   justification is an effect nobody can currently measure has no evidence behind it.
2. **Cache warming is moot too.** You cannot warm a cache that is not operating. Positions
   0-5 of a burst missing 100% of the time stops being actionable once position 6+ also
   misses 100% of the time.
3. **Every caching figure in the plan is unsupported on this CLI** — the 51%, the 57%, the
   2.365 -> 1.027 credits/call. Do not re-quote them; they described 0.144.x.
4. **What survives, and it is the durable part:** the *instrument*. Rollout files carry
   exact `input_tokens` / `cached_input_tokens` / `output_tokens` per call. SCORING §8.5
   called message-bound "a working assumption with no measurement behind it" and named the
   missing instrument; this is it. It proved per-token billing, and it proved this
   negative.

**To reopen:** pin codex-cli 0.144.x and re-run the same six calls. That turns the leading
hypothesis into a finding or kills it, for 6 more paid calls. Not run here — downgrading
the CLI under a live daemon is not a change to make while the operator is away.
