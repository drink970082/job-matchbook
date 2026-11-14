"""Injected P3 prototype: append-only state history, no DDL/HTTP/runtime wiring.

Freshness is relative to the latest explicitly captured source/policy event, not a
claim about the mutable production job table or current source availability.
"""
from __future__ import annotations

import base64
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, time, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from ats_worker.ranking.native import jev_question_set_from_value, validate_jev_response

SOURCE_FIELDS = {"schema", "job_id", "company", "title", "location", "description", "source_url", "publication_time", "captured_time", "source_revision"}
POLICY_FIELDS = {"profile_sha256", "question_context_domain_sha256", "question_set", "rubric_version", "projection_version", "adapter_version", "requested_model", "resolved_model"}
BASIS = "latest explicitly captured prototype source/policy; not live source availability"
RECORDED_NATIVE_REQUESTED_MODEL = "typesafe/jev-1.13"
RECORDED_NATIVE_RESOLVED_MODEL = "typesafe/jev-1.13-20260917"
RECORDED_NATIVE_ADAPTER = "recorded-native-replay-v1"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _instant(value, path, *, allow_date=False, require_utc=False):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"invalid {path}")
    try:
        if allow_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.combine(date.fromisoformat(value), time.min, tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise ValueError(f"invalid {path}") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"invalid {path}")
    if require_utc and parsed.utcoffset().total_seconds() != 0:
        raise ValueError(f"{path} must be UTC")
    return parsed.astimezone(timezone.utc)


def _assessment_origin(policy, *, allow_native_replay):
    requested = policy.get("requested_model")
    resolved = policy.get("resolved_model")
    if requested.startswith("fake-") and resolved.startswith("fake-"):
        return "fake"
    if (
        allow_native_replay
        and requested == RECORDED_NATIVE_REQUESTED_MODEL
        and resolved == RECORDED_NATIVE_RESOLVED_MODEL
        and policy.get("adapter_version") == RECORDED_NATIVE_ADAPTER
    ):
        return "recorded_native"
    raise ValueError("prototype accepts fake models only unless recorded native replay is enabled")


def binding(source, policy, *, allow_native_replay=False):
    if not isinstance(source, dict) or set(source) != SOURCE_FIELDS or source["schema"] != "ranking-source-v1":
        raise ValueError("invalid source snapshot")
    if type(source["job_id"]) is not int or source["job_id"] <= 0:
        raise ValueError("invalid job identity")
    for field in ("company", "title", "description", "source_url", "captured_time"):
        if not isinstance(source[field], str) or not source[field].strip():
            raise ValueError("incomplete source snapshot")
    if not isinstance(source["location"], str):
        raise ValueError("invalid source fields")
    revision = source["source_revision"]
    if type(revision) is int:
        if revision <= 0:
            raise ValueError("invalid source revision")
    elif not isinstance(revision, str) or not revision or revision.strip() != revision:
        raise ValueError("invalid source revision")
    _instant(source["captured_time"], "captured time", require_utc=True)
    if source["publication_time"] is not None:
        _instant(source["publication_time"], "publication time", allow_date=True)
    if not isinstance(policy, dict) or set(policy) != POLICY_FIELDS:
        raise ValueError("invalid ranking policy")
    for key in ("profile_sha256", "question_context_domain_sha256"):
        if not isinstance(policy[key], str) or not re.fullmatch(r"[0-9a-f]{64}", policy[key]):
            raise ValueError("invalid policy hash")
    if any(not isinstance(policy[k], str) or not policy[k] for k in POLICY_FIELDS - {"question_set", "profile_sha256", "question_context_domain_sha256"}):
        raise ValueError("unresolved model or policy version")
    origin = _assessment_origin(policy, allow_native_replay=allow_native_replay)
    questions = jev_question_set_from_value(policy["question_set"])
    if [q.id for q in questions.questions] != ["domain", "preference", "relevance", "ambiguity"]:
        raise ValueError("four ranking questions required in canonical order")
    if any(q.question_type != "choice" for q in questions.questions):
        raise ValueError("ranking requires native choices")
    if policy["projection_version"] != "ranking-projection-v1":
        raise ValueError("unsupported projection")
    result = {k: policy[k] for k in POLICY_FIELDS - {"question_set"}}
    result.update(job_id=source["job_id"], source_sha256=digest(source), question_set_sha256=questions.sha256)
    return result, questions


def _fresh(state):
    success = state["latest_success"]
    return "absent" if success is None else ("current" if success["binding_sha256"] == state["binding_sha256"] else "stale")


