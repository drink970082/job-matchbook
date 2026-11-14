"""Read-only prospective roster capture; no database, models or production wiring.

Completeness is relative to a frozen, explicitly selected single-response JSON scope.
Unsupported boards/feed coverage remain visible and prevent a complete-scope claim.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json

from ats_worker.fetch import ashby, greenhouse, lever, prefilter_postings
from ats_worker.screening.engine import deterministic_screen

ADAPTERS = {m.SOURCE: m for m in (greenhouse, lever, ashby)}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("UTC timestamps required")
    return parsed


def validate_scope(scope):
    if not isinstance(scope, dict) or set(scope) != {"version", "boards", "filters", "candidate", "feed_scope"}:
        raise ValueError("scope requires version, boards, filters, candidate and feed_scope")
    if scope["version"] != "jev-roster-scope-v1" or scope["feed_scope"] != "excluded":
        raise ValueError("this collector explicitly excludes feeds")
    if not isinstance(scope["boards"], list) or not scope["boards"]:
        raise ValueError("nonempty board scope required")
    seen = set()
    for board in scope["boards"]:
        if not isinstance(board, dict) or set(board) != {"source", "slug", "name"}:
            raise ValueError("board requires source, slug, name")
        if any(not isinstance(v, str) or not v.strip() for v in board.values()):
            raise ValueError("board fields must be nonempty strings")
        # Live URLs use slugs only; forbid URL/path injection.
        if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in board["slug"]):
            raise ValueError("invalid board slug")
        key = (board["source"], board["slug"])
        if key in seen:
            raise ValueError("duplicate board")
        seen.add(key)
    filters = scope["filters"]
    if not isinstance(filters, dict) or set(filters) != {"title_filter", "title_exclude", "max_age_days"}:
        raise ValueError("explicit filter configuration required")
    for key in ("title_filter", "title_exclude"):
        if not isinstance(filters[key], list) or any(not isinstance(v, str) for v in filters[key]):
            raise ValueError("title filters must be string arrays")
    if type(filters["max_age_days"]) is not int or filters["max_age_days"] < 0:
        raise ValueError("invalid max_age_days")
    candidate = scope["candidate"]
    if not isinstance(candidate, dict) or set(candidate) != {"locations", "exclude_internships"}:
        raise ValueError("explicit deterministic candidate gates required")
    if not isinstance(candidate["locations"], list) or any(not isinstance(v, str) for v in candidate["locations"]):
        raise ValueError("locations must be string array")
    if type(candidate["exclude_internships"]) is not bool:
        raise ValueError("exclude_internships must be boolean")


def _rows(payload, source):
    if source == "lever":
        rows = payload
    else:
        if not isinstance(payload, dict) or "jobs" not in payload:
            raise ValueError("missing jobs list")
        rows = payload["jobs"]
    if not isinstance(rows, list):
        raise ValueError("invalid jobs list")
    if any(not isinstance(v, dict) or "id" not in v or v["id"] is None or str(v["id"]) == "" for v in rows):
        raise ValueError("raw posting without stable identity")
    return rows


def collect(scope, *, fetch_json, now, window_start, window_end):
    """Capture one observation, injected HTTP and UTC clock; never write files.

    ``fetch_json(board)`` returns decoded complete JSON, not adapter-filtered rows.
    A single observation is never represented as a full daily time window.
    """
    validate_scope(scope)
    start, end, captured = map(_time, (window_start, window_end, now))
    if not start < end or not start <= captured < end:
        raise ValueError("capture must lie within the declared window")
    boards, raw_payloads, all_rows, seen = [], {}, [], {}
    for board in scope["boards"]:
        key = board["source"] + "/" + board["slug"]
        receipt = {"board": board, "status": "unsupported", "raw_count": 0,
                   "parsed_count": 0, "pagination": "unverified"}
        boards.append(receipt)
        if board["source"] not in ADAPTERS:
            continue
        try:
            payload = fetch_json(board)
            raw_payloads[key] = payload  # retained even if reconciliation/parsing fails
            receipt["raw_sha256"] = sha(payload)
            raw = _rows(payload, board["source"])
            receipt["raw_ids"] = [str(v["id"]) for v in raw]
            receipt["raw_count"] = len(raw)
            parsed = ADAPTERS[board["source"]].parse_jobs(payload, board["name"])
            if [p["external_id"] for p in parsed] != receipt["raw_ids"]:
                raise ValueError("raw/parsed identity mismatch")
            receipt["parsed_count"] = len(parsed)
            # These selected endpoints have one complete response; no adapter detail calls.
            receipt["pagination"] = "single_response_contract"
            receipt["status"] = "captured"
            for posting in parsed:
                reasons = []
                for field, reason in (("title_filter", "title_not_in_keep_list"),
                                      ("title_exclude", "title_excluded"),
                                      ("max_age_days", "posting_too_old")):
                    kw = {field: scope["filters"][field], "now": now}
                    if not prefilter_postings([posting], **kw):
                        reasons.append(reason)
                verdict = deterministic_screen({"screen": {}, "disqualified": False}, posting, scope["candidate"])
                for name, result in verdict["screen"].items():
                    if result["pass"] is False:
                        reasons.append("deterministic_" + name)
                for field in ("external_id", "job_title", "description"):
                    if not str(posting.get(field) or "").strip():
                        reasons.append("missing_" + field)
                identity = (posting["source"], posting["external_id"])
                duplicate_of = seen.get(identity)
                if duplicate_of is not None:
                    reasons.append("duplicate_identity")
                row_id = len(all_rows)
                seen.setdefault(identity, row_id)
                all_rows.append({"row_id": row_id, "board_key": key,
                                 "posting": posting, "source_sha256": sha(posting),
                                 "description_sha256": hashlib.sha256(posting["description"].encode()).hexdigest(),
                                 "duplicate_of": duplicate_of, "exclusion_reasons": reasons,
                                 "disposition": "excluded" if reasons else "retained",
                                 "hydration": "body_present" if posting["description"] else "body_missing"})
        except Exception as exc:  # isolate each board; error text may contain secrets
            receipt["status"] = "failed"
            receipt["error_type"] = type(exc).__name__
    complete = all(b["status"] == "captured" for b in boards)
    return {"schema": "jev-roster-observation-v1", "scope_sha256": sha(scope),
            "scope": scope, "captured_at": now, "window_start": window_start,
            "window_end": window_end, "boards": boards, "rows": all_rows,
            "raw_payloads": raw_payloads,
            "scope_capture_complete": complete,
            "daily_window_complete": False, "feeds_included": False,
            "completeness_limit": "One observation of selected single-response endpoints; not all-day coverage or proof of full JD content",
            "counts": {"expected_boards": len(boards), "captured_boards": sum(b["status"] == "captured" for b in boards),
                       "raw": sum(b["raw_count"] for b in boards), "parsed": len(all_rows),
                       "retained": sum(r["disposition"] == "retained" for r in all_rows),
                       "excluded": sum(r["disposition"] == "excluded" for r in all_rows)},
            "model_calls": 0, "database_writes": 0}
