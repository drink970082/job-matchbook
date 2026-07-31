"""Orchestration: drive postings through new -> scored -> notified, with a
capped loop back from failed -> new (run_retry).

WHY a per-stage, per-item try/except: each stage talks to a flaky external
(board API, Ollama, Claude, Telegram). The cardinal rule is that ONE
bad posting must never abort the whole batch — on any exception we record it
(db.mark_failed, or db.record_notify_failure at the notify stage) and move on. Stages are pure functions over a db connection with
injected worker callables and an explicit `now`, so the whole machine is
deterministic and testable without network.

Stage gating:
  run_fetch  -> inserts brand-new postings ('new')
  run_retry  -> processes ONLY 'failed' rows that have burned NEITHER budget
                (attempts < RETRY_MAX_ATTEMPTS AND notify_attempts <
                NOTIFY_MAX_ATTEMPTS), requeuing them to 'new' so they're
                rescored THIS SAME pass (runs before run_score). score and
                notify keep SEPARATE counters, so score hiccups can't pre-spend
                the delivery budget; but a row parked by run_notify's exhausted
                retries (notify_attempts >= NOTIFY_MAX_ATTEMPTS) still never
                qualifies — 'failed' stays terminal for it.
  run_expire -> re-checks a capped batch of live (scored|notified) rows from
                per-listing sources and marks the 404/410 ones 'expired'
                (terminal); every other outcome leaves the row alone.
  run_score  -> processes ONLY 'new', advances to 'scored'
  run_notify -> processes ONLY 'scored' rows whose fit verdicts are a strong
                match (db.get_notifiable — the rest stay 'scored', untouched);
                sends a message-only alert and advances to 'notified'. The
                verdict predicate is the notification gate. A send error
                is transient until proven persistent: the row STAYS 'scored'
                (notify_attempts+1, error recorded) so the next pass retries it,
                and parks 'failed' on the NOTIFY_MAX_ATTEMPTS-th send failure. A
                SYSTEMIC send fault (bad token) circuit-breaks the pass instead —
                see run_notify.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import db, score
from .fetch import (DETAIL_SOURCES, STUB_GATE_NOW_SOURCES, STUB_GATE_SOURCES,
                    prefilter_postings)
from .feed import prefilter as _prefilter
from .feed import resolve as _resolve


# --- fetch ----------------------------------------------------------------

def run_fetch(conn, companies, title_filter, *, now, fetch_fn=None,
              title_exclude=None, max_age_days=0, candidate=None) -> int:
    """Fetch every company, pre-filter (title keep/exclude + max-age), tag any
    deterministic disqualification (intern/location) so it lands 'discarded' WITHOUT
    an Ollama call, then upsert. Returns rows inserted.

    A failing company is logged-and-skipped (no posting to mark failed yet —
    nothing is in the db), so the remaining companies still ingest.
    """
    if fetch_fn is None:
        raise ValueError("run_fetch requires an injected fetch_fn (wired in run.py)")
    inserted = 0

    def _keep(stub):
        """Fetch-cost gate handed to the two-step adapters: decide from the search
        stub alone (title + location) whether a posting is worth its detail call.
        Pure optimization — the loop below still re-runs both filters over whatever
        comes back and owns every status decision, so a wrong verdict here can only
        cost or save HTTP requests."""
        if not prefilter_postings([stub], title_filter=title_filter,
                                  title_exclude=title_exclude,
                                  max_age_days=max_age_days, now=now):
            return "drop"
        if candidate:
            verdict = score.deterministic_screen(
                {"screen": {}, "disqualified": False, "disqualification_reason": ""},
                stub, candidate)
            if verdict.get("disqualified"):
                return "discard"
        return "hydrate"

    for c in companies:
        try:
            # Pass recipe only for recipe-driven rows so a plain 3-arg fetch_fn
            # (and every non-recipe adapter) is called exactly as before.
            kw = {"recipe": c["recipe"]} if c.get("recipe") is not None else {}
            if c["source"] in STUB_GATE_SOURCES:
                kw["keep"] = _keep
                if c["source"] in STUB_GATE_NOW_SOURCES:
                    # Relative-prose stub dates need the injected clock to become a
                    # date the age gate can read; the other stub-gate adapters'
                    # fetch takes no `now`. Which sources those are is the fetch
                    # layer's to know, not ours.
                    kw["now"] = now
            postings = fetch_fn(c["source"], c["slug"], c["name"], **kw)
            kept = prefilter_postings(
                postings, title_filter=title_filter, title_exclude=title_exclude,
                max_age_days=max_age_days, now=now)
            for p in kept:
                p["company_slug"] = c["slug"]
                if candidate:
                    verdict = score.deterministic_screen(
                        {"screen": {}, "disqualified": False, "disqualification_reason": ""},
                        p, candidate)
                    if verdict.get("disqualified"):
                        p["pipeline_status"] = "discarded"
                        p["score_detail"] = _score_detail(verdict, disqualified=True)
            # A bodyless row is permanent (upsert is ON CONFLICT DO NOTHING) and would
            # be fit-scored blind on the PAID backend. Drop it instead: a board whose
            # list endpoint carries no JD simply yields nothing this cycle. Dropping
            # (not storing as 'discarded') keeps the id re-fetchable, so the board
            # self-heals if a later cycle returns the body. Each drop is recorded in
            # feed_unresolved (feed='watchlist', reason='empty_description') so a
            # silently-broken scraper surfaces on the Unresolved board instead of
            # vanishing into a log line — the same visibility the feed path already
            # gives detail-fetch failures. 'discarded' rows are exempt: the stub gate
            # returns them deliberately un-hydrated and they never reach the scorer.
            bodyless = [p for p in kept
                        if p.get("pipeline_status") != "discarded" and not _valid_posting(p)]
            if bodyless:
                print(f"[fetch] {c['source']}/{c['slug']}: dropped {len(bodyless)} "
                      f"posting(s) with no description")
                for p in bodyless:
                    url = p.get("job_url") or ""
                    if not url:
                        continue  # no url = nothing to key feed_unresolved on
                    db.record_unresolved(
                        conn, feed="watchlist", url=url,
                        company_name=p.get("company_name") or "",
                        job_title=p.get("job_title") or "",
                        host=(urlparse(url).hostname or ""),
                        reason="empty_description", now=now)
                drop_ids = {id(p) for p in bodyless}
                kept = [p for p in kept if id(p) not in drop_ids]
            inserted += db.upsert_postings(conn, kept, now=now)
        except Exception as exc:  # noqa: BLE001 — one bad board must not abort the rest
            print(f"[fetch] {c.get('source')}/{c.get('slug')}: skipped after error: {exc}")
            continue
    return inserted


# --- feed (discovery) -----------------------------------------------------

# A scraped posting is only usable if it carries an id, a title, AND a body. An
# empty description means the scrape silently lost the JD (a moved selector) —
# the #1 way a detail/scraping adapter breaks without raising. Applied on BOTH
# insert paths: the feed's detail fetch (records the id as failed) and run_fetch's
# board path (logs and drops).
_REQUIRED_FIELDS = ("external_id", "job_title", "description")


def _valid_posting(p: dict) -> bool:
    return all(str((p or {}).get(k) or "").strip() for k in _REQUIRED_FIELDS)


def _detail_fetch(detail_fetch_fn, source: str, slug: str, ids,
                  name: str) -> tuple[list[dict], list[tuple[str, str]]]:
    """Fetch each surfaced id one at a time, for sources with no board-list endpoint.
    Returns (kept, failures) where each failure is `(external_id, reason)`. One bad
    listing is isolated, mirroring the list adapters' per-item resilience.

    The two failures are DIFFERENT diagnoses and are recorded as different reasons —
    both used to be filed under `detail_fetch_failed`, which made the collapse warning
    unable to say which had happened:

      `detail_fetch_failed` — a raise or a None. The endpoint did not serve the id,
        which for a feed-surfaced `externalPath` is usually a dead req: normal and
        harmless.
      `empty_description` — a posting came back but is missing a required field. That
        is a scraper parsing a shape it does not understand, and it is the one worth
        acting on. Same reason string the watchlist path uses for the same condition,
        so one query over `feed_unresolved` covers both paths.
    """
    kept: list[dict] = []
    failed: list[tuple[str, str]] = []
    for ext in ids:
        try:
            posting = detail_fetch_fn(source, slug, ext, name)
        except Exception:  # noqa: BLE001 — skip one bad listing, keep the rest
            failed.append((ext, "detail_fetch_failed"))
            continue
        if posting and _valid_posting(posting):
            kept.append(posting)
        elif posting:
            failed.append((ext, "empty_description"))
        else:
            failed.append((ext, "detail_fetch_failed"))
    return kept, failed


def _safe_call(fn, *args):
    """Call fn, swallowing any exception to None — one bad fetch never aborts the
    batch. Used to run injected I/O fns inside a worker thread."""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        return None


def _fetch_group(source, slug, name, missing, *, detail_fetch_fn, fetch_fn,
                 detail_sources) -> tuple[list[dict], list[tuple[str, str]]]:
    """Network-only: fetch one (source, slug) group, returning (keep, failed_ids).
    NO DB access — this runs in a worker thread (SQLite stays on the main thread).
    Per-item isolation is preserved so one bad board/listing never aborts the rest."""
    if source in detail_sources:
        # No board-list endpoint (or a per-job feed route like smartrecruiters/
        # workday): fetch each surfaced id directly — external_id is exactly what we
        # fetched, so no keep-filter; _detail_fetch isolates per id.
        return _detail_fetch(detail_fetch_fn, source, slug, missing, name)
    # Board source: list the whole board, keep only the feed-surfaced ids. A raise
    # (None) is a real failure — return the surfaced ids as failed so run_feed
    # records them, rather than silently dropping the feed-surfaced postings.
    postings = _safe_call(fetch_fn, source, slug, name)
    if postings is None:
        return [], [(m, "list_fetch_failed") for m in missing]
    return [p for p in postings if p.get("external_id") in missing], []


def _feed_posting_view(listing: dict) -> dict:
    """A feed listing in the shape `prefilter_postings` reads.

    The translation is load-bearing, not cosmetic, and it fails SILENTLY in both
    directions if skipped: the feed publishes `title` where the filter reads
    `job_title` (so a non-empty title_filter would match nothing and the feed would
    ingest ZERO rows), and it publishes `date_posted` as a Unix epoch int where
    `_too_old` parses an ISO date (so max_age_days would quietly never fire — and
    stale listings are the larger half of what the filters catch here).

    An absent or unreadable date yields None, which `_too_old` keeps — the same
    err-toward-keep policy the board path already applies to a dateless posting.
    """
    try:
        posted_at = datetime.fromtimestamp(
            int(listing.get("date_posted")), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        posted_at = None
    return {"job_title": listing.get("title") or "", "posted_at": posted_at}


def run_feed(conn, *, now, feed_fn, keep_categories, feed_name="simplify",
             prefilter_fn=_prefilter.prefilter, resolve_fn=_resolve.resolve_url,
             classify_fn=_resolve.classify_reason, fetch_fn=None,
             detail_fetch_fn=None, detail_sources=DETAIL_SOURCES,
             record_unresolved_fn=db.record_unresolved,
             resolve_embedded_fn=None, max_workers: int = 12,
             title_filter=None, title_exclude=None, max_age_days: int = 0) -> int:
    """Ingest a discovery feed: prefilter cheaply, resolve each apply URL back to
    its board, then REUSE the board adapters to fetch the JD — keeping ONLY the
    feed-surfaced postings. Returns rows inserted.

    A feed is a transport, not a source: resolved postings carry the underlying
    board's (source, external_id), so they dedup against the watchlist and across
    feeds. Listings we can't resolve are recorded (feed_unresolved) as a
    next-step backlog, never silently dropped. Mirrors run_fetch's resilience:
    one bad board never aborts the batch.

    `title_filter`/`title_exclude`/`max_age_days` are the operator's coarse filters,
    the same ones `run_fetch` applies and through the same `prefilter_postings`, so
    the rule cannot drift apart between the two paths. They run before the resolve,
    the earliest point that saves anything. The feed's own `prefilter_fn` gate is a
    different thing and still runs first: it covers active/category/sponsorship,
    which the board path has no equivalent for.

    The age gate runs TWICE, on two different dates, and both are needed. Before the
    resolve it judges the FEED's `date_posted` — a proxy, but the only date available
    while the fetch is still avoidable, so that is where the cost is saved. Before the
    upsert it re-judges the `posted_at` the board itself returned, which is the date
    actually stored. Without the second pass a feed row could sit in the DB dated older
    than `max_age_days` whenever the two dates disagreed (evergreen greenhouse reqs
    Simplify re-lists as fresh); with it, both paths make the same guarantee.
    """
    # The feed is I/O-bound: hundreds of board/listing fetches dominate the runtime.
    # So network work is run CONCURRENTLY (ThreadPoolExecutor) while every DB call
    # stays on this thread — SQLite connections are not safe across threads. Pattern
    # throughout: read (serial) -> fetch (parallel) -> write (serial).

    # 1. cheap metadata gate + resolve. resolve_url is pure; embedded greenhouse
    #    needs an I/O page-fetch, so those are collected and resolved concurrently.
    wanted: dict[tuple[str, str], dict[str, dict]] = {}
    pending_embedded: list[tuple[str, dict, str]] = []  # (url, listing, host)

    def _stash(r, url, listing):
        source, slug, external_id = r
        wanted.setdefault((source, slug), {}).setdefault(external_id, {
            "url": url,
            "company_name": listing.get("company_name") or "",
            "job_title": listing.get("title") or "",
        })

    def _record(url, listing, host, reason):
        record_unresolved_fn(
            conn, feed=feed_name, url=url,
            company_name=listing.get("company_name") or "",
            job_title=listing.get("title") or "", host=host, reason=reason, now=now)

    for x in prefilter_fn(feed_fn(), keep_categories):
        # Same one-listing call shape as run_fetch's `_keep` stub gate. Dropping here
        # rather than at the ingest tail is the whole point: past this line the listing
        # costs a resolve, a board detail fetch and a screen call. Be exact about the
        # recurrence, because it is easy to overstate — a listing that INGESTS pays
        # those once (`existing_external_ids` prunes it afterwards and `run_score` only
        # reads 'new'), so the win there is one-time and large. What recurs every pass
        # is the resolve for anything that never lands: an unresolvable URL, a board
        # that stops serving the id. A drop here is not recorded in `feed_unresolved` —
        # the operator's own config refused it, so it is not an unresolved backlog item.
        if not prefilter_postings([_feed_posting_view(x)], title_filter=title_filter,
                                  title_exclude=title_exclude,
                                  max_age_days=max_age_days, now=now):
            continue
        url = x.get("url")
        if not url:
            continue
        r = resolve_fn(url)
        if r is not None:
            _stash(r, url, x)
            continue
        host, reason = classify_fn(url)
        # Embedded greenhouse: the board token isn't in the URL but may be in the
        # company page's HTML — an injected I/O resolver (real only in run.py) can
        # recover it. Defer to the concurrent pass below; else record as today.
        if reason == "embedded_greenhouse" and resolve_embedded_fn is not None:
            pending_embedded.append((url, x, host))
        else:
            _record(url, x, host, reason)

    # 1b. resolve embedded-greenhouse pages concurrently (each is one slow fetch).
    if pending_embedded:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            resolved = list(ex.map(
                lambda t: _safe_call(resolve_embedded_fn, t[0]), pending_embedded))
        for (url, x, host), r in zip(pending_embedded, resolved):
            if r is not None:
                _stash(r, url, x)
            else:
                _record(url, x, host, "embedded_greenhouse")

    # 2. per group: prune already-ingested ids (DB, serial), fetch the boards
    #    (network, CONCURRENT — the bulk of the runtime), then write (DB, serial).
    work: list[tuple] = []  # (source, slug, name, missing, meta)
    for (source, slug), meta in wanted.items():
        ids = set(meta)
        # existing_external_ids prunes groups already fully ingested. It is a no-op
        # for workday (the feed surfaces the job's externalPath, the DB stores the
        # GUID — different id spaces — so it never matches and re-fetches each run;
        # but that's now ONE cheap per-job CXS call, not the whole board, and upsert
        # dedups the row).
        missing = ids - db.existing_external_ids(conn, source, ids)
        if missing:
            name = next(iter(meta.values()))["company_name"] or slug
            work.append((source, slug, name, missing, meta))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fetched = list(ex.map(
            lambda w: _fetch_group(w[0], w[1], w[2], w[3],
                                   detail_fetch_fn=detail_fetch_fn, fetch_fn=fetch_fn,
                                   detail_sources=detail_sources),
            work))

    inserted = 0
    for (source, slug, name, missing, meta), (keep, failed) in zip(work, fetched):
        for fid, reason in failed:
            m = meta[fid]
            record_unresolved_fn(
                conn, feed=feed_name, url=m["url"],
                company_name=m["company_name"], job_title=m["job_title"],
                host=(urlparse(m["url"]).hostname or ""),
                reason=reason, now=now)
        # A detail source that resolved ids but kept NONE = the scraper likely broke
        # (a genuinely-empty board never reaches here — missing is non-empty).
        # The warning names WHICH failure, because the two have opposite meanings and
        # this line repeats every pass: dead reqs are normal (the feed surfaces an
        # externalPath the board no longer serves), unparseable bodies are not. Without
        # the split, "may be broken" six times a day is the signal that gets tuned out.
        if source in detail_sources and not keep:
            unparseable = sum(1 for _, r in failed if r == "empty_description")
            diagnosis = (f"{unparseable} unparseable — scraper may be broken"
                         if unparseable else f"{len(failed)} dead req(s), none unparseable")
            print(f"[feed] {source}: detail-fetch collapse — "
                  f"0/{len(missing)} resolved ({diagnosis})")
        for p in keep:
            p["company_slug"] = slug
        # Re-run the age gate over the date the BOARD returned, which is the one
        # about to be stored — the gate above judged the feed's proxy date. Same
        # guarantee run_fetch makes. Age only: the title filters already passed on
        # the feed's title, and the collapse check above must see the unfiltered
        # keep (an all-stale board is not a broken scraper).
        fresh = prefilter_postings(keep, max_age_days=max_age_days, now=now)
        inserted += db.upsert_postings(conn, fresh, now=now)
        for p in keep:  # a URL that once failed now resolves — clear its stale row.
            m = meta.get(p["external_id"])
            if m:
                db.delete_unresolved(conn, m["url"])
    return inserted


# --- expire ---------------------------------------------------------------

# Per-pass re-check budget — one detail fetch each, so this is the only knob that
# bounds the extra network the expiry pass costs. ponytail: fixed cap, no config
# key; raise it here if a backlog ever needs draining faster.
EXPIRE_BATCH = 50


def _gone(exc) -> bool:
    """True ONLY for an unambiguous 'this listing no longer exists' HTTP status.
    Duck-typed off the exception's response so this module stays import-pure (no
    requests here). Everything else — timeout, 403 bot wall, 5xx, a parse error —
    is transient and must never expire a live posting."""
    return getattr(getattr(exc, "response", None), "status_code", None) in (404, 410)


def run_expire(conn, *, now, detail_fetch_fn, detail_sources=DETAIL_SOURCES,
               limit=EXPIRE_BATCH) -> int:
    """Re-fetch the least-recently-checked live postings and mark the dead ones
    'expired', so a closed req stops sitting in the queue as a dead link. Returns
    rows expired.

    Per-LISTING sources only: they already have a per-job endpoint, so the check is
    one honest request with a real status. Board sources would need an invented one.
    Err toward alive — only a 404/410 expires a row (`_gone`); anything else leaves
    it untouched for the next pass, because wrongly expiring a live match costs the
    operator a job while a missed dead link costs one stale row.
    """
    expired = 0
    for row in db.get_recheck_candidates(conn, sorted(detail_sources), limit):
        try:
            detail_fetch_fn(row["source"], row["company_slug"] or "",
                            row["external_id"], row["company_name"])
        except Exception as exc:  # noqa: BLE001 — one bad check never aborts the pass
            if _gone(exc):
                db.mark_expired(conn, row["id"], now=now)
                expired += 1
            continue
        # Alive (or the adapter declined with None — treat as alive): rotate it to
        # the back of the queue so the next pass checks different rows.
        db.touch(conn, row["id"], now=now)
    return expired


# --- score ----------------------------------------------------------------

def _score_detail(result: dict, *, disqualified: bool,
                  scorer_meta: dict | None = None) -> dict:
    """Assemble the persisted score_detail JSON from a screen+fit result.

    Shared by the disqualified-discard path (screen alone) and the scored path
    (normalized fit merged with screen) so both produce the SAME shape for the
    same inputs — byte-identical to the pre-B3 run_score's inline assembly.
    """
    detail: dict = {}
    # The fit scorecard (seniority/domain verdicts, must/nice-to-haves, summary).
    # Absent on disqualified rows — the fit call is skipped, so no assessment.
    if result.get("assessment"):
        detail["assessment"] = result["assessment"]
    # Per-requirement screen verdicts (which hard requirements passed/failed)
    # — kept for transparency so the UI can show why something was dropped.
    if result.get("screen"):
        detail["screen"] = result["screen"]
    # Which resume version the scorer recommends sending — rides the
    # score_detail JSON (no schema change), surfaced in Telegram + UI.
    if result.get("recommended_resume"):
        detail["recommended_resume"] = result["recommended_resume"]
    # JD too thin to score with confidence — routes to the low-context bucket
    # in the UI (alongside the deterministic <N-char rule), regardless of score.
    if result.get("insufficient_context"):
        detail["insufficient_context"] = True
    # Which screen checks the local model failed the row on but were re-checked by the
    # strong model instead of discarding it (SPEC §7.1). Kept whatever the outcome, so a
    # row that ends up 'discarded' anyway still shows the verdict came from the strong
    # model — and so the routed population is selectable later without re-deriving it.
    if result.get("needs_confirmation"):
        detail["needs_confirmation"] = result["needs_confirmation"]
    if disqualified:
        detail["disqualified"] = True
        detail["disqualification_reason"] = result.get("disqualification_reason", "")
    # Which scorer produced this verdict (backend / model / scorer_version) —
    # stamped ONLY where a fit call actually ran, so a screen-discarded or
    # low-context row never claims a backend it never reached. Rides the existing
    # JSON, so no schema migration; enough to read a --score-backend A/B back off
    # the data and to select the rows predating a score.txt / profile / resume
    # edit for a bounded re-score. Deliberately NOT content hashes with automatic
    # re-score triggering — that is a cache-invalidation system for a config the
    # operator changes a handful of times a year (docs/PROGRESS.md).
    if scorer_meta:
        detail.update(scorer_meta)
    return detail


def _chunks(seq: list, n: int):
    """Yield `seq` sliced into consecutive chunks of at most `n` items."""
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _persist_scored(conn, row, screen: dict, card: dict, posting: dict, *,
                    now, candidate=None, scorer_meta=None) -> None:
    """Normalize one raw fit scorecard, apply the scorer's fallback hard-requirement
    extraction (fills gaps ONLY where the screen produced no verdict for a check —
    see score.merge_fallback_screen), merge the (possibly-updated) screen verdict on
    top (normalize-then-update, the composition B2's now-removed score_posting used
    to do), and persist. A structurally-bad scorecard (score.ScoreError from
    _normalize_score) fails only THIS row — it must not abort the chunk it's part of.

    A row the fallback newly disqualifies lands 'discarded' (score 0, screen alone —
    same shape the screen-loop's own disqualified branch persists), never 'scored' —
    it never earned a fit assessment in spirit, even though the fit call already ran.
    On a working screen backend merge_fallback_screen is a no-op (the screen already
    ruled on every check), so this branch and the 'scored' outcome below are
    byte-identical to pre-fallback behavior.
    """
    # merge_fallback_screen returns a fresh verdict dict, so the routing marker has to be
    # carried across it explicitly — it is provenance, not a screen verdict, and belongs
    # in score_detail whichever way the confirmation goes.
    confirming = screen.get("needs_confirmation")
    screen = score.merge_fallback_screen(screen, card, posting, candidate)
    if confirming:
        screen = {**screen, "needs_confirmation": confirming}
    if screen.get("disqualified"):
        db.save_score(
            conn, row["id"], score=0,
            score_detail=_score_detail(screen, disqualified=True,
                                       scorer_meta=scorer_meta),
            now=now, status="discarded",
        )
        return
    try:
        result = {**score._normalize_score(card), **screen}
    except score.ScoreError as exc:
        db.mark_failed(conn, row["id"], error=str(exc), now=now)
        return
    disqualified = bool(result.get("disqualified"))
    detail = _score_detail(result, disqualified=disqualified, scorer_meta=scorer_meta)
    db.save_score(
        conn, row["id"], score=int(result["score"]),
        score_detail=detail, now=now,
        status="scored",
    )


def _persist_low_context(conn, row, screen: dict, *, now) -> None:
    """Persist a screen-surviving posting whose JD is too short to spend a PAID fit
    call on: mark it 'scored' with insufficient_context (score 0, screen verdicts
    kept), skipping the fit scorer entirely. The UI's low-context bucket and the
    notify gate already hold back any scored row under
    db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH, so scoring it would only buy a distrusted
    verdict we then hide — this reaches the identical end state minus the wasted
    message. The row still shows under Low-context for a human to eyeball the JD."""
    result = {"insufficient_context": True, "score": 0, **screen}
    db.save_score(
        conn, row["id"], score=0,
        score_detail=_score_detail(result, disqualified=False),
        now=now, status="scored",
    )


# A systemic backend/channel outage looks like a run of failures with zero
# successes — distinct from one bad posting, which fails alone among successes.
# Both run_score (dead fit backend) and run_notify (dead send channel) watch for
# it with this ONE breaker and each decides what to do with the untouched
# remainder (score leaves rows 'new'; notify leaves them 'scored'). N chosen so a
# genuinely flaky-but-alive backend that lands even one success this pass never
# trips. See docs/PRINCIPLES.md "the four kinds of uncertainty" (circuit break).
_BREAKER_LIMIT = 5


class _BackendBreaker:
    """Trips once a stage has produced >= limit failures and ZERO successes this
    pass — the signature of a dead backend, not a bad item. One success disarms it
    for the pass. Per-pass (constructed fresh each run_score / run_notify call)."""

    def __init__(self, limit: int = _BREAKER_LIMIT) -> None:
        self.limit = limit
        self.successes = 0
        self.failures = 0

    def record_success(self) -> None:
        self.successes += 1

    def record_failure(self) -> None:
        self.failures += 1

    @property
    def tripped(self) -> bool:
        return self.successes == 0 and self.failures >= self.limit


def _sweep_free_gates(conn, rows, *, candidate, now, tally) -> list:
    """Discard every row the CODE-only gates already kill, and return the rest.

    Free by construction: `deterministic_screen` is intern-title + location-string, no
    model and no provider. It is the same verdict `screen_posting` would reach, so a row
    swept here would have been discarded anyway — the difference is that it costs no
    model call and no slot in the pass's `limit` budget.

    This is the only loop in `run_score` that can write across the WHOLE queue rather
    than a bounded slice, so a per-row write failure is contained the way every other
    per-row failure here is: `db.save_score` commits per row, so an interrupted sweep
    leaves partial progress the next pass simply resumes, and one `SQLITE_BUSY` past the
    busy_timeout must not take `run_notify` down with it. Failures are counted and said
    out loud rather than swallowed.
    """
    survivors, write_errors = [], 0
    for row in rows:
        posting = dict(row)
        gate = score.deterministic_screen(
            {"screen": {}, "disqualified": False, "disqualification_reason": ""},
            posting, candidate)
        if not gate["disqualified"]:
            survivors.append(row)
            continue
        try:
            db.save_score(conn, row["id"], score=0,
                          score_detail=_score_detail(gate, disqualified=True),
                          now=now, status="discarded")
        except Exception:  # noqa: BLE001 — one unwritable row must not abort the pass
            write_errors += 1
            continue       # stays 'new'; the next pass sweeps it again, same verdict
        tally["free"] += 1
    if write_errors:
        print(f"[score] WARNING: {write_errors} free-gate discard(s) could not be "
              "written — they stay 'new' and are swept again next pass")
    return survivors


def run_score(conn, *, now, screen_fn, fit_fn, batch_size: int = 10,
              limit: int = 0, max_id: int = 0, screen_workers: int = 1,
              score_workers: int = 4, candidate=None, scorer_meta=None) -> None:
    """Score every 'new' posting -> 'scored', or 'discarded' when the screen flags
    it disqualified (conflicts with a candidate hard requirement). Score + reason are
    kept either way so the UI can show why something was dropped.

    `limit` > 0 caps how many 'new' rows this pass carries into the SCREEN phase
    (operator quota control): only the paid fit scorer costs quota, so a bounded first
    pass over a huge fresh intake avoids firing the whole backlog blind. 0 = no cap. The
    remainder stays 'new' for the next pass.

    It does NOT cap the free deterministic gates (phase 0 below), which run over the
    whole queue: charging a quota budget for work that spends no quota is what let a
    pile of requeued location discards own the head of the queue and starve the paid
    stage entirely (2026-07-31).

    **It is still not a pure quota budget, and the residual is deliberate.** A row the
    LLM screen discards, and a thin-JD row, each consume a slot while spending no quota
    — measured ~18% of screened rows. Closing that would mean screening until `limit`
    SURVIVORS are found, which makes the model work per pass unbounded; the bound is
    worth more than the last 18%. Sized from the live data the difference is ~1.3 days
    of catch-up rather than ~16.

    `max_id` > 0 restricts the pass to rows with `id <= max_id` — the SELECTOR to
    `limit`'s BUDGET, applied BEFORE it. The queue is newest-first, so `limit` can only
    name rows from the NEW end; a `--rescreen-discarded` recovery target sits at the old
    end. See SPEC §7.1 for why they are not interchangeable.

    `screen_workers`/`score_workers` bound how many screen/fit calls run
    concurrently (each I/O-bound: an HTTP round trip or a subprocess spawn) —
    see the read-serial / network-parallel / write-serial shape below, the same
    one `run_feed` uses. `candidate` is threaded into `_persist_scored`, which
    applies the fit scorer's fallback hard-requirement extraction — insurance for
    whatever check the screen produced no verdict for (see
    `score.merge_fallback_screen`).

    Three phases:
      1. SCREEN every 'new' row (cheap, local Ollama, per-item — one bad screen
         call marks only that row 'failed' and never blocks the rest). A
         disqualified posting is persisted 'discarded' right here and NEVER
         reaches the fit scorer — that's the whole point of screening first. A
         screen survivor whose JD is shorter than
         db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH is persisted 'scored' + low-context
         here too, ALSO skipping the fit scorer: the UI/notify gate hold back any
         scored row that thin, so paying to fit-score it would only buy a verdict
         we then hide.
      2. Chunk the survivors and BATCH-fit each chunk in one `fit_fn` call —
         the codex quota win (message-bound, not token-bound).
      3. FALLBACK: a chunk that raises ScoreError (e.g. a batch alignment/parse
         failure) is retried as one `fit_fn` call PER posting in that chunk, so
         a single bad JD in a batch doesn't sink its batch-mates. A single that
         STILL fails marks only that row 'failed'.
    """
    survivors: list[tuple] = []  # (row, posting, screen)
    # Most-recently-touched then newest, so `limit` takes today's discoveries — and the
    # rows run_retry just requeued, which keep their OLD ids — rather than the back of
    # the backlog (see get_by_status). The backlog then drains from its tail only when a
    # pass has headroom under the cap, which keeps clearing it an operator decision
    # instead of something the schedule does silently and expensively.
    rows = db.get_by_status(conn, "new", newest_first=True)
    # Select, then bound. Filtered here rather than in SQL because the full 'new' read
    # already happens and this is the only caller that wants it — pushing an optional
    # predicate into db.get_by_status would buy nothing but a wider signature.
    if max_id > 0:
        rows = [row for row in rows if row["id"] <= max_id]

    # ponytail: a plain dict, not a dataclass — it exists only to build the one summary
    # line below. A pass that did work used to print NOTHING on success, so a working
    # run and a no-op run were indistinguishable at the terminal (cost real debugging
    # time 2026-07-26); the breakers below already speak up, so silence read as "fine".
    tally = {"free": 0, "discarded": 0, "confirming": 0, "thin": 0, "fit": 0, "failed": 0}

    # Phase 0 — the FREE deterministic gates, over the WHOLE queue and deliberately
    # OUTSIDE `limit`. `limit` is a QUOTA budget and these gates spend no quota: no
    # model call, no paid call, 0.26 ms/row measured over 9,390 live rows. Letting one
    # consume a budget slot is what stalled the pipeline on 2026-07-31 —
    # `requeue_discarded` had moved 4,644 rows back to `new`, they sort AHEAD of fresh
    # intake (it stamps `updated_at`, which the queue orders on first), and at
    # `--score-limit 40` the daemon spent six passes a day re-killing location discards
    # for free while fit-scoring nothing, with ~16 days to go before it reached a
    # posting found today. Sweeping them here costs ~2.4s and clears the head of the
    # queue in one pass.
    rows = _sweep_free_gates(conn, rows, candidate=candidate, now=now, tally=tally)

    if limit > 0:
        rows = rows[:limit]
    postings = [dict(row) for row in rows]

    # Screen calls are I/O-bound (an HTTP round trip, or a subprocess spawn on the CLI
    # backends), so they run CONCURRENTLY while every DB call stays on this thread —
    # the same read-serial / network-parallel / write-serial shape run_feed uses,
    # because SQLite connections are not safe across threads. Consuming futures in
    # submission order keeps writes deterministic and correctly row-associated.
    # A dead screen PROVIDER is systemic, not per-item: screen_posting errs toward keep
    # on any provider failure, so an outage produces no exception and no 'failed' row —
    # it silently hands the whole backlog to the PAID fit scorer unscreened. This breaker
    # watches the same signature the fit phase does (>= limit provider errors, zero
    # successes) and aborts the screen phase, leaving the remainder 'new' and free. One
    # success disarms it, so a flaky-but-alive provider never trips it.
    # (PRINCIPLES "the four kinds of uncertainty" — circuit break.)
    screen_breaker = _BackendBreaker()
    with ThreadPoolExecutor(max_workers=max(1, screen_workers)) as ex:
        futures = [ex.submit(screen_fn, posting) for posting in postings]
        for row, posting, future in zip(rows, postings, futures):
            if screen_breaker.tripped:
                # Rest stay 'new': recoverable, and nothing was spent. Cancel what is
                # still QUEUED (in-flight calls can't be unspawned — the pool is filled
                # up front so consumption stays in submission order); on a real provider
                # each call takes long enough that this stops most of the backlog.
                # SAY SO: the rows keep attempts=0 and never reach the Failed tab, so an
                # abort that printed nothing would look exactly like a pass with no work
                # to do — the same silence this breaker exists to end.
                print("[screen] screen backend appears down "
                      f"({screen_breaker.failures} consecutive failures, no successes) "
                      "— aborting the screen phase; rows after this point stay 'new'")
                for pending in futures:
                    pending.cancel()
                break
            try:
                screen = future.result()
            except Exception as exc:  # noqa: BLE001 — one bad screen never aborts the pass
                # Counts toward the breaker exactly like a provider_error verdict: a
                # backend whose failure mode RAISES is just as systemic as one that
                # returns the flag, and leaving it uncounted would let an outage march
                # the whole backlog to terminal `failed` (the fit phase pairs the two
                # the same way).
                screen_breaker.record_failure()
                db.mark_failed(conn, row["id"], error=str(exc), now=now)
                tally["failed"] += 1
                continue
            if screen.get("provider_error"):
                screen_breaker.record_failure()
                # The CODE gates still ran and cost nothing, so a deterministic
                # disqualification is honoured below. Otherwise the row is left 'new':
                # unscreened is not scoreable, and the next pass screens it properly.
                if not screen.get("disqualified"):
                    continue
            else:
                screen_breaker.record_success()
            if screen.get("disqualified"):
                # A degree/clearance-ONLY fail is re-checked by the strong model instead
                # of being deleted: the failing verdicts are cleared, which makes them
                # gaps `merge_fallback_screen` fills from the fit scorer's own extraction,
                # arbitrated by the same CODE. Which checks qualify and why — measured
                # false-disqualification rate, not "a model produced it" — is
                # `score.screen._CONFIRMABLE_CHECKS`. Everything else stays terminal and free.
                demoted = score.demote_for_confirmation(screen)
                if demoted is None:
                    db.save_score(
                        conn, row["id"], score=0,
                        score_detail=_score_detail(screen, disqualified=True),
                        now=now, status="discarded",
                    )
                    tally["discarded"] += 1
                    continue
                screen = demoted
            if len((posting.get("description") or "").strip()) < \
                    db.LOW_CONTEXT_MAX_DESCRIPTION_LENGTH:
                # Too thin to trust a fit verdict on — bucket it low-context WITHOUT the
                # paid fit call (the UI/notify gate would hold it back anyway). Screen was
                # free (Ollama), so hard-disqualifications on thin JDs are still caught above.
                # A demoted row lands here UNCONFIRMED: no fit call runs, so nothing rules
                # on the check that was cleared. The `needs_confirmation` marker stays —
                # it names a confirmation the row still needs, and a thin-JD row is held
                # back from notify and shown for human review anyway — but it must NOT be
                # counted below, which reports confirmations that actually cost quota.
                _persist_low_context(conn, row, screen, now=now)
                tally["thin"] += 1
            else:
                if screen.get("needs_confirmation"):
                    tally["confirming"] += 1
                survivors.append((row, posting, screen))

    # Fit calls are also I/O-bound. Concurrency is QUOTA-NEUTRAL: N parallel codex
    # execs spend exactly the same number of messages as N serial ones — it only
    # changes wall-clock. (The 2026-07-15 "parallelism can't help" note assumed a
    # rolling 5-hour message window; that was corrected to WEEKLY two days later, and
    # pacing is served by --score-limit. See CHANGELOG and SPEC §11.)
    chunks = list(_chunks(survivors, batch_size))
    # Watch for a DEAD fit backend (every call failing, zero successes) — an outage,
    # not a bad posting. Convicting each row individually would burn the whole
    # backlog's retry budget on it (§ Defects). Persistence stays on THIS thread,
    # and results are consumed via as_completed and associated back to their row by
    # the future->chunk map — so a straggler never holds finished, already-paid-for
    # scores unwritten (which a crash/abort would then discard and re-purchase).
    breaker = _BackendBreaker()
    with ThreadPoolExecutor(max_workers=max(1, score_workers)) as ex:
        future_to_chunk = {ex.submit(fit_fn, [p for (_row, p, _screen) in chunk]): chunk
                           for chunk in chunks}
        try:
            for future in as_completed(future_to_chunk):
                chunk = future_to_chunk[future]
                postings = [p for (_row, p, _screen) in chunk]
                batch_error = None
                try:
                    cards = future.result()
                except Exception as exc:  # noqa: BLE001 — see below
                    # ANY batch failure falls back to singles, not just ScoreError: the
                    # codex backend wraps every failure as ScoreError, but make_claude_scorer
                    # lets a transient anthropic.RateLimitError/APIConnectionError from
                    # client.messages.create() propagate. A narrow `except ScoreError` would
                    # let that escape run_score entirely — aborting every remaining chunk AND
                    # skipping run_notify this pass, violating the cardinal "one bad posting
                    # never aborts the batch" invariant. Falling back to singles here means a
                    # transient API hiccup fails only the row(s) it actually hits (via the
                    # singles-level mark_failed), matching the old broad per-row catch.
                    # (KeyboardInterrupt is a BaseException, so it is NOT caught here — it
                    # propagates to the abort handler below.)
                    batch_error = exc
                    cards = None
                if cards is not None and len(cards) != len(postings):
                    # A backend returning fewer/more cards than postings without raising
                    # would misalign the zip below and silently orphan the tail (stuck
                    # 'new', re-scored every pass). codex raises on a missing job_ref and
                    # claude loops one-per-posting, so this is latent today — but treat a
                    # count mismatch as a batch failure so every posting is scored 1:1.
                    cards = None
                if cards is None and len(chunk) > 1:
                    # Fallback: retry this chunk's postings one fit_fn call each, so one
                    # bad JD in the batch doesn't sink its batch-mates.
                    for row, posting, screen in chunk:
                        try:
                            card = fit_fn([posting])[0]
                        except Exception as exc:  # noqa: BLE001 — a single that still fails is isolated
                            db.mark_failed(conn, row["id"], error=str(exc), now=now)
                            breaker.record_failure()
                            tally["failed"] += 1
                        else:
                            _persist_scored(conn, row, screen, card, posting,
                                            now=now, candidate=candidate,
                                            scorer_meta=scorer_meta)
                            breaker.record_success()
                            tally["fit"] += 1
                elif cards is None:
                    # batch_size 1: the chunk IS one posting, so re-issuing fit_fn([posting])
                    # would repeat the identical call that just failed — no chance of a
                    # different result, only a second spend. Mark it failed directly.
                    row, posting, screen = chunk[0]
                    err = (str(batch_error) if batch_error is not None
                           else "fit returned a mismatched card count")
                    db.mark_failed(conn, row["id"], error=err, now=now)
                    breaker.record_failure()
                    tally["failed"] += 1
                else:
                    for (row, posting, screen), card in zip(chunk, cards):
                        _persist_scored(conn, row, screen, card, posting,
                                        now=now, candidate=candidate,
                                        scorer_meta=scorer_meta)
                        breaker.record_success()
                        tally["fit"] += 1
                if breaker.tripped:
                    # Dead backend, not a bad row: stop, leave the untouched remainder
                    # 'new' (recoverable next pass) and don't spend more failing calls
                    # on the outage. Cancel the queued chunks (in-flight ones can't be
                    # unspawned, but the backlog is not queued through).
                    print(f"[score] fit backend appears down ({breaker.failures} "
                          "consecutive failures, 0 scored) — aborting this pass; "
                          "unprocessed rows left 'new'")
                    ex.shutdown(wait=False, cancel_futures=True)
                    break
        except KeyboardInterrupt:
            # Operator abort: stop LAUNCHING queued fit calls rather than draining the
            # whole backlog (the old ThreadPoolExecutor.__exit__ did shutdown(wait=True),
            # so Ctrl-C waited out ~3,985 uninterruptible codex execs). Scores already
            # persisted above are kept; rows never started stay 'new'.
            ex.shutdown(wait=False, cancel_futures=True)
            raise

    # One line, always — the pass is otherwise silent on success. `fit` is the number
    # that spent quota; `left new` is whatever a tripped breaker or an abort did not
    # reach, so a partial pass reads as partial instead of as a smaller pass.
    # Counted from the DB, not from `len(rows) - done`: under `--score-limit` that
    # arithmetic is over the SLICE, so a capped pass always claimed "0 left 'new'"
    # while thousands of rows waited. On the daemon that line prints six times a day,
    # and a queue that is not draining is exactly what it must not hide.
    done = tally["discarded"] + tally["thin"] + tally["fit"] + tally["failed"]
    remaining = conn.execute(
        "SELECT COUNT(*) FROM job_postings WHERE pipeline_status='new'").fetchone()[0]
    unreached = len(rows) - done
    # `sent for confirmation` OVERLAPS the other counts rather than adding to them: the
    # row was demoted out of `discarded`, reached the fit phase, and then landed wherever
    # that phase put it — `fit-scored` normally, but `failed` on a scorer error and
    # `unreached` behind a tripped breaker. It is on the line because it is the number
    # that moved a free outcome to a paid one, and the bucket it left (`screen-discarded`)
    # is what an operator would otherwise be watching. It is NOT in `done` for the same
    # reason: every row already increments exactly one of the four terms there.
    print(f"[score] {tally['free']} free-gate discarded (unbudgeted), then "
          f"{len(rows)} row(s): {tally['discarded']} screen-discarded, "
          f"{tally['thin']} thin-JD (no fit call), {tally['fit']} fit-scored, "
          f"{tally['confirming']} sent for confirmation, "
          f"{tally['failed']} failed, {unreached} unreached, "
          f"{remaining} left 'new'")


# --- retry ------------------------------------------------------------------

# Requeue budget for the SCORE stage. `attempts` counts score-stage failures only
# (mark_failed); notify failures land on the separate `notify_attempts` column, so
# score hiccups no longer pre-spend the delivery budget. Persistent score failures
# increment attempts each requeued pass until the 3rd trip parks it 'failed' for
# good — a hard ceiling of 3 score failures per row. run_retry guards BOTH budgets
# so a notify-exhausted row (notify_attempts >= 3) stays terminal regardless.
RETRY_MAX_ATTEMPTS = 3


def run_retry(conn, *, now) -> int:
    """Requeue every 'failed' row that has burned neither budget — attempts <
    RETRY_MAX_ATTEMPTS AND notify_attempts < NOTIFY_MAX_ATTEMPTS — back to 'new',
    so it's rescored THIS SAME pass (called before run_score in run.run_once). A
    requeued row re-runs the full screen+score — flipping to 'discarded' on retry
    is a legitimate outcome, not a bug. A row a prior notify-retry exhausted
    (notify_attempts >= 3) never qualifies, so 'failed' stays terminal for those.
    Returns the number of rows requeued.
    """
    return db.requeue_failed(conn, now, RETRY_MAX_ATTEMPTS, NOTIFY_MAX_ATTEMPTS)


# --- notify ---------------------------------------------------------------

# Retry budget for the Telegram send, counted on `notify_attempts` (its OWN column,
# separate from score `attempts`). A per-posting send error is transient until
# proven persistent: the row stays 'scored' so the next scheduled pass retries it,
# and the NOTIFY_MAX_ATTEMPTS-th failure parks it 'failed' (terminal, the web app's
# Failed tab) so a broken channel surfaces instead of retrying silently forever.
# This budget only applies to genuinely per-posting faults — a SYSTEMIC channel
# fault (bad token) circuit-breaks the pass and spends none of it (run_notify).
# ponytail: pass-cadence retry only — no in-pass backoff; the scheduler is the
# timer (~3 days at the default 24h schedule).
NOTIFY_MAX_ATTEMPTS = 3


def _systemic_send_error(exc) -> bool:
    """True for a send failure that condemns the whole Telegram CHANNEL, not one
    message — a wrong/expired bot token (401/403, or an 'unauthorized'/'invalid
    token' body). Such a failure must circuit-break the notify pass: convicting
    each matched posting individually would burn its retry budget and, on the
    NOTIFY_MAX_ATTEMPTS-th pass, PERMANENTLY destroy a finished match. Duck-typed
    off the exception's response, like `_gone`, so this module stays import-pure
    (no requests import). A rate-limit (429) / timeout / 5xx is NOT systemic here —
    those are transient and correctly ride the per-row retry budget."""
    if getattr(getattr(exc, "response", None), "status_code", None) in (401, 403):
        return True
    text = str(exc).lower()
    return "unauthorized" in text or ("invalid" in text and "token" in text)


def run_notify(conn, *, now, notify_fn, token, chat_id) -> None:
    """Notify every scored posting whose fit verdicts mark it a strong match
    (db.get_notifiable) and advance it to 'notified' (clearing any prior send
    error). Non-matching rows stay 'scored', untouched. The verdict predicate
    is the gate now — the old score>=threshold gate is gone (the score
    quantized to the rubric band edge and flipped run-to-run; the verdicts
    are stable). One message-only alert per posting. Delivery is at-least-once:
    a timeout after Telegram delivered re-sends next pass (one duplicate ping)
    rather than risking a lost alert.

    Failure handling distinguishes SYSTEMIC from per-posting (PRINCIPLES, "the
    four kinds of uncertainty"):
      - A systemic channel fault (`_systemic_send_error` — a bad token), or
        `_BREAKER_LIMIT` consecutive send failures with zero deliveries, CIRCUIT-
        BREAKS the pass: every remaining row stays 'scored', NO notify_attempts
        spent, one operator line printed. A broken channel must never convict the
        postings riding on it.
      - A genuinely per-posting send error keeps that row 'scored'
        (notify_attempts+1, error recorded) for a next-pass retry until
        NOTIFY_MAX_ATTEMPTS charges park it 'failed'. notify_attempts is delivery's
        OWN budget — score hiccups never pre-spend it.
    """
    breaker = _BackendBreaker()
    for row in db.get_notifiable(conn):
        posting = dict(row)
        try:
            notify_fn(posting, token=token, chat_id=chat_id)
        except Exception as exc:  # noqa: BLE001
            # The bot token rides in the Telegram URL, which requests embeds in the
            # exception text; scrub it before it lands in pipeline_error (rendered by
            # the web Failed bucket) or on stdout. (Guard the empty-token case: an
            # empty replace() would splice "***" between every character.)
            error = str(exc).replace(token, "***") if token else str(exc)
            if _systemic_send_error(exc):
                print(f"[notify] send channel rejected auth ({error}) — circuit-breaking "
                      "this pass: all matched rows left 'scored', no attempts spent")
                return
            attempt = row["notify_attempts"] + 1
            exhausted = attempt >= NOTIFY_MAX_ATTEMPTS
            db.record_notify_failure(conn, row["id"], error=error, now=now,
                                     exhausted=exhausted)
            print(f"[notify] send failed (attempt {attempt}/{NOTIFY_MAX_ATTEMPTS}) "
                  f"for posting id={row['id']}: {error}"
                  + (" — parked as failed" if exhausted else "; will retry next pass"))
            breaker.record_failure()
            if breaker.tripped:
                print(f"[notify] {breaker.failures} consecutive send failures, 0 delivered "
                      "— circuit-breaking this pass; remaining matched rows left 'scored'")
                return
        else:
            db.mark_notified(conn, row["id"], now=now)
            breaker.record_success()
