"""Orchestration: drive postings through new -> scored -> tailored -> notified.

WHY a per-stage, per-item try/except: each stage talks to a flaky external
(board API, Ollama, Claude+tectonic, Telegram). The cardinal rule is that ONE
bad posting must never abort the whole batch — on any exception we record it via
db.mark_failed and move on. Stages are pure functions over a db connection with
injected worker callables and an explicit `now`, so the whole machine is
deterministic and testable without network.

Stage gating:
  run_fetch  -> inserts brand-new postings ('new')
  run_score  -> processes ONLY 'new', advances to 'scored'
  run_tailor -> processes ONLY 'scored' with score >= threshold (the rest stay
                'scored', untouched), advances to 'tailored'
  run_notify -> processes ONLY 'tailored', advances to 'notified'. A tailored
                row always has a resume_path (save_resume requires it), so we
                always send the PDF; if it were somehow missing the notifier
                degrades to a message-only alert.
"""
from __future__ import annotations

import sqlite3

from . import db
from .fetch import DETAIL_SOURCES, fetch_company, fetch_one_company, filter_postings
from .feed import prefilter as _prefilter
from .feed import resolve as _resolve


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


# --- fetch ----------------------------------------------------------------

def run_fetch(conn, companies, title_filter, *, now, fetch_fn=fetch_company) -> int:
    """Fetch every company, title-filter, and upsert. Returns rows inserted.

    A failing company is logged-and-skipped (no posting to mark failed yet —
    nothing is in the db), so the remaining companies still ingest.
    """
    inserted = 0
    for c in companies:
        try:
            postings = fetch_fn(c["source"], c["slug"], c["name"])
            kept = filter_postings(postings, title_filter)
            for p in kept:
                p["company_slug"] = c["slug"]
            inserted += db.upsert_postings(conn, kept, now=now)
        except Exception:  # noqa: BLE001 — one bad board must not abort the rest
            continue
    return inserted


# --- feed (discovery) -----------------------------------------------------

def _feed_match_fn(source: str, wanted: set[str]):
    """Return a predicate `posting -> bool` for keeping feed-surfaced postings.

    For greenhouse/lever/ashby/smartrecruiters the wanted set holds the exact
    external_id the adapter emits, so exact membership. WORKDAY is special: the
    feed surfaces the per-tenant jobReqId but the adapter emits the GUID as
    external_id and carries the jobReqId inside posting['job_url'] (externalUrl),
    so we keep a workday posting if ANY wanted value is a substring of its
    job_url.
    """
    if source == "workday":
        return lambda p: any(w and w in (p.get("job_url") or "") for w in wanted)
    return lambda p: p.get("external_id") in wanted


def _detail_fetch(detail_fetch_fn, source: str, slug: str, ids, name: str) -> list[dict]:
    """Fetch each surfaced id one at a time, for sources with no board-list endpoint.
    One bad listing is skipped (mirroring the list adapters' per-item isolation)."""
    out: list[dict] = []
    for ext in ids:
        try:
            posting = detail_fetch_fn(source, slug, ext, name)
        except Exception:  # noqa: BLE001 — skip one bad listing, keep the rest
            continue
        if posting:
            out.append(posting)
    return out


