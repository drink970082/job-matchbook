# MCP read path: tunnel over HTTP, then option A or B (#209)

**Status:** approved 2026-11-20 (option A; scope per section 6; decision 5 open). Gates #257.

Research for epic #256. No code changes. Recommendation: **option A** (MCP server inside
the web app). The tunnel can front a streamable-HTTP server, so A is not blocked.

## 1. Can OpenAI Secure MCP Tunnel front a streamable-HTTP MCP server?

**Yes.**

- OpenAI's guide lists the target as "an MCP server that `tunnel-client` can reach over
  stdio or HTTP", and says "for an HTTP MCP server, use `--mcp-server-url
  https://mcp.internal.example.com/mcp` instead of `--mcp-command`". Streamed SSE
  responses are forwarded.
  <https://developers.openai.com/api/docs/guides/secure-mcp-tunnels>
- The tunnel-client onboarding doc describes `MCP_SERVER_URL` as the setting "for a
  Streamable HTTP MCP endpoint". It also says `Authorization` headers from the connector
  are forwarded to the MCP server origin.
  <https://github.com/openai/tunnel-client/blob/master/docs/onboarding.md>
- The installed `tunnel-client` 0.0.15 ships four samples. Three of them take an HTTP
  target (`sample_mcp_remote_no_auth`, `sample_mcp_with_dcr`,
  `sample_mcp_enterprise_proxy`). `run` has `--mcp.extra-headers` ("Static HTTP headers
  to send to the configured MCP server origin", values `env:VAR` / `file:/path`). That
  flag lets the tunnel itself send `Authorization: Bearer <read key>` from a file, the
  same way today's key file works.

**Empirical test (run locally, no OpenAI account used):**
`tunnel-client dev proxy` runs an in-memory control plane plus the tunnel runtime
entirely on loopback. I put it in front of the real `create_server()` (read tools only)
on a fixture DB, served with SDK 2.3.0 `run(transport="streamable-http")` on
`127.0.0.1`. The DB held one 40,000-character JD. A Python SDK client then went through
the proxy's ingress URL:

| Call (10 runs each) | direct HTTP median | through tunnel proxy median |
|---|---|---|
| `get_ats_overview` | 4.5 ms | 5.9 ms |
| `list_jobs` | 3.2 ms | 4.5 ms |
| `get_job_description` 16k chunk (x3, last 8k) | 2.5-2.7 ms | 4.1-4.2 ms |

`tools/list` returned all 14 tools, and each chunk had the right length. The tunnel
added about 1.5 ms per call on loopback.

**Not tested:**
- The hosted OpenAI control plane (ChatGPT -> tunnel). It needs a Platform tunnel id
  and a runtime API key on the operator's account.
- The `--mcp.extra-headers` injection.
- A plain `http://` target under `run` (as opposed to `dev proxy`). The docs only show
  `http://127.0.0.1` for the demo stub, so a `doctor --explain` check belongs in #257.

The dev proxy is the vendor's own local integration harness, so it is good evidence
that the transport works. It does not stand in for the hosted path.

## 2. Inventory: MCP read tool -> web action

"Partial" means the web action computes the same rule but is missing filters or fields,
or returns a different shape.

| MCP tool | Web counterpart | Gap |
|---|---|---|
| `list_jobs` | `getJobPostings({stage:'all'})` partial | Web pages by offset, MCP by filter-scoped keyset cursor. Web has no `source`, `pipeline_status`, `screen_state`, `triage_status`, `jev` keep/skip/all, created/posted/screening-updated windows or `application_id` filters, and no `hidden_skip_count`. Web returns `p.*` including `description` and `score_detail`; MCP omits them. The JEV/screen-outcome/stage SQL is already a TS port "kept identical". |
| `get_job` | none (detail is a list row) | Single-row read plus model, policy hash and attempt times. Small. |
| `get_job_description` | none | 16k character chunking. Trivial (`substr` plus offset and null/empty handling). |
| `get_ats_overview` | none | Disjoint counts: screen state, screen outcome, triage, JEV filter, backlog, unknown timestamps. JEV and outcome SQL exist in TS. **Triage status is SQL in Python but per-row JS in `triage-summary.ts`**, so counting needs a SQL port or a full scan. |
| `list_applications` | `getApplications` partial | Offset vs cursor; no `applied_from/to` filter; `actor` field. |
| `get_application` | none | Small. |
| `get_application_notes` | none | Chunking, same as the description chunk tool. |
| `list_application_history` | `getApplicationHistory` partial | Unpaginated in web. |
| `list_ats_records` / `get_ats_record` | none | Seven entities with an identifier allowlist, `redact_url` / `_redact_recipe` (header values, secret query keys, malformed-URL keys), the withheld-setting policy and raw/parsed legacy JSON. About 250 lines of Python, and the most security-sensitive code to port. |
| `list_sources` | `getWatchedCompanies` partial | Same `postings_30d` rule. No `has_recipe` (web returns the raw recipe; MCP must not) and no `unresolved_30d`. |
| `get_setup_status` | `getSetupStatus` partial | Same "requirements configured" rule, different shape. Web has `steps`; MCP has `missing`, `version` and `new_postings_screened_before_change`. |
| `get_jev_profile` | `getSettings().jev` partial | Same `reassessOnChange` rule. No pack question ids. |
| `get_preferences` | `getSettings().preferences` | Equivalent. |

**Bounding and sanitizing that would move to TS:**
- Already ported: `bounded_provenance`, `safe_time`, the reason/provenance/timestamp caps
  (`screen-summary.ts`, `source-lifecycle.ts`, `triage-summary.ts`).
- Still Python-only:
  - Cursor encode/decode with scope binding (`MAX_CURSOR_*`).
  - `_bounded_text` input caps and `_iso_date` / RFC3339 parsing.
  - `_like_literal` (TS has `escapeLikeLiteral`).
  - Recipe/URL redaction.
  - The `_safe_full_record` / `_list_record` field policy.
  - Error mapping that never leaks a DB path or driver text.
  - The SQLite UDFs `ats_instant_cmp` / `ats_instant_valid`. Prisma cannot register
    UDFs. Web already relies on canonical-UTC string comparison (`watchlist-actions.ts`
    comment), but the overview's "unknown assessment time" count needs a SQL or JS
    equivalent.

## 3. Security: does a read-scope key give the guarantee `mode=ro` gives?

- **Today:** all nine `/api/v1` handlers go through `write()`, which calls
  `authorize(req, 'read_write')`. A read key gets `403` on every route, and there is no
  GET route. The read key reaches no write path, but it also reaches nothing at all.
  Integration tests cover the 403 on three routes (`api-v1.int.test.ts`); the others are
  covered by construction.
- **Both A and B weaken the guarantee in kind.** Today it is enforced by the SQLite
  connection (`mode=ro` plus `query_only`). Under A or B it is enforced by code: the read
  path runs on the read-write Prisma client, and scope decides which tools or routes
  exist. Under A, a read-scope session must be built with read tools only, the same way
  the Python server omits write tools without `ATS_API_KEY`. #257 needs a test that a
  read key's `tools/list` holds only read-only tools and that calling a write tool name
  fails. A read-only Prisma client (SQLite `mode=ro` in the datasource URL) would restore
  the connection-level guard. It is unverified with Prisma's SQLite driver.
- **Wider exposure (both options):** the web port already serves about 26 unauthenticated
  server actions to anything on loopback (the `docker-compose.yml` port comment). A
  local process is therefore not stopped by the read key in either option. The new
  question is the tunnel. It forwards to the MCP server **origin**, and its OAuth
  endpoint rewriting shows that more than one path is reachable there. Under A that
  origin is the whole web app, server actions included. Request paths are chosen by
  OpenAI's control plane, not by tool input, so this is not a prompt-injection path.
  It is still a wider surface than a stdio child. Mitigation (decided, section 6): MCP
  listens on its own loopback port and the tunnel points only at that port.

## 4. Operational impact

- **Web dependency:** MCP reads need the web container up under both A and B. Writes
  already do. Today a web outage leaves reads working, and that is lost.
- **Latency:** each chunked read costs about 3-4 ms over loopback HTTP, including the
  tunnel hop (section 1). That is negligible next to the model turn. Option B adds a
  second loopback hop (MCP -> Next.js), still single-digit ms (not measured against
  Next.js).
- **Install:** A removes host Python and the checkout from the MCP path. Claude Code,
  Codex and Claude Desktop connect to the MCP loopback port (`http://127.0.0.1:<mcp-port>/mcp`)
  with a bearer header.
  ChatGPT's tunnel profile switches from `--mcp-command` to `--mcp-server-url` (plus
  `--mcp.extra-headers`). B keeps the stdio Python process, so the docker-only goal of
  #256 still fails unless the Python MCP is containerized too.

