"""Bounded, allowlisted read access to the application-owned ATS SQLite schema."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qsl, quote, unquote_plus, urlencode, urlsplit, urlunsplit


DEFAULT_BUSY_TIMEOUT_MS = 5_000
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
TEXT_CHUNK_SIZE = 16_000
MAX_SEARCH_CHARS = 200
MAX_FILTER_CHARS = 200
MAX_CURSOR_CHARS = 1_024
MAX_CURSOR_KEY_CHARS = 300

REQUIRED_TABLES = frozenset({
    "applications",
    "job_postings",
    "job_screenings",
    "status_history",
    "watched_companies",
    "feed_unresolved",
    "promotion_dismissed",
    "app_settings",
})

PIPELINE_STATUSES = frozenset({
    "new", "scored", "notified", "applied", "discarded", "failed", "removed", "expired",
})
APPLICATION_STATUSES = frozenset({
    "Applied", "Online Assessment", "Phone Screen", "Interviewing: 1st round",
    "Interviewing: 2nd round", "Interviewing: 3rd round", "Interviewing: 4th round",
    "Interviewing: 5th round", "Final Round", "Offer", "Accepted", "Rejected",
    "Withdrew", "Ghosted",
})

# This is the allowlist for all dynamic table names and primary keys. User input selects
# only an entry from this closed map; it never becomes a SQL identifier.
ENTITY_KEYS: dict[str, tuple[str, str, str]] = {
    "applications": ("applications", "id", "int"),
    "job_postings": ("job_postings", "id", "int"),
    "job_screenings": ("job_screenings", "id", "int"),
    "status_history": ("status_history", "id", "int"),
    "watched_companies": ("watched_companies", "id", "int"),
    "feed_unresolved": ("feed_unresolved", "id", "int"),
    "promotion_dismissed": ("promotion_dismissed", "id", "int"),
    "app_settings": ("app_settings", "key", "str"),
}

LIST_OMIT_FIELDS = {
    "applications": frozenset({"notes"}),
    "job_postings": frozenset({"description", "score_detail"}),
    "job_screenings": frozenset({"result_json"}),
}

SAFE_SETTING_VALUE_KEYS = frozenset({"categories"})
REDACTED = "[REDACTED]"
MALFORMED_RECIPE = "[withheld: malformed recipe cannot be safely redacted]"
UNREVIEWED_SETTING = "[withheld: setting key has no approved read policy]"

_SECRET_QUERY_KEYS = frozenset({
    "token", "accesstoken", "authtoken", "auth", "authorization", "apikey", "key",
    "secret", "clientsecret", "signature", "sig", "password", "passwd",
    "credential", "credentials", "accesskey", "jwt",
})
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INTEGER_KEY_RE = re.compile(r"^[1-9]\d{0,9}$")


class RepositoryError(Exception):
    """An actionable, safe-to-return repository error."""


class QueryInputError(RepositoryError):
    pass


class RecordNotFound(RepositoryError):
    pass


class DatabaseUnavailable(RepositoryError):
    pass


@dataclass(frozen=True)
class _Cursor:
    key: int | str
    extra: int | None = None


def _bounded_text(value: str | None, name: str, maximum: int, *, allow_empty: bool = True) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise QueryInputError(f"{name} must be text")
    if len(value) > maximum:
        raise QueryInputError(f"{name} is too long (maximum {maximum} characters)")
    if not allow_empty and not value:
        raise QueryInputError(f"{name} must not be empty")
    return value


def _positive_id(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise QueryInputError(f"{name} must be a positive integer")
    return value


def _page_size(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PAGE_SIZE:
        raise QueryInputError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    return value


def _iso_date(value: str | None, name: str) -> str | None:
    value = _bounded_text(value, name, 10, allow_empty=False)
    if value is None:
        return None
    if not _DATE_RE.fullmatch(value):
        raise QueryInputError(f"{name} must be an ISO date in YYYY-MM-DD form")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise QueryInputError(f"{name} must be a real calendar date") from exc
    if parsed.isoformat() != value:
        raise QueryInputError(f"{name} must be an ISO date in YYYY-MM-DD form")
    return value


def _check_range(start: str | None, end: str | None, start_name: str, end_name: str) -> None:
    if start and end and start > end:
        raise QueryInputError(f"{start_name} must not be after {end_name}")


def _like_literal(value: str) -> str:
    return "%" + value.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def _secret_query_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", unquote_plus(key).lower())
    return normalized in _SECRET_QUERY_KEYS or any(
        normalized.endswith(suffix)
        for suffix in ("token", "secret", "apikey", "signature", "credential")
    )


def redact_url(value: str) -> str:
    """Replace conventional secret query values while retaining the rest of a URL."""
    try:
        parts = urlsplit(value)
        if not parts.query:
            return value
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        safe_pairs = [(key, REDACTED if _secret_query_key(key) else item)
                      for key, item in pairs]
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           urlencode(safe_pairs, doseq=True), parts.fragment))
    except (TypeError, ValueError):
        # A malformed URL must not turn into an unredacted fallback.
        return re.sub(
            r"([?&](?:[^=&#]*(?:token|secret|api[-_]?key|signature|password|auth)[^=&#]*)=)[^&#]*",
            lambda match: match.group(1) + quote(REDACTED), value, flags=re.IGNORECASE,
        )


def _redact_recipe(value: Any, *, key: str = "") -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, child in value.items():
            if str(child_key).casefold() == "headers":
                if isinstance(child, dict):
                    result[child_key] = {header: REDACTED for header in child}
                elif isinstance(child, list):
                    result[child_key] = [
                        [pair[0], REDACTED] if isinstance(pair, (list, tuple)) and len(pair) >= 2
                        else REDACTED for pair in child
                    ]
                else:
                    result[child_key] = REDACTED
            else:
                result[child_key] = _redact_recipe(child, key=str(child_key))
        return result
    if isinstance(value, list):
        return [_redact_recipe(item, key=key) for item in value]
    if isinstance(value, str) and ("?" in value or key.lower() in {"url", "job_url", "application_url"}):
        return redact_url(value)
    return value


def _json_info(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {"raw": None, "parsed": None, "parse_status": "null"}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw": raw, "parsed": None, "parse_status": "malformed"}
    return {"raw": raw, "parsed": parsed, "parse_status": "valid"}


def _recipe_info(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {"raw_redacted": None, "parsed": None, "parse_status": "null"}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw_redacted": MALFORMED_RECIPE, "parsed": None,
                "parse_status": "malformed_withheld"}
    if not isinstance(parsed, dict):
        return {"raw_redacted": MALFORMED_RECIPE, "parsed": None,
                "parse_status": "malformed_withheld"}
    safe = _redact_recipe(parsed)
    safe_json = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
    return {"raw_redacted": safe_json, "parsed": safe, "parse_status": "valid_redacted"}


def _cursor_encode(scope: str, key: int | str, extra: int | None = None) -> str:
    payload = {"v": 1, "scope": scope, "key": key}
    if extra is not None:
        payload["extra"] = extra
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _filter_scope(name: str, filters: dict[str, Any]) -> str:
    """Bind a cursor to the exact filters without storing search text in the token."""
    canonical = json.dumps(filters, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{name}:{digest}"


def _cursor_decode(cursor: str | None, scope: str, key_kind: str,
                   *, composite: bool = False) -> _Cursor | None:
    if cursor is None:
        return None
    cursor = _bounded_text(cursor, "cursor", MAX_CURSOR_CHARS, allow_empty=False)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", cursor):
        raise QueryInputError("cursor is malformed")
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
    except (ValueError, json.JSONDecodeError, TypeError, UnicodeError):
        raise QueryInputError("cursor is malformed") from None
    if not isinstance(payload, dict) or payload.get("v") != 1 or payload.get("scope") != scope:
        raise QueryInputError("cursor does not match this query")
    value = payload.get("key")
    if key_kind == "int":
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise QueryInputError("cursor is malformed")
    else:
        if not isinstance(value, str) or len(value) > MAX_CURSOR_KEY_CHARS:
            raise QueryInputError("cursor is malformed")
    extra = payload.get("extra")
    if composite:
        if isinstance(extra, bool) or not isinstance(extra, int) or extra <= 0:
            raise QueryInputError("cursor is malformed")
    elif "extra" in payload:
        raise QueryInputError("cursor is malformed")
    return _Cursor(value, extra)


def _page(rows: list[dict[str, Any]], limit: int, scope: str,
          key_field: str, *, descending: bool, extra_field: str | None = None) -> dict[str, Any]:
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = _cursor_encode(scope, last[key_field],
                                    last[extra_field] if extra_field else None)
    return {"items": items, "limit": limit, "has_more": has_more,
            "next_cursor": next_cursor, "ordering": "live keyset page; not a snapshot"}


def _safe_url_fields(record: dict[str, Any]) -> dict[str, Any]:
    for field in ("url", "job_url", "application_url"):
        value = record.get(field)
        if isinstance(value, str):
            record[field] = redact_url(value)
    return record


def _safe_full_record(entity: str, raw: dict[str, Any]) -> dict[str, Any]:
    record = _safe_url_fields(raw)
    if entity == "job_postings":
        description = record.pop("description", None)
        record["description_is_null"] = description is None
        record["description_chars"] = None if description is None else len(description)
        record["description_read_tool"] = "get_job_description"
        score_detail_info = _json_info(record.get("score_detail"))
        record["score_detail_parsed"] = score_detail_info["parsed"]
        record["score_detail_parse_status"] = score_detail_info["parse_status"]
        if record.get("pipeline_error"):
            record["pipeline_error"] = redact_url(record["pipeline_error"])
    elif entity == "applications":
        notes = record.pop("notes", None)
        record["notes_is_null"] = notes is None
        record["notes_chars"] = None if notes is None else len(notes)
        record["notes_read_tool"] = "get_application_notes"
    elif entity == "job_screenings":
        info = _json_info(record.get("result_json"))
        record["result_json_parsed"] = info["parsed"]
        record["result_json_parse_status"] = info["parse_status"]
    elif entity == "watched_companies":
        info = _recipe_info(record.get("recipe"))
        record["recipe_raw_redacted"] = info["raw_redacted"]
        record["recipe_parsed"] = info["parsed"]
        record["recipe_parse_status"] = info["parse_status"]
        record.pop("recipe", None)
    elif entity == "app_settings":
        value = record.pop("value", None)
        if record.get("key") in SAFE_SETTING_VALUE_KEYS:
            info = _json_info(value)
            record["value_raw"] = info["raw"]
            record["value_parsed"] = info["parsed"]
            record["value_parse_status"] = info["parse_status"]
            record["value_policy"] = "approved: categories vocabulary"
        else:
            record["value"] = UNREVIEWED_SETTING
            record["value_policy"] = "withheld until this setting key has an explicit policy"
    return record


def _list_record(entity: str, raw: dict[str, Any]) -> dict[str, Any]:
    omit = LIST_OMIT_FIELDS.get(entity, frozenset())
    record = {key: value for key, value in raw.items() if key not in omit}
    if "description" in raw:
        record["description_is_null"] = raw["description"] is None
        record["description_chars"] = len(raw["description"] or "")
        record["description_read_tool"] = "get_job_description"
    if "notes" in raw:
        record["notes_is_null"] = raw["notes"] is None
        record["notes_chars"] = None if raw["notes"] is None else len(raw["notes"])
        record["notes_read_tool"] = "get_application_notes"
    if "score_detail" in raw:
        record["score_detail_chars"] = None if raw["score_detail"] is None else len(raw["score_detail"])
        record["score_detail_read_tool"] = "get_ats_record"
    if "result_json" in raw:
        record["result_json_chars"] = None if raw["result_json"] is None else len(raw["result_json"])
        record["result_json_read_tool"] = "get_ats_record"
    if entity == "watched_companies":
        info = _recipe_info(raw.get("recipe"))
        record.pop("recipe", None)
        record["recipe_raw_redacted"] = info["raw_redacted"]
        record["recipe_parse_status"] = info["parse_status"]
    if entity == "app_settings":
        value = raw.get("value")
        if raw.get("key") in SAFE_SETTING_VALUE_KEYS:
            info = _json_info(value)
            record["value_raw"] = info["raw"]
            record["value_parsed"] = info["parsed"]
            record["value_parse_status"] = info["parse_status"]
        else:
            record["value"] = UNREVIEWED_SETTING
            record["value_policy"] = "withheld until this setting key has an explicit policy"
    return _safe_url_fields(record)


class ReadOnlyATSRepository:
    """An allowlisted query API over SQLite opened in read-only/query-only mode."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            configured = os.environ.get("ATS_DB_PATH")
            db_path = configured or (Path(__file__).resolve().parents[4]
                                     / "apps" / "web" / "prisma" / "applications.db")
        self.db_path = Path(db_path).expanduser()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            absolute = self.db_path.resolve(strict=False)
            connection = sqlite3.connect(
                absolute.as_uri() + "?mode=ro", uri=True,
                timeout=DEFAULT_BUSY_TIMEOUT_MS / 1000,
            )
        except (OSError, sqlite3.Error, ValueError):
            raise DatabaseUnavailable(
                "ATS database is unavailable; check ATS_DB_PATH and file permissions"
            ) from None
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute(f"PRAGMA busy_timeout = {DEFAULT_BUSY_TIMEOUT_MS}")
            if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
                raise DatabaseUnavailable("ATS database connection is not query-only")
            present = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED_TABLES.issubset(present):
                raise DatabaseUnavailable(
                    "ATS database schema is incomplete; check ATS_DB_PATH and apply the Prisma schema"
                )
            yield connection
        except RepositoryError:
            raise
        except sqlite3.Error:
            raise DatabaseUnavailable(
                "ATS database could not be read; check its schema and permissions"
            ) from None
        finally:
            connection.close()

    @staticmethod
    def _count(conn: sqlite3.Connection, table: str) -> int:
        # `table` is always a literal from this module's closed table list.
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

    @staticmethod
    def _group_counts(conn: sqlite3.Connection, table: str, column: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            f'SELECT "{column}" AS value, COUNT(*) AS count FROM "{table}" '
            f'GROUP BY "{column}" ORDER BY "{column}"'
        ).fetchall()
        known = (PIPELINE_STATUSES if table == "job_postings" else
                 APPLICATION_STATUSES if table == "applications" else
                 frozenset({"complete", "provider_error"}) if table == "job_screenings" else
                 frozenset())
        return [{"value": row["value"], "count": int(row["count"]),
                 "known": row["value"] in known} for row in rows]

    def get_ats_overview(self) -> dict[str, Any]:
        with self._connection() as conn:
            # One read snapshot keeps grouped totals internally reconcilable while the
            # worker or web app writes through WAL.
            conn.execute("BEGIN")
            tables = {table: self._count(conn, table) for table, _, _ in ENTITY_KEYS.values()}
            posting_screens = conn.execute(
                "SELECT CASE WHEN s.id IS NULL THEN 'not_screened' ELSE s.state END AS state, "
                "COUNT(*) AS count FROM job_postings p LEFT JOIN job_screenings s "
                "ON s.job_posting_id=p.id GROUP BY state ORDER BY state"
            ).fetchall()
            screening_records = self._group_counts(conn, "job_screenings", "state")
            pipeline_counts = self._group_counts(conn, "job_postings", "pipeline_status")
            application_counts = self._group_counts(conn, "applications", "status")
            return {
                "table_counts": tables,
                "pipeline_status_counts": pipeline_counts,
                "application_status_counts": application_counts,
                "screen_state_counts_by_posting": [
                    {"state": row["state"], "count": int(row["count"])}
                    for row in posting_screens
                ],
                "screening_record_state_counts": screening_records,
                "unknown_pipeline_statuses": [row["value"] for row in pipeline_counts
                                               if not row["known"]],
                "unknown_application_statuses": [row["value"] for row in application_counts
                                                  if not row["known"]],
                "counts_are_live": True,
            }

    def list_jobs(self, *, search: str | None = None, source: str | None = None,
                  pipeline_status: str | None = None, screen_state: str | None = None,
                  created_from: str | None = None, created_to: str | None = None,
                  posted_from: str | None = None, posted_to: str | None = None,
                  application_id: int | None = None, limit: int = DEFAULT_PAGE_SIZE,
                  cursor: str | None = None) -> dict[str, Any]:
        limit = _page_size(limit)
        search = _bounded_text(search, "search", MAX_SEARCH_CHARS)
        source = _bounded_text(source, "source", MAX_FILTER_CHARS)
        pipeline_status = _bounded_text(pipeline_status, "pipeline_status", MAX_FILTER_CHARS)
        screen_state = _bounded_text(screen_state, "screen_state", MAX_FILTER_CHARS)
        created_from, created_to = _iso_date(created_from, "created_from"), _iso_date(created_to, "created_to")
        posted_from, posted_to = _iso_date(posted_from, "posted_from"), _iso_date(posted_to, "posted_to")
        _check_range(created_from, created_to, "created_from", "created_to")
        _check_range(posted_from, posted_to, "posted_from", "posted_to")
        if application_id is not None:
            application_id = _positive_id(application_id, "application_id")

        filters = {"search": search, "source": source, "pipeline_status": pipeline_status,
                   "screen_state": screen_state, "created_from": created_from,
                   "created_to": created_to, "posted_from": posted_from,
                   "posted_to": posted_to, "application_id": application_id}
        scope = _filter_scope("jobs", filters)
        decoded = _cursor_decode(cursor, scope, "int")
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            pattern = _like_literal(search)
            clauses.append("(p.job_title LIKE ? ESCAPE '!' OR p.company_name LIKE ? ESCAPE '!' "
                           "OR COALESCE(p.location,'') LIKE ? ESCAPE '!')")
            params.extend((pattern, pattern, pattern))
        for column, value in (("p.source", source), ("p.pipeline_status", pipeline_status),
                              ("p.application_id", application_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if screen_state is not None:
            clauses.append("COALESCE(s.state, 'not_screened') = ?")
            params.append(screen_state)
        if created_from:
            clauses.append("substr(p.created_at, 1, 10) >= ?")
            params.append(created_from)
        if created_to:
            clauses.append("substr(p.created_at, 1, 10) <= ?")
            params.append(created_to)
        if posted_from:
            clauses.append("substr(p.posted_at, 1, 10) >= ?")
            params.append(posted_from)
        if posted_to:
            clauses.append("substr(p.posted_at, 1, 10) <= ?")
            params.append(posted_to)
        if decoded:
            clauses.append("p.id < ?")
            params.append(decoded.key)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT p.id,p.source,p.external_id,p.company_slug,p.company_name,p.job_title,"
            "p.location,p.job_url,p.score,p.pipeline_status,p.pipeline_error,p.attempts,"
            "p.notify_attempts,p.application_id,p.created_at,p.updated_at,p.posted_at,"
            "p.deprioritized_at,length(p.description) AS description_chars,"
            "s.id AS screening_id,s.state AS screening_state,s.backend AS screening_backend,"
            "s.model AS screening_model,s.effort AS screening_effort,"
            "s.last_attempted_at AS screening_last_attempted_at,"
            "s.completed_at AS screening_completed_at "
            "FROM job_postings p LEFT JOIN job_screenings s ON s.job_posting_id=p.id" + where +
            " ORDER BY p.id DESC LIMIT ?"
        )
        params.append(limit + 1)
        with self._connection() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        for row in rows:
            row["job_url"] = redact_url(row["job_url"])
            row["pipeline_error"] = redact_url(row["pipeline_error"]) if row["pipeline_error"] else None
            row["description_is_null"] = row["description_chars"] is None
        return _page(rows, limit, scope, "id", descending=True)

    def get_job(self, job_id: int) -> dict[str, Any]:
        job_id = _positive_id(job_id, "job_id")
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM job_postings WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise RecordNotFound("job was not found")
            result = _safe_full_record("job_postings", dict(row))
            screening = conn.execute(
                "SELECT * FROM job_screenings WHERE job_posting_id=?", (job_id,)
            ).fetchone()
            result["screening"] = (_safe_full_record("job_screenings", dict(screening))
                                   if screening else None)
            return result

    def get_job_description(self, job_id: int, *, offset: int = 0,
                            limit: int = TEXT_CHUNK_SIZE) -> dict[str, Any]:
        return self._get_text_chunk("job_postings", "id", _positive_id(job_id, "job_id"),
                                    "description", offset=offset, limit=limit)

    def list_applications(self, *, search: str | None = None, status: str | None = None,
                          category: str | None = None, applied_from: str | None = None,
                          applied_to: str | None = None, limit: int = DEFAULT_PAGE_SIZE,
                          cursor: str | None = None) -> dict[str, Any]:
        limit = _page_size(limit)
        search = _bounded_text(search, "search", MAX_SEARCH_CHARS)
        status = _bounded_text(status, "status", MAX_FILTER_CHARS)
        category = _bounded_text(category, "category", MAX_FILTER_CHARS)
        applied_from, applied_to = _iso_date(applied_from, "applied_from"), _iso_date(applied_to, "applied_to")
        _check_range(applied_from, applied_to, "applied_from", "applied_to")
        filters = {"search": search, "status": status, "category": category,
                   "applied_from": applied_from, "applied_to": applied_to}
        scope = _filter_scope("applications", filters)
        decoded = _cursor_decode(cursor, scope, "int")
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            pattern = _like_literal(search)
            clauses.append("(a.company_name LIKE ? ESCAPE '!' OR a.job_title LIKE ? ESCAPE '!')")
            params.extend((pattern, pattern))
        if status is not None:
            clauses.append("a.status = ?")
            params.append(status)
        if category is not None:
            clauses.append("a.category = ?")
            params.append(category)
        if applied_from:
            clauses.append("a.date_applied >= ?")
            params.append(applied_from)
        if applied_to:
            clauses.append("a.date_applied <= ?")
            params.append(applied_to)
        if decoded:
            clauses.append("a.id < ?")
            params.append(decoded.key)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT a.id,a.company_name,a.job_title,a.application_url,a.date_applied,a.category,"
            "a.status,a.last_updated,length(a.notes) AS notes_chars,a.notes IS NULL AS notes_is_null,"
            "(SELECT COUNT(*) FROM job_postings p WHERE p.application_id=a.id) AS linked_job_count "
            "FROM applications a" + where + " ORDER BY a.id DESC LIMIT ?"
        )
        params.append(limit + 1)
        with self._connection() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        for row in rows:
            row["application_url"] = redact_url(row["application_url"]) if row["application_url"] else None
        return _page(rows, limit, scope, "id", descending=True)

    def get_application(self, application_id: int) -> dict[str, Any]:
        application_id = _positive_id(application_id, "application_id")
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM applications WHERE id=?", (application_id,)).fetchone()
            if row is None:
                raise RecordNotFound("application was not found")
            result = _safe_full_record("applications", dict(row))
            if isinstance(result["application_url"], str):
                result["application_url"] = redact_url(result["application_url"])
            result["linked_job_ids"] = [item[0] for item in conn.execute(
                "SELECT id FROM job_postings WHERE application_id=? ORDER BY id ASC",
                (application_id,),
            )]
            return result

    def get_application_notes(self, application_id: int, *, offset: int = 0,
                               limit: int = TEXT_CHUNK_SIZE) -> dict[str, Any]:
        return self._get_text_chunk("applications", "id", _positive_id(application_id, "application_id"),
                                    "notes", offset=offset, limit=limit)

    def list_application_history(self, application_id: int, *, limit: int = DEFAULT_PAGE_SIZE,
                                 cursor: str | None = None) -> dict[str, Any]:
        application_id = _positive_id(application_id, "application_id")
        limit = _page_size(limit)
        scope = f"history:{application_id}"
        decoded = _cursor_decode(cursor, scope, "str", composite=True)
        with self._connection() as conn:
            if conn.execute("SELECT 1 FROM applications WHERE id=?", (application_id,)).fetchone() is None:
                raise RecordNotFound("application was not found")
            where = "application_id=?"
            params: list[Any] = [application_id]
            if decoded:
                where += " AND (timestamp > ? OR (timestamp = ? AND id > ?))"
                params.extend((decoded.key, decoded.key, int(decoded.extra or 0)))
            params.append(limit + 1)
            rows = [dict(row) for row in conn.execute(
                f"SELECT id,application_id,status,timestamp FROM status_history WHERE {where} "
                "ORDER BY timestamp ASC,id ASC LIMIT ?", params,
            ).fetchall()]
        page = _page(rows, limit, scope, "timestamp", descending=False, extra_field="id")
        return page

    def list_ats_records(self, entity: str, *, limit: int = DEFAULT_PAGE_SIZE,
                         cursor: str | None = None) -> dict[str, Any]:
        if not isinstance(entity, str):
            raise QueryInputError("entity must name one of the supported ATS records")
        spec = ENTITY_KEYS.get(entity)
        if spec is None:
            raise QueryInputError("entity must name one of the supported ATS records")
        table, key_field, key_kind = spec
        limit = _page_size(limit)
        descending = key_kind == "int"
        scope = f"records:{entity}"
        decoded = _cursor_decode(cursor, scope, key_kind)
        direction = "DESC" if descending else "ASC"
        where = ""
        params: list[Any] = []
        if decoded:
            comparator = "<" if descending else ">"
            where = f" WHERE \"{key_field}\" {comparator} ?"
            params.append(decoded.key)
        params.append(limit + 1)
        with self._connection() as conn:
            rows = [dict(row) for row in conn.execute(
                f'SELECT * FROM "{table}"{where} ORDER BY "{key_field}" {direction} LIMIT ?',
                params,
            ).fetchall()]
        return _page([_list_record(entity, row) for row in rows], limit, scope,
                     key_field, descending=descending)

    def get_ats_record(self, entity: str, key: str) -> dict[str, Any]:
        if not isinstance(entity, str):
            raise QueryInputError("entity must name one of the supported ATS records")
        spec = ENTITY_KEYS.get(entity)
        if spec is None:
            raise QueryInputError("entity must name one of the supported ATS records")
        table, key_field, key_kind = spec
        key = _bounded_text(key, "key", MAX_CURSOR_KEY_CHARS, allow_empty=False) or ""
        if key_kind == "int":
            if not _INTEGER_KEY_RE.fullmatch(key):
                raise QueryInputError("key must be a positive integer for this entity")
            lookup: int | str = int(key)
        else:
            lookup = key
        if entity == "job_postings":
            return self.get_job(int(lookup))
        if entity == "applications":
            return self.get_application(int(lookup))
        with self._connection() as conn:
            row = conn.execute(
                f'SELECT * FROM "{table}" WHERE "{key_field}"=?', (lookup,)
            ).fetchone()
            if row is None:
                raise RecordNotFound(f"{entity} record was not found")
            return _safe_full_record(entity, dict(row))

    def _get_text_chunk(self, table: str, key_field: str, key: int, field: str,
                        *, offset: int, limit: int) -> dict[str, Any]:
        key = _positive_id(key, "record id")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or offset > 2_147_483_647:
            raise QueryInputError("offset must be a nonnegative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= TEXT_CHUNK_SIZE:
            raise QueryInputError(f"limit must be between 1 and {TEXT_CHUNK_SIZE}")
        if table == "job_postings":
            tool = "get_job_description"
        elif table == "applications":
            tool = "get_application_notes"
        else:
            raise QueryInputError("text field is not available")
        with self._connection() as conn:
            row = conn.execute(
                f'SELECT "{field}" FROM "{table}" WHERE "{key_field}"=?', (key,)
            ).fetchone()
            if row is None:
                raise RecordNotFound("record was not found")
            value = row[0]
        if value is None:
            return {"text": None, "is_null": True, "total_chars": None, "offset": offset,
                    "next_offset": None, "has_more": False, "read_tool": tool}
        if offset > len(value):
            raise QueryInputError("offset is past the end of the stored text")
        chunk = value[offset:offset + limit]
        next_offset = offset + len(chunk)
        has_more = next_offset < len(value)
        return {"text": chunk, "is_null": False, "total_chars": len(value), "offset": offset,
                "next_offset": next_offset if has_more else None, "has_more": has_more,
                "read_tool": tool}
