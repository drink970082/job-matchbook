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
from .fetch import fetch_company, filter_postings


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
            inserted += db.upsert_postings(conn, kept, now=now)
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
