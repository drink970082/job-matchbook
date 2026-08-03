# Onboarding any user — the design problem, recorded

**Status:** open. Discussion only, nothing decided, nothing built. Recorded 2026-08-02
so the next session starts from the constraints rather than re-deriving them.

## Why this exists

Tuning the tool for its *first* user took an afternoon: reviewing 126 golden rows,
four profile rewrites, three paid 16-row probes, and a 71-key `title_exclude` list that
only existed because a session ran ad-hoc SQL over 11,675 stored titles. **No new user
will do that**, and a general-purpose tool cannot require it.

Decompose that afternoon and only one third is irreducible:

- **One-time development, already paid for everyone.** Tier-2's head qualifier reading
  as a standalone list; a noun list getting keyword-matched (`risk`, `market data` fired
  on a genomics JD); "platform" scoped to one tier; `title_exclude` matching as a
  substring. Fixed in the prompt/format/code, so no future user meets them.
- **Irreducible per-user input.** Which role families are match / adjacent / no, plus
  résumé and hard constraints. Nobody else can supply this.
- **Accidental friction — the target.** 77 of 126 reviewed rows were consensus rows
  carrying zero information. Keyword mining needed hand-written SQL. Diagnosing *which
  profile line* caused a wrong verdict was done by reading JDs, when the scorer had
  already written the answer down (below).

## The primary goal is the FREE filter, not the taxonomy

`title_filter` / `title_exclude` run at fetch time, cost nothing, and decide what the
paid scorer ever sees. Getting them right is worth more than any refinement of the
profile prose. Measured on the first user's corpus: a tuned exclude list took kept
intake from **8,851 → 6,099 (31%)**, and the largest single group was **seniority/level
tokens — 1,821 titles, 21% of intake**.

A taxonomy/card-sort for the TARGET/ANTI tiers is a secondary aid. It must not ship as
a fixed list of role families: mining twenty families from the first user's titles and
shipping them makes this a quant tool with extra steps, and the list goes stale.
Anything taxonomy-shaped has to be **derived from the user's own fetched titles**, which
runs straight into the next section.

## The blocking constraint: onboarding runs before there is any corpus

`onboard-me` runs first and `onboard-board` after it, so **at profile-building time the
DB holds zero postings**. Every corpus-driven idea above — cluster the user's titles,
rank tokens by volume, show "excluding this drops N postings" — needs data that does not
exist yet. This is the constraint the mechanism has to survive, best-effort.

Options sketched, none chosen:

1. **Universal defaults that need no corpus.** Seniority is the one axis every field
   shares — every profession has junior and senior. `senior, sr, principal, staff,
   director, vp, ii, iii, manager, lead, intern, internship`, selected from the STAGE
   answer, is domain-independent and is the biggest group in the one corpus we have
   (21%). This is the only option that works at literal time zero.
2. **Interleave the two skills.** `onboard-board` for one to three boards → a free
   fetch → mine → finish `onboard-me`. Breaks the circular dependency at the cost of a
   longer, two-phase flow.
3. **Deferred tuning.** Ship conservative defaults, then after the first real pass the
   tool proactively surfaces the intake explorer: "here is what your feed actually
   contains, tune now."
4. **Derive candidate keywords from the résumé and profile** with the LLM, then
   validate them against the first fetch. Untested; risks inventing tokens no board uses.
5. **Ship a seed corpus of titles.** Rejected on sight — it would be *this* user's
   corpus, which is the exact skew the whole note is trying to avoid.

(1) + (3) is the cheap combination; (2) is the honest fix to the ordering. Not decided.

## The bad-start failure mode

An empty `title_exclude` passes all 11,675 titles where a tuned one passes 6,099, and
the user cannot know which are junk until they have spent to find out. Since ~96% of
paid fit calls buy a "no" (PROGRESS), a misconfigured first week can drain the quota
before the user sees a single useful verdict. Two guards beyond the defaults above:

- **Cap the first pass and label it calibration, not results** (order of 10 rows).
- **Preview before spending:** after the free fetch, "your filters let N through; at 40
  per pass that is N/40 passes", with the top volume-carrying tokens beside it.

## The scorer already names the profile line it used

Not used anywhere today, and it is the cheapest large win available. Of 502 stored
`score_detail` domain notes: **99% state `ANTI: yes/no`** and name the clause
(`...falls under the candidate's IT/infrastructure-operations anti-target`), and **54%
state the tier** (`TARGET: Priority 5, general software engineering`). Also measured:
**343 of 501 verdicts die on an ANTI, not on a tier** — the anti list does roughly twice
the work of the target tiers, so onboarding should weight the "no" bucket accordingly.

Two uses:

- **Onboarding:** group the user's disagreements by the cited line — "three of your four
  disagreements were routed through TARGET priority 3's AI clause" — instead of "you
  disagreed on four rows".
- **The eval harness:** `score_eval` records only the verdict tuple, so a flipping row
  reads as noise. Logging the cited line per draw would turn "this row is noisy" into
  "this row flips between priority 1 and priority 4". Observed 2026-08-02: two rows sat
  at `match` 3 draws out of 3 and returned `adjacent` minutes later on a fresh draw with
  a correctly-reasoned note — between-run variance on tier-boundary rows exceeds the
  within-run K=3 spread, so a 16-row K=3 probe cannot resolve a one-row difference.

## Audience — the boundary is discovery, not the adapters

Checked rather than assumed. The shipped adapters (Workday, iCIMS, Phenom, Oracle,
SmartRecruiters, Workable, Jobvite, alongside Greenhouse/Lever/Ashby) carry hospitals,
retail, logistics and government contractors as readily as tech. **Adapter coverage is
industry-general.** The first user's corpus looks like tech because their 172-company
watchlist is tech — configuration, not architecture.

What is not general is *discovery*. A user who cannot name their employers depends on a
feed, and the only feed wired up is Simplify, whose categories are
`Software, AI/ML/Data, Quant`. A nurse is serviceable today only by hand-typing a
hundred hospital names.

**Feeds are a source concept, not one integration.** Aggregated lists — GitHub
new-grad repos and similar — are the same shape as Simplify and should be addable the
way a board is. That implies an `onboard-feed` skill alongside `onboard-board`;
out of scope here, recorded so it is not re-derived.

Proposed wording, not decided: *works for any field where you can name your target
employers; ships with built-in discovery for tech and new-grad roles.* It keeps the
persona-agnostic engine the code already has and names the one missing input, rather
than narrowing the stated scope to tech and discarding capability that exists.

## UI — filters belong in the DB, not only in YAML

`config.yaml` is read at startup, so every filter change needs a worker restart. The
motivating use is **in-flight**: during a run the user notices the same unwanted title
recurring and wants it gone now. A read-only "here is what to paste" page does not serve
that, which is a reversal of this session's first recommendation.

Shape: follow the Watchlist precedent — DB owns the list, the `config.yaml` key demotes
to a one-time seed for an empty table, worker reads the table. The affordance lives in
the Discovered Jobs queue, where the repetition is actually noticed ("hide roles like
this" appends a token). The intake explorer becomes a view over the same table. Cost is
a Prisma schema change plus a server action, i.e. the watchlist migration again.

## Open questions

1. Audience wording — the capability boundary above, or narrow the stated scope to tech
   and knowledge work?
2. Is deriving the taxonomy from the user's own first fetch acceptable as *the*
   mechanism, given the tool would then ship no role list at all and step quality
   depends on what their boards return?
3. Which cold-start option, given `onboard-me` precedes `onboard-board`?
4. DB-owned filters now, or defaults plus a deferred tuning prompt first?
