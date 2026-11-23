"""Orchestration: fetch postings ('new'), screen them against the candidate's hard
requirements, and expire dead ones.

WHY a per-stage, per-item try/except: each stage talks to a flaky external
(board API, screen provider). ONE bad posting must never abort the whole batch — on any
exception we record it and move on. Stages are pure functions over a db connection with
injected worker callables and an explicit `now`, so the whole machine is deterministic
and testable without network.

Stage gating:
  run_fetch  -> inserts brand-new postings ('new', verdict pending); code-only gates
                store a requirements discard at ingest (run_feed applies the same gate)
  run_expire -> re-checks a capped batch of live rows from per-listing sources and
                marks the 404/410 ones source_state='closed'
  run_screen -> hard-requirements screen of pending in-window 'new' rows, once each
  run_jev    -> triage (keep/skip) of pending in-window rows that passed, once each

Each posting is evaluated at most once, inside one shared window (EVALUATION_WINDOW_DAYS);
the stage that finishes it writes job_postings.verdict, and db.age_out finalizes what
left the window unfinished as `not_evaluated`.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlparse

from . import db, screening
from .jev import JevError
from .screening.errors import provider_failure_category
from .fetch import (ABSENCE_CLOSURE_SOURCES, DETAIL_SOURCES, STUB_GATE_NOW_SOURCES,
                    STUB_GATE_SOURCES, prefilter_postings, recheck_id)
from .feed import prefilter as _prefilter
from .feed import resolve as _resolve
from .source_lifecycle import (assessment_input_hash,
                               observation_error_category)


# --- fetch ----------------------------------------------------------------

def run_fetch(conn, companies, title_filter, *, now, fetch_fn=None,
              title_exclude=None, max_age_days=0, candidate=None,
              profile_version: int | None = None,
              counts: dict | None = None) -> int:
    """Fetch every company, pre-filter (title keep/exclude + max-age), tag any
    deterministic disqualification (intern/contract/location) so it is stored with its
    requirements result and verdict `discarded` WITHOUT a model call (`_gate_discard`),
    then upsert. Returns rows inserted.

    A failing company is logged-and-skipped (no posting to mark failed yet —
    nothing is in the db), so the remaining companies still ingest. Each board's result
    is written to its watchlist row (`db.record_board_health`): `ok` with the health-line
    figures, or the failure's error category.

    Before any filter, every id the board listed — returned, or seen only by the stub
    gate — is recorded as observed (`db.record_board_listing`). For a source in
    `ABSENCE_CLOSURE_SOURCES` a stored posting missing from that complete list counts
    one absence; a raising fetch records nothing, and an empty list counts nothing.

    `counts`, when given, is filled with this pass's tallies for the pass record:
    listings by drop cause, discards by failed check, inserted. Listings are counted
    every pass, including ones already stored.
    """
    if fetch_fn is None:
        raise ValueError("run_fetch requires an injected fetch_fn (wired in run.py)")
    tally = counts if counts is not None else {}
    tally.update({"boards_attempted": 0, "boards_failed": 0, "listed": 0,
                  "dropped_title": 0, "dropped_age": 0, "discarded": 0,
                  "discarded_by_reason": {}, "bodyless": 0, "detail_failed": 0,
                  "closed_by_absence": 0,
                  "inserted": 0})

    def _coarse(postings):
        """The title keep/exclude + max-age prefilter, split so each drop is counted
        under its cause. Same result as one prefilter_postings call."""
        titled = prefilter_postings(postings, title_filter=title_filter,
                                    title_exclude=title_exclude, now=now)
        fresh = prefilter_postings(titled, max_age_days=max_age_days, now=now)
        tally["dropped_title"] += len(postings) - len(titled)
        tally["dropped_age"] += len(titled) - len(fresh)
        return fresh

    def _keep(stub):
        """Fetch-cost gate handed to the two-step adapters: decide from the search
        stub alone (title + location) whether a posting is worth its detail call.
        Pure optimization — the loop below still re-runs both filters over whatever
        comes back and owns every status decision, so a wrong verdict here can only
        cost or save HTTP requests."""
        if not _coarse([stub]):
            return "drop"
        if candidate:
            verdict = screening.deterministic_screen(
                {"screen": {}, "disqualified": False, "disqualification_reason": ""},
                stub, candidate)
            if verdict.get("disqualified"):
                return "discard"
        return "hydrate"

    for c in companies:
        tally["boards_attempted"] += 1
        try:
            # Pass recipe only for recipe-driven rows so a plain 3-arg fetch_fn
            # (and every non-recipe adapter) is called exactly as before.
            kw = {"recipe": c["recipe"]} if c.get("recipe") is not None else {}
            gated: set[str] = set()   # ids the stub gate saw, including dropped ones
            # Stub-gate verdicts, counted per call rather than per id: a workday stub
            # carries no external_id, so `gated` cannot count what was listed.
            verdicts = {"calls": 0, "drop": 0}
            if c["source"] in STUB_GATE_SOURCES:
                def _observed_keep(stub, _gated=gated, _v=verdicts):
                    if stub.get("external_id"):
                        _gated.add(str(stub["external_id"]))
                    verdict = _keep(stub)
                    _v["calls"] += 1
                    _v["drop"] += verdict == "drop"
                    return verdict
                kw["keep"] = _observed_keep
                if c["source"] in STUB_GATE_NOW_SOURCES:
                    # Relative-prose stub dates need the injected clock to become a
                    # date the age gate can read; the other stub-gate adapters'
                    # fetch takes no `now`. Which sources those are is the fetch
                    # layer's to know, not ours.
                    kw["now"] = now
            postings = fetch_fn(c["source"], c["slug"], c["name"], **kw)
            returned = {str(p.get("external_id") or "") for p in postings}
            if verdicts["calls"]:
                # Every stub the gate passed should come back; one that did not lost its
                # detail call (workday returns None on a failed detail GET).
                listed = verdicts["calls"]
                tally["detail_failed"] += max(
                    0, verdicts["calls"] - verdicts["drop"] - len(postings))
            else:
                listed = len(postings)
            tally["listed"] += listed
            closed = db.record_board_listing(
                conn, c["source"], c["slug"], gated | returned, now=now,
                count_absence=c["source"] in ABSENCE_CLOSURE_SOURCES)
            tally["closed_by_absence"] += closed
            if closed:
                print(f"[fetch] {c['source']}/{c['slug']}: closed {closed} posting(s) "
                      f"absent from {db.ABSENT_LISTS_TO_CLOSE} consecutive lists")
            kept = _coarse(postings)
            for p in kept:
                p["company_slug"] = c["slug"]
                if _gate_discard(p, candidate, profile_version):
                    tally["discarded"] += 1
                    _count_failed_checks(tally["discarded_by_reason"],
                                         p["requirements"]["result"])
            # A bodyless row is permanent (upsert is ON CONFLICT DO NOTHING) and would
            # be fit-scored blind on the PAID backend. Drop it instead: a board whose
            # list endpoint carries no JD simply yields nothing this cycle. Dropping
            # (not storing as 'discarded') keeps the id re-fetchable, so the board
            # self-heals if a later cycle returns the body. Each drop is recorded in
            # feed_unresolved (feed='watchlist', reason='empty_description') so a
            # silently-broken scraper surfaces on the Unresolved board instead of
            # vanishing into a log line — the same visibility the feed path already
            # gives detail-fetch failures. Gate discards are exempt: the stub gate
            # returns them deliberately un-hydrated and they never reach the screen.
            bodyless = [p for p in kept
                        if not p.get("requirements") and not _valid_posting(p)]
            tally["bodyless"] += len(bodyless)
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
            added = db.upsert_postings(conn, kept, now=now)
            tally["inserted"] += added
            figures = _board_health(listed, kept, bodyless, added)
            _log_board_health(c, figures)
            db.record_board_health(conn, c["source"], c["slug"], now=now, status="ok",
                                   figures=figures)
        except Exception as exc:  # noqa: BLE001 — one bad board must not abort the rest
            tally["boards_failed"] += 1
            print(f"[fetch] {c.get('source')}/{c.get('slug')}: skipped after error: {exc}")
            try:
                db.record_board_health(conn, c.get("source"), c.get("slug"), now=now,
                                       status=observation_error_category(exc))
            except Exception as write_exc:  # noqa: BLE001 — the next board still fetches
                print(f"[fetch] {c.get('source')}/{c.get('slug')}: health not recorded: "
                      f"{write_exc}")
            continue
    return tally["inserted"]


def _gate_discard(posting: dict, candidate, profile_version: int | None) -> bool:
    """The fetch-time requirements gate, shared by the watchlist and the feed so the
    same miss is stored identically. A deterministic disqualification attaches the
    requirements result `db.upsert_postings` stores with verdict `discarded`."""
    if not candidate:
        return False
    verdict = screening.deterministic_screen(
        {"screen": {}, "disqualified": False, "disqualification_reason": ""},
        posting, candidate)
    if not verdict.get("disqualified"):
        return False
    posting["requirements"] = {"result": verdict, "evaluator_version": SCREEN_EVALUATOR_VERSION,
                               "profile_version": profile_version}
    return True


def _count_failed_checks(by_reason: dict, verdict: dict) -> None:
    """Count a disqualification under each screen check it failed (the check names
    are a closed set; the free-text reason is not). One posting can fail several."""
    for check, result in (verdict.get("screen") or {}).items():
        if isinstance(result, dict) and result.get("pass") is False:
            by_reason[check] = by_reason.get(check, 0) + 1


# --- feed (discovery) -----------------------------------------------------

# A scraped posting is only usable if it carries an id, a title, AND a body. An
# empty description means the scrape silently lost the JD (a moved selector) —
# the #1 way a detail/scraping adapter breaks without raising. Applied on BOTH
# insert paths: the feed's detail fetch (records the id as failed) and run_fetch's
# board path (logs and drops).
_REQUIRED_FIELDS = ("external_id", "job_title", "description")


def _valid_posting(p: dict) -> bool:
    return all(str((p or {}).get(k) or "").strip() for k in _REQUIRED_FIELDS)


def _board_health(listed: int, kept, bodyless, added: int) -> dict:
    """One board's figures for this pass (db.BOARD_HEALTH_FIGURES): what it listed,
    what the filters kept (bodyless already dropped), how many were new, how many came
    with no description, and the kept postings' median description length."""
    lengths = sorted(len(p.get("description") or "") for p in kept)
    return {"fetched": listed, "kept": len(kept), "new": added, "bodyless": len(bodyless),
            "desc_median": lengths[len(lengths) // 2] if lengths else 0}


def _log_board_health(company, h: dict) -> None:
    """One line per board per pass: what it returned and how much JD came with it.

    `_valid_posting` already catches a description that is EMPTY, which is how a moved
    selector announces itself. It cannot catch a board that serves a 250-character
    summary — that reads as a healthy fetch and silently starves the screen and JEV, which
    is why finding it took a manual query over the stored rows rather than a log. The
    median is the cheapest thing that would have said so. The same figures are stored on
    the watchlist row (db.record_board_health) for the Sources page and list_sources.
    """
    teaser = h["kept"] and h["desc_median"] < db.TEASER_MEDIAN_CHARS
    note = " TEASER? (board may need a detail step)" if teaser else ""
    print(f"[fetch] {company['source']}/{company['slug']}: fetched={h['fetched']} "
          f"kept={h['kept']} new={h['new']} bodyless={h['bodyless']} "
          f"desc_median={h['desc_median']}{note}")


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
             title_filter=None, title_exclude=None, max_age_days: int = 0,
             candidate=None, profile_version: int | None = None,
             counts: dict | None = None) -> int:
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

    `candidate` drives the same fetch-time requirements gate as `run_fetch`
    (`_gate_discard`), so a feed miss is stored exactly like a watchlist miss.

    The age gate runs TWICE, on two different dates, and both are needed. Before the
    resolve it judges the FEED's `date_posted` — a proxy, but the only date available
    while the fetch is still avoidable, so that is where the cost is saved. Before the
    upsert it re-judges the `posted_at` the board itself returned, which is the date
    actually stored. Without the second pass a feed row could sit in the DB dated older
    than `max_age_days` whenever the two dates disagreed (evergreen greenhouse reqs
    Simplify re-lists as fresh); with it, both paths make the same guarantee.

    `counts`, when given, is filled with the pass-record tallies. The buckets do not
    overlap: listings = prefilter_dropped + dropped_title + dropped_age + no_url +
    sum(unresolved_by_reason) + duplicate + already_stored + not_on_board + resolved,
    where `resolved` counts postings actually fetched from their board (a list or
    detail failure is under unresolved_by_reason instead), and resolved =
    dropped_age_board + inserted (+ any the upsert finds already stored). `discarded`
    counts the fetched postings the requirements gate discarded (a subset of resolved).
    """
    tally = counts if counts is not None else {}
    tally.update({"listings": 0, "prefilter_dropped": 0, "dropped_title": 0,
                  "dropped_age": 0, "no_url": 0, "unresolved_by_reason": {},
                  "duplicate": 0, "already_stored": 0, "not_on_board": 0,
                  "resolved": 0, "dropped_age_board": 0, "discarded": 0, "inserted": 0})
    unresolved = tally["unresolved_by_reason"]
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
        group = wanted.setdefault((source, slug), {})
        tally["duplicate"] += external_id in group
        group.setdefault(external_id, {
            "url": url,
            "company_name": listing.get("company_name") or "",
            "job_title": listing.get("title") or "",
        })

    def _record(url, listing, host, reason):
        unresolved[reason] = unresolved.get(reason, 0) + 1
        record_unresolved_fn(
            conn, feed=feed_name, url=url,
            company_name=listing.get("company_name") or "",
            job_title=listing.get("title") or "", host=host, reason=reason, now=now)

    listings = list(feed_fn())
    gated = list(prefilter_fn(listings, keep_categories))
    tally["listings"] = len(listings)
    tally["prefilter_dropped"] = len(listings) - len(gated)
    for x in gated:
        # Same one-listing call shape as run_fetch's `_keep` stub gate. Dropping here
        # rather than at the ingest tail is the whole point: past this line the listing
        # costs a resolve, a board detail fetch and a screen call. Be exact about the
        # recurrence, because it is easy to overstate — a listing that INGESTS pays
        # those once (`existing_external_ids` prunes it afterwards and the screen pass only
        # reads 'new'), so the win there is one-time and large. What recurs every pass
        # is the resolve for anything that never lands: an unresolvable URL, a board
        # that stops serving the id. A drop here is not recorded in `feed_unresolved` —
        # the operator's own config refused it, so it is not an unresolved backlog item.
        view = [_feed_posting_view(x)]
        if not prefilter_postings(view, title_filter=title_filter,
                                  title_exclude=title_exclude, now=now):
            tally["dropped_title"] += 1
            continue
        if not prefilter_postings(view, max_age_days=max_age_days, now=now):
            tally["dropped_age"] += 1
            continue
        url = x.get("url")
        if not url:
            tally["no_url"] += 1
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
        tally["already_stored"] += len(ids) - len(missing)
        if missing:
            name = next(iter(meta.values()))["company_name"] or slug
            work.append((source, slug, name, missing, meta))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fetched = list(ex.map(
            lambda w: _fetch_group(w[0], w[1], w[2], w[3],
                                   detail_fetch_fn=detail_fetch_fn, fetch_fn=fetch_fn,
                                   detail_sources=detail_sources),
            work))

    for (source, slug, name, missing, meta), (keep, failed) in zip(work, fetched):
        tally["resolved"] += len(keep)
        # A board list that answered but no longer carries a surfaced id records nothing.
        tally["not_on_board"] += max(0, len(missing) - len(keep) - len(failed))
        for fid, reason in failed:
            m = meta[fid]
            unresolved[reason] = unresolved.get(reason, 0) + 1
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
        tally["dropped_age_board"] += len(keep) - len(fresh)
        tally["discarded"] += sum(_gate_discard(p, candidate, profile_version) for p in fresh)
        tally["inserted"] += db.upsert_postings(conn, fresh, now=now)
        for p in keep:  # a URL that once failed now resolves — clear its stale row.
            m = meta.get(p["external_id"])
            if m:
                db.delete_unresolved(conn, m["url"])
    return tally["inserted"]


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
               limit=EXPIRE_BATCH, recheck_id_fn=recheck_id,
               counts: dict | None = None) -> int:
    """Re-fetch the least-recently-checked live postings and mark the dead ones
    source_state='closed', so a closed req stops sitting in the queue as a dead link.
    Returns rows closed.

    Per-LISTING sources only: they already have a per-job endpoint, so the check is
    one honest request with a real status. Board sources would need an invented one.
    `recheck_id_fn(row)` gives the key fetch_one takes (workday: the job path, not the
    stored GUID); a row with none is skipped, recorded inconclusive.
    Err toward alive — only a 404/410 closes a row (`_gone`). Any other error is
    recorded inconclusive, and so is an adapter's None; a served posting is `found`.
    Every outcome rotates the row to the back of the queue, so a row that always
    errors cannot pin the head of it; wrongly expiring a live match costs
    the operator a job while a missed dead link costs one stale row.
    `counts`, when given, gets the pass-record tallies: checked, closed, inconclusive.
    """
    expired = skipped = found = 0
    rows = db.get_recheck_candidates(conn, sorted(detail_sources), limit)
    for row in rows:
        key = recheck_id_fn(row)
        if not key:
            db.record_check_inconclusive(conn, row["id"], now=now, category="no_recheck_key")
            skipped += 1
            continue
        try:
            posting = detail_fetch_fn(row["source"], row["company_slug"] or "", key,
                                      row["company_name"])
        except Exception as exc:  # noqa: BLE001 — one bad check never aborts the pass
            if _gone(exc):
                db.mark_source_closed(conn, row["id"], now=now)
                expired += 1
            else:
                db.record_check_inconclusive(conn, row["id"], now=now,
                                             category=observation_error_category(exc))
            continue
        if posting is None:
            # The adapter declined (no usable payload): alive by default, but the
            # check proved nothing, so it must not read as a found posting.
            db.record_check_inconclusive(conn, row["id"], now=now,
                                         category="incomplete_content")
        else:
            db.record_check_found(conn, row["id"], now=now)
            found += 1
    if skipped:
        print(f"[expire] skipped {skipped} row(s) with no recheck key")
    if counts is not None:
        counts.update({"checked": len(rows), "closed": expired,
                       "inconclusive": len(rows) - expired - found})
    return expired


UNSCORED_REFRESH_MAX = 25


def run_unscored_refresh(conn, *, source: str, limit: int, now: str,
                         observation_fn) -> dict:
    """Refresh a bounded, explicitly selected slice of unscored source evidence.

    This stage only performs source GETs and conditional SQLite writes. It does not
    change pipeline/application state and never invokes a screen or fit provider.
    """
    if not isinstance(source, str) or not source.strip():
        raise ValueError("unscored refresh requires an explicit source")
    if not 1 <= limit <= UNSCORED_REFRESH_MAX:
        raise ValueError(f"unscored refresh limit must be between 1 and {UNSCORED_REFRESH_MAX}")
    if observation_fn is None:
        raise ValueError("run_unscored_refresh requires an injected observation_fn")

    rows = db.get_unscored_refresh_candidates(conn, source, limit)
    tally = {"selected": len(rows), "found": 0, "changed": 0, "closed": 0,
             "inconclusive": 0,
             "skipped": db.count_unknown_refresh_statuses(conn, source)}
    for row in rows:
        try:
            observation = observation_fn(row["source"], row["company_slug"] or "",
                                         row["external_id"], row["company_name"])
        except Exception as exc:  # noqa: BLE001 — one source failure never aborts the batch
            observation = {"state": "unknown",
                           "error_category": observation_error_category(exc)}
        before_hash = row["source_content_hash"] or assessment_input_hash(dict(row))
        after_hash = None
        if isinstance(observation, dict) and observation.get("state") == "available":
            after_hash = assessment_input_hash(observation.get("posting") or {})
        saved = db.save_source_observation(
            conn, int(row["id"]), expected_source=source,
            expected_external_id=row["external_id"], observation=observation, now=now,
        )
        if not saved:
            tally["skipped"] += 1
        elif isinstance(observation, dict) and observation.get("state") == "closed":
            tally["closed"] += 1
        elif isinstance(observation, dict) and observation.get("state") == "available" \
                and after_hash is not None:
            tally["found"] += 1
            tally["changed"] += before_hash != after_hash
        else:
            tally["inconclusive"] += 1
    print("[source-refresh] " + ", ".join(f"{key}={value}" for key, value in tally.items()))
    return tally


# --- screen ---------------------------------------------------------------


# A systemic provider outage looks like a run of failures with zero successes —
# distinct from one bad posting, which fails alone among successes. N chosen so a
# genuinely flaky-but-alive backend that lands even one success this pass never
# trips. See docs/PRINCIPLES.md "the four kinds of uncertainty" (circuit break).
_BREAKER_LIMIT = 5


class _BackendBreaker:
    """Trips once a stage has produced >= limit failures and ZERO successes this
    pass — the signature of a dead backend, not a bad item. One success disarms it
    for the pass. Per-pass (constructed fresh each run_screen call)."""

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


SCREEN_EVALUATOR_VERSION = "screen-v1"


# The evaluation window both stages share: a posting is evaluated only while posted_at
# (else created_at) is within this many days; one that leaves it unfinished is final
# `not_evaluated` (db.age_out), so no backlog ever queues.
# ponytail: a constant; make it a CLI flag if another install wants a different window.
EVALUATION_WINDOW_DAYS = 7


def window_start(now: str) -> str:
    """The first in-window date (YYYY-MM-DD) for the pass clock `now`."""
    return (datetime.fromisoformat(now.replace("Z", "+00:00"))
            - timedelta(days=EVALUATION_WINDOW_DAYS)).date().isoformat()


def run_jev(conn, *, now: str, jev_fn, model: str, limit: int, max_usd,
            clock: Callable[[], str] | None = None,
            profile_version: int | None = None) -> dict:
    """Triage each pending, screened, not-disqualified in-window posting once; a
    completed keep/skip is its final verdict and records `profile_version`.

    Sequential, no retries within a pass. Stops at `limit` postings or once settled
    spend reaches `max_usd` (a Decimal). An unknown charge stops the pass outright:
    spend that cannot be counted must not keep spending. A dead backend trips the
    breaker. Failures are stored as provider_error and retried next pass.
    """
    if limit <= 0:
        raise ValueError("jev limit must be positive")
    rows = db.get_jev_candidates(conn, window_start(now))
    tally = {"attempted": 0, "keep": 0, "skip": 0, "errors": 0, "deferred": 0,
             "spent_usd": Decimal(0), "stopped": None, "errors_by_category": {}}
    breaker = _BackendBreaker()
    for row in rows:
        if breaker.tripped:
            tally["stopped"] = "breaker"
        elif tally["attempted"] >= limit:
            tally["stopped"] = "limit"
        elif tally["spent_usd"] >= max_usd:
            tally["stopped"] = "max_usd"
        if tally["stopped"]:
            tally["deferred"] = len(rows) - tally["attempted"]
            break
        tally["attempted"] += 1
        saved_at = clock() if clock is not None else now
        try:
            out = jev_fn(dict(row))
        except JevError as exc:
            tally["spent_usd"] += exc.cost
            tally["errors"] += 1
            by = tally["errors_by_category"]
            by[exc.category] = by.get(exc.category, 0) + 1
            if exc.category != "request_too_large":
                breaker.record_failure()
            db.save_jev(conn, int(row["id"]), state="provider_error", verdict=None, reasons=None,
                        result=None, error_category=exc.category, model=model,
                        cost_usd=str(exc.cost), now=saved_at, profile_version=profile_version)
            if exc.category == "unknown_charge":
                tally["stopped"] = "unknown_charge"
                tally["deferred"] = len(rows) - tally["attempted"]
                break
            continue
        breaker.record_success()
        tally["spent_usd"] += Decimal(out["cost_usd"])
        tally[out["verdict"]] += 1
        db.save_jev(conn, int(row["id"]), state="complete", verdict=out["verdict"],
                    reasons=out["reasons"], result=out["result"], error_category=None,
                    model=model, cost_usd=out["cost_usd"], now=saved_at,
                    profile_version=profile_version)
    print(f"[jev] {tally['attempted']} assessed: {tally['keep']} keep, {tally['skip']} skip, "
          f"{tally['errors']} error(s), {tally['deferred']} deferred, "
          f"USD {tally['spent_usd']}" + (f", stopped: {tally['stopped']}" if tally["stopped"] else ""))
    return tally


def _screen_error_category(exc: Exception | None) -> str:
    """Map failures to fixed safe categories; exception text may contain job data."""
    if exc is None:
        return "provider_error"
    category = provider_failure_category(exc)
    return "screen_error" if category == "provider_error" else category


def run_screen(conn, *, now: str, screen_fn, extract, candidate=None, backend: str,
               model: str | None, effort: str | None, limit: int | None = 40,
               screen_workers: int = 1, clock: Callable[[], str] | None = None,
               profile_version: int | None = None, triage: bool = False) -> dict:
    """Screen each pending in-window `new` posting once, without touching its lifecycle.

    Fresh eligible postings run newest-first. Provider errors are retried oldest-first
    after the fresh queue; a completed screen is never re-run. Each result records
    `profile_version`; a disqualification is the final verdict `discarded`, and a pass is
    the final `keep` unless `triage` (a triage stage follows this pass). ``limit`` reserves
    only actual extraction-provider calls; deterministic-only checks continue after the
    cap. ``None`` explicitly removes that cap while retaining the provider breaker.
    DB reads/writes stay on this thread while provider work may overlap.
    """
    if limit is not None and limit <= 0:
        raise ValueError("screen provider-call limit must be positive")
    if screen_fn is None:
        raise ValueError("run_screen requires an injected screen_fn")
    since = window_start(now)
    rows = db.get_screen_candidates(conn, since)
    cached = conn.execute(
        "SELECT COUNT(*) FROM job_screenings s JOIN job_postings p "
        "ON p.id=s.job_posting_id WHERE p.pipeline_status='new' AND s.state='complete'"
    ).fetchone()[0]
    tally = {"attempted": 0, "passed": 0, "disqualified": 0, "unknown": 0,
             "errors": 0, "saved": 0, "changed": 0, "uncalled": 0,
             "disqualified_by_reason": {}, "errors_by_category": {}}
    breaker = _BackendBreaker()
    workers = max(1, int(screen_workers))

    def invoke(posting):
        try:
            return screen_fn(posting), None
        except Exception as exc:  # noqa: BLE001 — isolate one row, discard unsafe text
            return None, _screen_error_category(exc)

    def persist(row, result, error_category, *, provider_attempted):
        if error_category or (isinstance(result, dict) and result.get("provider_error")):
            category = error_category or result.get("provider_error_category") \
                or "provider_error"
            state, stored = "provider_error", None
            tally["errors"] += 1
            if provider_attempted:
                breaker.record_failure()
        else:
            if not isinstance(result, dict):
                state, stored = "provider_error", None
                category = "screen_error"
                tally["errors"] += 1
                if provider_attempted:
                    breaker.record_failure()
            else:
                state = "complete"
                stored = {key: value for key, value in result.items()
                          if key not in {"provider_error", "provider_error_category"}}
                category = None
                if provider_attempted:
                    breaker.record_success()
                if result.get("disqualified"):
                    tally["disqualified"] += 1
                    _count_failed_checks(tally["disqualified_by_reason"], result)
                else:
                    checks = (result.get("screen") or {}).values()
                    has_verdict = any(isinstance(check, dict) and "pass" in check
                                      for check in checks)
                    tally["passed" if has_verdict else "unknown"] += 1
        if category is not None:
            by = tally["errors_by_category"]
            by[category] = by.get(category, 0) + 1
        saved_at = clock() if clock is not None else now
        saved = db.save_screening(
            conn, int(row["id"]), state=state, result=stored,
            error_category=category, backend=backend, model=model, effort=effort,
            evaluator_version=SCREEN_EVALUATOR_VERSION, now=saved_at,
            profile_version=profile_version, final_on_pass=not triage,
        )
        tally["saved" if saved else "changed"] += 1

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = []
        cursor = 0
        while cursor < len(rows) or pending:
            while cursor < len(rows) and len(pending) < workers:
                row = rows[cursor]
                cursor += 1
                try:
                    needs_provider = screening.screen_requires_provider(
                        row, extract=extract, candidate=candidate)
                except Exception as exc:  # noqa: BLE001 — fail this item visibly
                    persist(row, None, _screen_error_category(exc),
                            provider_attempted=False)
                    continue
                if needs_provider:
                    if breaker.tripped or (limit is not None and tally["attempted"] >= limit):
                        tally["uncalled"] += 1
                        continue
                    tally["attempted"] += 1
                    pending.append((row, executor.submit(invoke, row), True))
                else:
                    result, category = invoke(row)
                    persist(row, result, category, provider_attempted=False)

            if pending:
                row, future, provider_attempted = pending.pop(0)
                result, category = future.result()
                persist(row, result, category, provider_attempted=provider_attempted)

    remaining = len(db.get_screen_candidates(conn, since))
    print(f"[screen-only] {tally['attempted']} provider call(s), {cached} cached, "
          f"{tally['passed']} pass, {tally['disqualified']} disqualified, "
          f"{tally['unknown']} unknown, {tally['errors']} error(s), "
          f"{tally['uncalled']} provider call(s) deferred, {remaining} still eligible")
    return tally


