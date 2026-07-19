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

# Realistic JD length (>= 200 chars) so a match/match seeded row clears
# get_notifiable's description-length low-context gate (mirrors the web
# LOW_CONTEXT_MAX_DESCRIPTION_LENGTH). A short default would make every notify
# test row non-notifiable — the thin-JD case the gate deliberately holds back.
LONG_DESC = "Build backend services in Python and Go across data pipelines. " * 4


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
        "description": LONG_DESC,
    }
    base.update(over)
    return base


# --- DB bootstrap + seed helpers -----------------------------------------

def bootstrap_db(path) -> str:
    """Create a fresh SQLite file from the Prisma-mirrored fixture schema."""
    boot = sqlite3.connect(path)
    boot.executescript((FIXTURES / "schema.sql").read_text())
    boot.commit()
    boot.close()
    return str(path)


def seed_new(conn, ids, *, description=None):
    over = {"description": description} if description is not None else {}
    db.upsert_postings(conn, [make_posting(i, **over) for i in ids], now=NOW)


def seed_scored(conn, scores, *, detail=None, description=None):
    """scores: dict external_id -> score. Leaves those rows in 'scored'.

    Only touches the rows it seeds (matched by external_id), so it composes with
    other seed helpers in the same db without clobbering their rows. Rows inherit
    make_posting's realistic (>=200-char) description so a match/match row is
    notifiable; pass a shorter `description` to exercise the thin-JD hold-back.
    """
    # `detail is not None` (not `detail or ...`) so a caller can pass an
    # intentionally-empty {} without silently getting the default.
    detail = detail if detail is not None else {"missing_keywords": ["aws"]}
    seed_new(conn, list(scores), description=description)
    for r in conn.execute("SELECT id, external_id FROM job_postings").fetchall():
        if r["external_id"] not in scores:
            continue
        db.save_score(conn, r["id"], score=scores[r["external_id"]],
                      score_detail=detail, now=NOW)


# --- requests-style HTTP fakes (for adapter fetch() wrappers) -------------

class FakeResponse:
    """Mimics a requests.Response: json()/text + a raise_for_status that can
    raise an injected exception (to exercise error propagation). Also exposes
    the redirect-shaped surface (`status_code`, `headers`, `is_redirect`) that
    `util.get_redirect_safe` inspects, defaulted to a plain 200 non-redirect."""

    def __init__(self, payload=None, *, text="", raise_exc=None,
                 status_code=200, headers=None, is_redirect=False):
        self._payload = payload
        self.text = text
        self._raise_exc = raise_exc
        self.status_code = status_code
        self.headers = headers or {}
        self.is_redirect = is_redirect

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._payload


class FakeSession:
    """Records get/post calls and returns configured FakeResponse(s).

    Pass `payload`/`text` for the body, or `raise_exc` to make raise_for_status
    raise, for the common one-response case. For a redirect chain, pass
    `responses` — a list of FakeResponse to return in order, one per call
    (get_redirect_safe re-validates and re-requests per hop). Inspect `.calls`
    (list of (METHOD, url, kwargs)) to assert URL/params, e.g. to prove an
    unsafe redirect target was never requested.
    """

    def __init__(self, payload=None, *, text="", raise_exc=None, responses=None):
        self._payload = payload
        self._text = text
        self._raise_exc = raise_exc
        self._responses = list(responses) if responses is not None else None
        self.calls = []

    def _resp(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        if self._responses is not None:
            return self._responses.pop(0)
        return FakeResponse(self._payload, text=self._text, raise_exc=self._raise_exc)

    def get(self, url, **kwargs):
        return self._resp("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._resp("POST", url, kwargs)