def run_feed(conn, *, now, feed_fn, keep_categories, feed_name="simplify",
             prefilter_fn=_prefilter.prefilter, resolve_fn=_resolve.resolve_url,
             classify_fn=_resolve.classify_reason, fetch_fn=fetch_company,
             detail_fetch_fn=fetch_one_company, detail_sources=DETAIL_SOURCES,
             record_unresolved_fn=db.record_unresolved) -> int:
    """Ingest a discovery feed: prefilter cheaply, resolve each apply URL back to
    its board, then REUSE the board adapters to fetch the JD — keeping ONLY the
    feed-surfaced postings. Returns rows inserted.

    A feed is a transport, not a source: resolved postings carry the underlying
    board's (source, external_id), so they dedup against the watchlist and across
    feeds. Listings we can't resolve are recorded (feed_unresolved) as a
    next-step backlog, never silently dropped. Mirrors run_fetch's resilience:
    one bad board never aborts the batch.
    """
    # 1. cheap metadata gate, then 2. resolve -> group wanted ids by (source, slug)
    wanted: dict[tuple[str, str], set[str]] = {}
    names: dict[tuple[str, str], str] = {}
    for x in prefilter_fn(feed_fn(), keep_categories):
        url = x.get("url")
        if not url:
            continue
        r = resolve_fn(url)
        if r is None:
            host, reason = classify_fn(url)
            record_unresolved_fn(
                conn, feed=feed_name, url=url,
                company_name=x.get("company_name") or "",
                job_title=x.get("title") or "", host=host, reason=reason, now=now,
            )
            continue
        source, slug, external_id = r
        wanted.setdefault((source, slug), set()).add(external_id)
        names.setdefault((source, slug), x.get("company_name") or slug)

    # 3. per company: skip already-ingested, else fetch the board and keep only
    #    the surfaced ids. Per-group try/except so one bad board is skipped.
    inserted = 0
    for (source, slug), ids in wanted.items():
        try:
            # existing_external_ids prunes groups already fully ingested. It is a
            # no-op for workday (the feed surfaces jobReqIds, the DB stores GUIDs —
            # different id spaces — so the lookup never matches and the group always
            # re-fetches; dedup-on-upsert prevents dupes). That's intentional.
            missing = ids - db.existing_external_ids(conn, source, ids)
            if not missing:
                continue
            if source in detail_sources:
                # No board-list endpoint: fetch each surfaced id directly. external_id
                # is exactly what we fetched, so no keep-filter is needed.
                keep = _detail_fetch(detail_fetch_fn, source, slug, missing,
                                     names[(source, slug)])
            else:
                match = _feed_match_fn(source, missing)
                postings = fetch_fn(source, slug, names[(source, slug)])
                keep = [p for p in postings if match(p)]
            for p in keep:
                p["company_slug"] = slug
            inserted += db.upsert_postings(conn, keep, now=now)
        except Exception:  # noqa: BLE001 — one bad board must not abort the rest
            continue
    return inserted


# --- score ----------------------------------------------------------------

def run_score(conn, resume_text, *, now, score_fn) -> None:
    """Score every 'new' posting -> 'scored', or 'discarded' when the scorer flags
    it disqualified (conflicts with a candidate dealbreaker). Score + reason are
    kept either way so the UI can show why something was dropped."""
    for row in db.get_by_status(conn, "new"):
        posting = _row_to_dict(row)
        try:
            result = score_fn(posting)
            disqualified = bool(result.get("disqualified"))
            detail = {
                "matched_keywords": result.get("matched_keywords", []),
                "missing_keywords": result.get("missing_keywords", []),
                "reasoning": result.get("reasoning", ""),
            }
            # Per-requirement screen verdicts (which hard requirements passed/failed)
            # — kept for transparency so the UI can show why something was dropped.
            if result.get("screen"):
                detail["screen"] = result["screen"]
            if disqualified:
                detail["disqualified"] = True
                detail["disqualification_reason"] = result.get("disqualification_reason", "")
            db.save_score(
                conn, row["id"], score=int(result["score"]),
                score_detail=detail, now=now,
                status="discarded" if disqualified else "scored",
            )
        except Exception as exc:  # noqa: BLE001
            db.mark_failed(conn, row["id"], error=str(exc), now=now)


# --- tailor ---------------------------------------------------------------

def run_tailor(conn, master_tex, threshold, *, now, tailor_fn) -> None:
    """Tailor every 'scored' posting at or above `threshold`.

    Below-threshold rows are left in 'scored' untouched. The injected
    `tailor_fn(posting) -> {tex, pdf_path, pages, ok}` already encapsulates the
    single-page loop; we just persist its result.
    """
    for row in db.get_by_status(conn, "scored", min_score=threshold):
        posting = _row_to_dict(row)
        try:
            result = tailor_fn(posting)
            db.save_resume(
                conn,
                row["id"],
                resume_tex=result["tex"],
                resume_path=result["pdf_path"],
                resume_pages=int(result["pages"]),
                now=now,
            )
        except Exception as exc:  # noqa: BLE001
            db.mark_failed(conn, row["id"], error=str(exc), now=now)


# --- notify ---------------------------------------------------------------

def run_notify(conn, *, now, notify_fn, token, chat_id) -> None:
    """Notify for every 'tailored' posting and advance it to 'notified'."""
    for row in db.get_by_status(conn, "tailored"):
        posting = _row_to_dict(row)
        try:
            notify_fn(posting, posting.get("resume_path"), token=token, chat_id=chat_id)
            db.mark_notified(conn, row["id"], now=now)
        except Exception as exc:  # noqa: BLE001
            db.mark_failed(conn, row["id"], error=str(exc), now=now)
