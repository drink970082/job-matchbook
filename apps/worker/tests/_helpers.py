"""Shared test utilities: posting builder, DB seed helpers, and HTTP fakes.

Consolidates the near-identical builders/fakes that were copy-pasted across
test_db.py, test_pipeline.py, and the fetch tests so unit + integration tiers
share one source of truth.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ats_worker import db

NOW = "2026-06-04T08:00:00.000Z"
LATER = "2026-06-04T09:00:00.000Z"

FIXTURES = Path(__file__).parent / "fixtures"


# --- posting builder ------------------------------------------------------

def make_posting(external_id="1", source="greenhouse", **over):
    """A canonical posting dict (the adapter contract shape), override-able."""
    base = {
        "source": source,
        "external_id": external_id,
        "company_name": "Acme",
        "job_title": "Software Engineer",
        "location": "Remote",
        "job_url": f"https://example.com/jobs/{external_id}",
        "description": "Build things with Python.",
    }
    base.update(over)
    return base


# --- DB bootstrap + seed helpers -----------------------------------------

def schema_sql() -> str:
    return (FIXTURES / "schema.sql").read_text()


def bootstrap_db(path) -> str:
    """Create a fresh SQLite file from the Prisma-mirrored fixture schema."""
    boot = sqlite3.connect(path)
    boot.executescript(schema_sql())
    boot.commit()
    boot.close()
    return str(path)


def seed_new(conn, ids):
    db.upsert_postings(conn, [make_posting(i) for i in ids], now=NOW)


def seed_scored(conn, scores, *, detail=None):
    """scores: dict external_id -> score. Leaves those rows in 'scored'.

    Only touches the rows it seeds (matched by external_id), so it composes with
    other seed helpers in the same db without clobbering their rows.
    """
    # `detail is not None` (not `detail or ...`) so a caller can pass an
    # intentionally-empty {} without silently getting the default.
    detail = detail if detail is not None else {"missing_keywords": ["aws"]}
    seed_new(conn, list(scores))
    for r in conn.execute("SELECT id, external_id FROM job_postings").fetchall():
        if r["external_id"] not in scores:
            continue
        db.save_score(conn, r["id"], score=scores[r["external_id"]],
                      score_detail=detail, now=NOW)


def seed_tailored(conn, ids):
    ids = set(ids)
    seed_scored(conn, {i: 90 for i in ids})
    for r in conn.execute("SELECT id, external_id FROM job_postings").fetchall():
        if r["external_id"] not in ids:
            continue
        db.save_resume(conn, r["id"], resume_tex="T",
                       resume_path=f"resumes/{r['id']}.pdf", resume_pages=1, now=NOW)


# --- requests-style HTTP fakes (for adapter fetch() wrappers) -------------

class FakeResponse:
    """Mimics a requests.Response: json()/text + a raise_for_status that can
    raise an injected exception (to exercise error propagation)."""

    def __init__(self, payload=None, *, text="", raise_exc=None):
        self._payload = payload
        self.text = text
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._payload


class FakeSession:
    """Records get/post calls and returns one configured FakeResponse.

    Pass `payload`/`text` for the body, or `raise_exc` to make raise_for_status
    raise. Inspect `.calls` (list of (METHOD, url, kwargs)) to assert URL/params.
    """

    def __init__(self, payload=None, *, text="", raise_exc=None):
        self._payload = payload
        self._text = text
        self._raise_exc = raise_exc
        self.calls = []

    def _resp(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(self._payload, text=self._text, raise_exc=self._raise_exc)

    def get(self, url, **kwargs):
        return self._resp("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._resp("POST", url, kwargs)
