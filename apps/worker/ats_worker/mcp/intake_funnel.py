"""The intake funnel (#248): where every listing a pass saw went. The figures before a
posting is stored come from the pass record (`worker_runs.counts_json`); the rest are the
stored verdicts of the postings that pass inserted (`created_at` = the pass's
`started_at`). The web's lib/intake-funnel.ts is the same rule, both pinned by
tests/fixtures/intake-funnel-cases.json."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

WINDOW_DAYS = 7
SEMANTICS = (
    "each stage's input is the previous stage's output; a stored listing is counted again "
    "by every pass that lists it (stage new, already_stored); feed_gate = the feed's own gate "
    "(inactive, category, sponsorship); later stages are the current "
    "stored verdicts of the postings those passes inserted, operator overrides not applied; "
    "a posting can fail several requirements, so those reasons can exceed removed; open = "
    "verdict keep and not closed at its source; unaccounted is non-zero only when a pass "
    "record does not add up (such as one older than the already_stored tally)"
)


def intake_funnel(conn: sqlite3.Connection, now: datetime) -> dict[str, Any]:
    since = (now.astimezone(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")
    runs = [(r["started_at"], r["status"], _object(r["counts_json"])) for r in conn.execute(
        "SELECT started_at,status,counts_json FROM worker_runs ORDER BY started_at,id")]
    # A pass counts once it recorded both fetch and feed: before that its postings have
    # no complete listing figures to reconcile with.
    done = [(at, counts) for at, _, counts in runs if _intake(counts)]
    missed = sum(at >= since and status != "running" and not _intake(counts)
                 for at, status, counts in runs)
    return {
        "semantics": SEMANTICS,
        "latest_pass": _window(conn, done[-1:], 0) if done else None,
        "last_7_days": _window(conn, [d for d in done if d[0] >= since], missed),
    }


def _object(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _intake(counts: dict[str, Any]) -> bool:
    return isinstance(counts.get("fetch"), dict) and isinstance(counts.get("feed"), dict)


def _n(tally: Any, *keys: str) -> int:
    if not isinstance(tally, dict):
        return 0
    return sum(v for k in keys if type(v := tally.get(k)) is int)


def _window(conn: sqlite3.Connection, passes: list[tuple[str, dict[str, Any]]],
            missed: int) -> dict[str, Any]:
    listed = 0
    filters = {"title": 0, "age": 0, "feed_gate": 0}
    not_new = {"already_stored": 0, "duplicate": 0, "unreadable": 0, "closed": 0}
    for _, counts in passes:
        fetch = counts["fetch"]
        listed += _n(fetch, "listed")
        filters["title"] += _n(fetch, "dropped_title")
        filters["age"] += _n(fetch, "dropped_age")
        not_new["already_stored"] += _n(fetch, "already_stored")
        not_new["unreadable"] += _n(fetch, "bodyless", "detail_failed")
        not_new["closed"] += _n(fetch, "inactive")
        for feed in counts["feed"].values():
            listed += _n(feed, "listings")
            filters["title"] += _n(feed, "dropped_title")
            filters["age"] += _n(feed, "dropped_age", "dropped_age_board")
            filters["feed_gate"] += _n(feed, "prefilter_dropped")
            # A resolved posting that was neither too old nor inserted was stored already.
            not_new["already_stored"] += (_n(feed, "already_stored", "resolved")
                                          - _n(feed, "dropped_age_board", "inserted"))
            not_new["duplicate"] += _n(feed, "duplicate")
            unresolved = feed.get("unresolved_by_reason") if isinstance(feed, dict) else None
            not_new["unreadable"] += _n(feed, "no_url", "not_on_board") + _n(
                unresolved, *(unresolved if isinstance(unresolved, dict) else ()))

    starts = sorted({at for at, _ in passes})
    rows = conn.execute(
        "SELECT p.verdict,p.source_state,s.result_json FROM job_postings p "
        "LEFT JOIN job_screenings s ON s.job_posting_id=p.id AND s.state='complete' "
        "WHERE p.created_at IN (SELECT value FROM json_each(?))",
        (json.dumps(starts),)).fetchall()
    by_verdict: dict[str, int] = {}
    requirements: dict[str, int] = {}
    closed = 0
    for row in rows:
        by_verdict[row["verdict"]] = by_verdict.get(row["verdict"], 0) + 1
        closed += row["verdict"] == "keep" and row["source_state"] == "closed"
        if row["verdict"] == "discarded":
            for check in _failed_checks(row["result_json"]):
                requirements[check] = requirements.get(check, 0) + 1
    # `new` is the postings themselves, so a record that claims more or fewer inserts
    # than the store holds shows here too.
    not_new["unaccounted"] = listed - sum(filters.values()) - sum(not_new.values()) - len(rows)

    stages: list[dict[str, Any]] = []
    left = listed

    def stage(name: str, reasons: dict[str, int], removed: int | None = None) -> None:
        nonlocal left
        gone = sum(reasons.values()) if removed is None else removed
        stages.append({"stage": name, "input": left, "removed": gone, "reasons": reasons,
                       "output": left - gone})
        left -= gone

    def verdicts(*names: str) -> dict[str, int]:
        return {v: by_verdict.get(v, 0) for v in names}

    stage("filters", filters)
    stage("new", not_new)
    stage("evaluated", verdicts("pending", "not_evaluated"))
    stage("requirements", requirements, by_verdict.get("discarded", 0))
    stage("triage", verdicts("skip"))
    stage("closed", {"closed": closed})
    return {"passes": len(passes), "passes_without_intake": missed,
            "since": starts[0] if starts else None, "stages": stages, "open": left}


def _failed_checks(raw: Any) -> list[str]:
    screen = _object(raw).get("screen")
    checks = screen.items() if isinstance(screen, dict) else ()
    return [k for k, v in checks if isinstance(v, dict) and v.get("pass") is False] or ["unknown"]