## 5. Estimate and recommendation

**Option A: TS SDK, streamable HTTP route in Next.js, tools call actions directly.**

| Work | Days |
|---|---|
| Transport on its own loopback port (a second listener in the web container that imports the same action modules and Prisma client; compose port; templates), bearer auth, per-scope tool set, error mapping | 1.0-1.5 |
| Nine write tools as direct action calls, plus instructions and prompts | 0.25 |
| Close the partial gaps (list filters, cursors or a deliberate switch to offset, field omission, sources/setup/profile shapes) by extending the existing actions | 1.0 |
| New reads: `get_job`, `get_application`, both chunk tools, overview counts (triage SQL port) | 0.75 |
| `list/get_ats_record` with redaction | 0.5 |
| Port about 68 Python tests (repository 42, protocol 4, write 22; ~1,760 lines) to jest | 1.0 |
| Templates, SETUP, tunnel profile change, delete `ats_worker/mcp/` | 0.5 |
| **Total** | **~5-5.5** |

That is above #257's 3 days. The separate port (section 6, decision 4) costs 0.5-1 day
more than a route inside Next.js. Two scope calls recover about 1-1.5 days:
1. Defer or drop the record tools (do any consumers use them?).
2. Let #258's consumer-shaped `list_jobs` replace the five-vocabulary filter set instead
   of porting it, then reshaping it.

