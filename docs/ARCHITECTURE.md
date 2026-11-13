# Architecture — ATS tools with ChatGPT judgment

> **Selected JEV delivery track:** [canonical handoff](jev-ranking/README.md). JEV
> produces domain-specific ranking priorities; ChatGPT consumes them over MCP for deeper
> judgment. This target supersedes optional-model selection and mandatory legacy research
> sequences below for JEV work. Shipped behavior remains unchanged; no calls or activation
> are authorized. Use the linked delivery index for current dependencies and gates.

**Status:** approved product direction; the implementation boundary is explicit below.
The [pivot decision](superpowers/specs/2026-10-22-chatgpt-first-pivot-design.md)
sets ownership. [SPEC](SPEC.md) describes shipped behavior;
[ROADMAP](ROADMAP.md) contains work required to reach the target.

## Responsibilities

| Concern | Job Matchbook | ChatGPT / Daily Job Brief |
|---|---|---|
| Discovery | Scheduled board/feed collection, official URLs, full JD storage | Supplemental web discovery outside the watchlist |
| Evidence | Posting identity, source text, timestamps, availability and data quality | Read evidence; verify official pages before recommending |
| Judgment | Selected target: JEV domain-specific review priority; separate screening evidence | Deeper eligibility interpretation, fit, career value and final recommendations |
| Personal context | Existing private inputs remain supported for optional scoring | Primary résumé, background, preferences and recommendation rubric |
| Delivery | Existing Telegram path remains supported; service health stays local | Preferred daily recommendation and notification workflow |
| Tracking | Applications, status history, watchlist, backups and manual UI | Consult application history and distinguish possible duplicates |

```mermaid
flowchart LR
    Sources[Official boards and discovery feeds] --> Fetch[Fetch and hydrate]
    Fetch --> DB[(SQLite evidence and application records)]
    DB --> UI[Local tracker and job browser]
    DB --> Assist[Optional screen and scorer]
    Assist --> DB
    DB --> MCP[Read-only MCP tools]
    MCP --> Chat[ChatGPT judgment and Daily Brief]
    Web[Supplemental web search] --> Chat
    Profile[User-controlled résumé and search preferences] --> Chat
    Chat --> Human[Human reviews and applies]
    Human --> UI
```

The diagram expresses ownership, not a new runtime or an automatic database write
from ChatGPT. Read-only MCP cannot save recommendations, import jobs or change status.
The UI remains the manual persistence path.

## Shipped implementation

- Next.js/Prisma web app and native Python worker share SQLite with WAL. Prisma owns DDL.
- Fetch, hydration, feed resolution, coarse intake filters and application tracking exist.
- The operator-selected worker runs fetch/feed/expiry followed by standalone Codex
  `gpt-5.6-luna`, medium effort screening, one worker and explicit unlimited call count.
  Completed results are cached; provider circuit breaking remains. This is **screening**,
  not a Luna fit-scoring deployment.
- The combined screen/fit/Telegram pipeline remains the CLI default. The operator's
  screen-only mode bypasses fit and Telegram; this documentation does not change defaults.
- `job_screenings` is separate from fit `score_detail` and `pipeline_status`. A `new`
  posting can have a completed disqualification. Missing facts and provider errors are
  not evidence of eligibility.
- MCP exposes ten bounded, read-only tools and full text in chunks through the private
  tunnel. The local UI still organizes jobs into fit-oriented buckets.

## Target boundaries and implementation gaps

**Evidence vs. judgment.** Retain raw JD and official identity independently of model
assessments. Query eligibility must not depend on having a score. Existing fetch-time
candidate/title filtering must be inventoried before moving preferences to ChatGPT;
changing the scorer alone does not restore jobs excluded during intake.

**Selected ranking target.** JEV produces domain-specific priority through the
[ranking contract](jev-ranking/design.md). ChatGPT consumes ranking and full source evidence
through read-only MCP. One native request per changed binding is the first hypothesis;
guards/extractors are conditional research, not mandatory runtime stages. Machine priority
must not become the only path to discover a job. Existing screening and legacy fit capability
remain supported; selection of the JEV target does not enable it or change their defaults.

**Freshness.** Existing conflict handling does not generally update stored JDs;
expiry checks select scored/notified rows from supported detail sources. A source-first
product needs freshness/availability semantics for unscored `new` rows as well. Until
then, a stored posting is not proof that a requisition is still open.

**Personal context.** ChatGPT's durable task instructions or accessible profile document
should define current preferences and background; conversational memory alone is not a
versioned configuration. Do not remove private scorer inputs while optional fit scoring
still reads them. No private résumé or settings belong in public documentation.

**Incremental research.** Current MCP filters use posting creation/publication dates,
not screen-completion dates. List rows expose completion metadata but not the full screen
verdict. The target adds bounded verdict/time queries, explicit unknowns and queue counts.
Current completion timestamps use the pass's injected clock; a reliable future incremental
feed must account for late commits and use overlapping windows/stable ordering.

**Delivery and durable state.** A normal chat does not wake on database changes.
A configured ChatGPT task can provide a daily brief, subject to product availability,
permissions and successful unattended MCP access. The worker also starts a pass at 20:00
America/New_York, so a 20:00 brief must disclose its data cutoff rather than promise the
new pass is finished. Reliable cross-day recommendation history needs persistent records;
read-only MCP currently has none. Preserve application history as the source of truth even
when postings lack application links.

## Planned implementation sequence

The first two implementation batches are [MCP research queries](superpowers/plans/2026-10-22-batch-1-mcp-research.md)
and [visible inventory](superpowers/plans/2026-10-22-batch-2-job-inventory.md).
A manual research baseline runs alongside them; scheduled acceptance starts once the
queries/UI are usable, while lifecycle work can proceed independently. See ROADMAP for
issue dependencies and DEVELOPMENT for Astra/Sol orchestration versus Luna/max execution.

Target lifecycle design separates source availability, assessment state and user action.
Do not rewrite pipeline_status wholesale in batches 1–2. Content revision/hash and stale
assessment linkage belong to the separately designed source-lifecycle slice. Before it
ships, response time is not evidence freshness and stored jobs need official-page checks.

## Extension seams

Use the existing fetch adapters/recipes, repository queries and dependency-injected
worker modules. Prefer literal search and useful SQL filters before a vector database.
The selected JEV ranking adapter must satisfy the dedicated research and rollout gates;
it is not deployed by this design, free inference, or a replacement for full ChatGPT
explanations. Any future write tools require their own design, authorization and
provenance contract. Operational health alerts remain distinct from job recommendations.