def _summary(state):
    result = state["latest_success"]
    assessment_origin = result["assessment_origin"] if result else state["assessment_origin"]
    return {"job_id": state["source"]["job_id"], "company": state["source"]["company"], "title": state["source"]["title"],
            "publication_time": state["source"]["publication_time"], "domain": result["domain"] if result else "unknown",
            "priority": result["priority"] if result else None, "needs_review": result["needs_review"] if result else True,
            "freshness": _fresh(state), "attempt_state": state["latest_attempt"]["state"],
            "assessment_origin": assessment_origin,
            "source_assessment_origin": state["assessment_origin"],
            "fake_provider": assessment_origin == "fake", "prototype": True}


class RankingStore:
    """Single-job prototype writer. Caller injects an isolated, schema-ready connection."""
    def __init__(self, connection, *, allow_native_replay=False):
        self.connection = connection
        if type(allow_native_replay) is not bool:
            raise ValueError("allow_native_replay must be a boolean")
        self.allow_native_replay = allow_native_replay

    def _latest(self, job_id):
        row = self.connection.execute("SELECT state_json FROM job_ranking_events WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def _append(self, state):
        with self.connection:
            row = self.connection.execute("INSERT INTO job_ranking_events(job_id,state_json) VALUES(?,?)", (state["source"]["job_id"], canonical(state)))
            return row.lastrowid

    def capture(self, source, policy, *, now):
        bound, _ = binding(source, policy, allow_native_replay=self.allow_native_replay)
        origin = _assessment_origin(policy, allow_native_replay=self.allow_native_replay)
        identity = digest({"schema": "ranking-binding-v1", **bound})
        previous = self._latest(source["job_id"])
        if previous and previous["binding_sha256"] == identity:
            return previous
        state = {"source": json.loads(canonical(source)), "assessment_origin": origin,
                 "binding": bound, "binding_sha256": identity,
                 "latest_success": previous["latest_success"] if previous else None,
                 "latest_attempt": {"id": None, "state": "pending", "at": now,
                                    "reason": None, "assessment_origin": origin}}
        self._append(state)
        return state

    def assess(self, source, policy, *, provider, now):
        state = self.capture(source, policy, now=now)
        if _fresh(state) == "current":
            return {"cache_hit": True, **_summary(state)}
        _, questions = binding(source, policy, allow_native_replay=self.allow_native_replay)
        origin = _assessment_origin(policy, allow_native_replay=self.allow_native_replay)
        state["latest_attempt"] = {"id": uuid4().hex, "state": "running", "at": now,
                                    "reason": None, "assessment_origin": origin}
        self._append(state)
        expected_model = state["binding"]["resolved_model"]
        invocation = {"job_id": state["source"]["job_id"], "source_sha256": state["binding"]["source_sha256"],
                      "binding_sha256": state["binding_sha256"], "question_set": questions.as_dict(),
                      "resolved_model": expected_model, "attempt_id": state["latest_attempt"]["id"]}
        expected_envelope = {key: invocation[key] for key in ("job_id", "source_sha256", "binding_sha256", "attempt_id")}
        try:
            reply = provider(deepcopy(invocation))
            if not isinstance(reply, dict) or set(reply) != {"job_id", "source_sha256", "binding_sha256", "attempt_id", "response"}:
                raise ValueError("invalid response envelope")
            if type(reply["job_id"]) is not int or reply["job_id"] <= 0 or any(
                not isinstance(reply[key], str) or not reply[key]
                for key in ("source_sha256", "binding_sha256", "attempt_id")
            ):
                raise ValueError("invalid response identity types")
            if any(reply[k] != expected_envelope[k] for k in expected_envelope):
                raise ValueError("response binding mismatch")
            response = validate_jev_response(reply["response"], questions, expected_model=expected_model)
            values = {a.question_id: a.value for a in response.answers}
            if values["preference"] not in {"strong", "plausible", "weak", "unknown"} or values["relevance"] not in {"supported", "partial", "absent", "unknown"} or values["ambiguity"] not in {"clear", "review"}:
                raise ValueError("invalid rubric choice")
            priority = (None if values["preference"] == "unknown" else "low" if values["preference"] == "weak" else "high" if values["preference"] == "strong" and values["relevance"] == "supported" else "medium")
            reasons = []
            for yes, code in ((values["domain"] in {"mixed", "unknown"}, "domain_" + values["domain"]), (values["ambiguity"] == "review", "duties_or_signals_unclear"), (values["preference"] == "unknown", "preference_unknown"), (values["relevance"] == "absent", "background_evidence_absent"), (values["relevance"] == "unknown", "background_interpretation_unknown")):
                if yes: reasons.append(code)
            diagnostics = {}
            for answer in response.answers:
                diagnostic = {"type": answer.question_type, "value": answer.value}
                if answer.legend:
                    diagnostic["legend"] = dict(answer.legend)
                if answer.probabilities:
                    diagnostic["probabilities"] = dict(answer.probabilities)
                if answer.confidence is not None:
                    diagnostic["confidence"] = answer.confidence
                diagnostics[answer.question_id] = diagnostic
            state["latest_success"] = {"binding_sha256": state["binding_sha256"], "source_sha256": state["binding"]["source_sha256"],
                                       "binding": state["binding"], "domain": values["domain"], "priority": priority,
                                       "needs_review": bool(reasons), "reason_codes": sorted(reasons), "native_values": values,
                                       "native_diagnostics": diagnostics, "response_sha256": digest(reply["response"]),
                                       "source_captured_time": state["source"]["captured_time"],
                                       "source_revision": state["source"]["source_revision"],
                                       "completed_at": now, "assessment_origin": origin,
                                       "completed_at_basis": "replay_ingestion" if origin == "recorded_native" else "fake_assessment",
                                       "fake_provider": origin == "fake", "prototype": True}
            state["latest_attempt"].update(state="succeeded", reason=None)
        except Exception as exc:
            state["latest_attempt"].update(state="failed", reason="delivery_unknown" if isinstance(exc, TimeoutError) else "invalid_or_failed_provider")
        # Atomic success+attempt settlement: one immutable full-state event.
        self._append(state)
        return {"cache_hit": False, **_summary(state)}


class RankingReader:
    """Closed read-only prototype inventory, reconstructed at a committed watermark."""
    def __init__(self, path):
        self.path = str(Path(path).resolve())

    def _states(self, watermark=None):
        with sqlite3.connect(Path(self.path).as_uri() + "?mode=ro", uri=True) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            latest = conn.execute("SELECT COALESCE(MAX(id),0) FROM job_ranking_events").fetchone()[0]
            if watermark is None: watermark = latest
            if type(watermark) is not int or not 0 <= watermark <= latest:
                raise ValueError("invalid ranking watermark")
            rows = conn.execute("SELECT e.state_json FROM job_ranking_events e JOIN (SELECT job_id,MAX(id) AS id FROM job_ranking_events WHERE id<=? GROUP BY job_id) x ON e.id=x.id", (watermark,)).fetchall()
            return watermark, [json.loads(r[0]) for r in rows]

    def coverage(self, watermark=None):
        watermark, states = self._states(watermark)
        freshness = Counter(_fresh(s) for s in states)
        attempts = Counter(s["latest_attempt"]["state"] for s in states)
        origins = Counter(
            s["latest_success"]["assessment_origin"]
            if s.get("latest_success") else s.get("assessment_origin", "fake")
            for s in states
        )
        source_origins = Counter(s.get("assessment_origin", "fake") for s in states)
        assessment_origin = next(iter(origins)) if len(origins) == 1 else ("mixed" if origins else None)
        source_assessment_origin = next(iter(source_origins)) if len(source_origins) == 1 else ("mixed" if source_origins else None)
        return {"watermark": watermark, "scope": "explicitly captured prototype inventory", "freshness_basis": BASIS,
                "total": len(states), "freshness": {k: freshness[k] for k in ("current", "stale", "absent")},
                "latest_attempt": {k: attempts[k] for k in ("pending", "running", "succeeded", "failed", "deferred", "none")},
                "current_unknown": sum(_fresh(s) == "current" and s["latest_success"]["priority"] is None for s in states),
                "assessment_origin": assessment_origin,
                "assessment_origin_counts": {k: origins[k] for k in ("fake", "recorded_native")},
                "source_assessment_origin": source_assessment_origin,
                "source_assessment_origin_counts": {k: source_origins[k] for k in ("fake", "recorded_native")},
                "prototype": True, "fake_provider": bool(states) and set(origins) == {"fake"}}

    def list_rankings(self, *, domain=None, priority=None, needs_review=None, freshness="current", lane="ranked", limit=20, cursor=None):
        if domain is not None and (not isinstance(domain, str) or len(domain) > 64): raise ValueError("invalid domain")
        if priority not in (None, "high", "medium", "low"): raise ValueError("invalid priority")
        if needs_review is not None and type(needs_review) is not bool: raise ValueError("invalid review filter")
        if freshness not in ("current", "stale", "absent", "all") or lane not in ("ranked", "unknown", "raw"): raise ValueError("invalid ranking filter")
        if type(limit) is not int or not 1 <= limit <= 100: raise ValueError("invalid page size")
        # Raw inventory must not require a successful/current result.
        if lane == "raw" and freshness == "current": freshness = "all"
        filters = {"domain": domain, "priority": priority, "needs_review": needs_review, "freshness": freshness, "lane": lane}
        token = None
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or len(cursor) > 4096: raise ValueError()
                token = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if set(token) != {"version", "watermark", "filters", "last"} or token["version"] != 1 or token["filters"] != digest(filters): raise ValueError()
            except Exception:
                raise ValueError("invalid or mismatched ranking cursor") from None
        watermark, states = self._states(token["watermark"] if token else None)
        rows = [_summary(s) for s in states]
        rows = [r for r in rows if (freshness == "all" or r["freshness"] == freshness) and (domain is None or r["domain"] == domain) and (priority is None or r["priority"] == priority) and (needs_review is None or r["needs_review"] == needs_review) and (lane == "raw" or (r["priority"] is None if lane == "unknown" else r["priority"] is not None))]
        # Stable instant-descending order, with null publication times last.
        rows.sort(key=lambda r: r["job_id"])
        rows.sort(
            key=lambda r: (
                r["publication_time"] is not None,
                _instant(r["publication_time"], "publication time", allow_date=True)
                if r["publication_time"] is not None
                else datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        rows.sort(key=lambda r: {"high": 0, "medium": 1, "low": 2, None: 3}[r["priority"]])
        eligible = len(rows)
        if token:
            ids = [r["job_id"] for r in rows]
            if type(token["last"]) is not int or token["last"] not in ids: raise ValueError("invalid ranking cursor position")
            rows = rows[ids.index(token["last"]) + 1:]
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            next_cursor = base64.urlsafe_b64encode(canonical({"version": 1, "watermark": watermark, "filters": digest(filters), "last": page[-1]["job_id"]}).encode()).decode()
        page_origins = Counter(r["assessment_origin"] for r in page)
        assessment_origin = next(iter(page_origins)) if len(page_origins) == 1 else ("mixed" if page_origins else None)
        return {"items": page, "next_cursor": next_cursor, "watermark": watermark, "snapshot": True,
                "eligible_count": eligible, "returned_count": len(page), "scope": "explicitly captured prototype inventory",
                "freshness_basis": BASIS, "assessment_origin": assessment_origin,
                "prototype": True, "fake_provider": bool(page) and all(r["fake_provider"] for r in page)}

    def get_ranking(self, job_id, watermark=None):
        if type(job_id) is not int or job_id <= 0: raise ValueError("invalid job identity")
        watermark, states = self._states(watermark)
        state = next((s for s in states if s["source"]["job_id"] == job_id), None)
        if state is None: return None
        source_snapshot = state["source"]
        source_origin = state.get("assessment_origin", "fake")
        result_origin = state["latest_success"]["assessment_origin"] if state["latest_success"] else source_origin
        return {"job_id": job_id, "source_snapshot": source_snapshot, "ranking": state["latest_success"],
                "latest_attempt": state["latest_attempt"], "freshness": _fresh(state), "watermark": watermark,
                "source_snapshot_sha256": state["binding"]["source_sha256"],
                "source_assessment_origin": source_origin,
                "assessment_origin": result_origin, "freshness_basis": BASIS,
                "prototype": True, "fake_provider": result_origin == "fake"}


def fake_reply(invocation, tier="high"):
    """Mechanical scenario generator, not a semantic predictor or real model."""
    questions = jev_question_set_from_value(invocation["question_set"])
    domain = next(k for k, _ in questions.questions[0].choice_criteria if k not in {"mixed", "unknown"})
    values = {"domain": domain, "preference": {"high": "strong", "medium": "plausible", "low": "weak", None: "unknown"}[tier], "relevance": "supported", "ambiguity": "review" if tier is None else "clear"}
    answers = {q.id: {"type": "choice", "choice": values[q.id], "probabilities": {k: int(k == values[q.id]) for k, _ in q.choice_criteria}, "confidence": 1} for q in questions.questions}
    return {k: invocation[k] for k in ("job_id", "source_sha256", "binding_sha256", "attempt_id")} | {"response": {"model": invocation["resolved_model"], "answers": answers}}