**Option B: Python MCP keeps its process; reads go through new `/api/v1` GET routes.**
"One implementation of every read rule" still means writing the TS reads: every gap in
section 2, the overview, the chunking and the record redaction. B adds about 12 GET
routes with a JSON contract and Python HTTP-client glue, and keeps the Python MCP tests.
That is roughly 4-4.5 days, about the same as A. B also keeps two MCP-facing processes,
host Python and the checkout, so it misses the docker-only goal.

**Recommend A.** The tunnel works over HTTP, B costs about the same, and only A meets
#256's docker-only goal. #257 should carry the per-scope tool-set test and the
tunnel-origin mitigation from section 3.

## 6. Operator decisions (2026-11-20)

Option A, scoped for #257:

1. **Hosted check first.** Before #257 starts, the operator runs one hosted tunnel check
   against a scratch HTTP server (profile `sample_mcp_remote_no_auth`,
   `--mcp-server-url http://127.0.0.1:<port>/mcp`,
   `--mcp.extra-headers 'Authorization: file:...'`). It needs the Platform tunnel id and
   runtime key.
2. **Record tools deferred.** `list_ats_records` / `get_ats_record` are not ported in
   #257. They come back only if a consumer is shown to use them.
3. **`list_jobs` ported once.** It is ported in #258's new shape, not the current
   five-vocabulary filter set.
4. **Separate loopback port.** MCP listens on its own loopback port, and the tunnel points
   only at that port. The web origin and its server actions are never behind the tunnel.
5. **Open: tunnel key scope.** The deployed ChatGPT tunnel is read-write today: its
   launcher exports `ATS_API_KEY` with the read-write key, matching
   `apps/web/templates/mcp/chatgpt.txt`. `docs/SETUP.md` Path D omits the key (read-only),
   so the two shipped instructions disagree. Keeping read-write is the status quo;
   a read key would remove ChatGPT's write tools. To decide before #257 ships.

With 2, 3 and 4, A is about 4-4.5 days.
