"""Phenom adapter: map search positions + two-step description hydration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from ats_worker.fetch import phenom
from ats_worker.util import POSTING_FIELDS

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIXTURES / "phenom_search.json").read_text())
DETAIL = json.loads((FIXTURES / "phenom_detail.json").read_text())
SLUG = "apply.careers.microsoft.com/microsoft.com"


class _Resp:
    def __init__(self, data, *, raise_exc=None):
        self._data = data
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    def json(self):
        return self._data


class _FakeSession:
    """Search returns the fixture page for start=0, an empty page afterwards; each
    position_details GET returns the detail fixture. `bad_ids` makes that detail
    GET raise (failure isolation)."""

    def __init__(self, *, bad_ids=()):
        self._bad = {str(i) for i in bad_ids}
        self.gets: list[tuple] = []

    def get(self, url, params=None, timeout=None):
        self.gets.append((url, params))
        params = params or {}
        if url.endswith("/search"):
            if params.get("start", 0) == 0:
                return _Resp(SEARCH)
            return _Resp({"status": 200, "data": {"count": SEARCH["data"]["count"], "positions": []}})
        pid = str(params.get("position_id"))
        if pid in self._bad:
            return _Resp(None, raise_exc=requests.HTTPError("boom"))
        return _Resp(DETAIL)


def test_parse_position_maps_canonical_fields():
    pos = SEARCH["data"]["positions"][0]
    p = phenom.parse_position(pos, "Microsoft", DETAIL["data"]["jobDescription"])
    assert set(p) == set(POSTING_FIELDS)
    assert p["source"] == "phenom"
    assert p["external_id"] == str(pos["id"])
    assert p["job_title"] == pos["name"].strip()
    assert p["location"] == ", ".join(pos["locations"])
    assert p["posted_at"] and p["posted_at"].startswith("20")  # epoch-seconds -> ISO
    assert "microsoft" in p["description"].lower()


def test_parse_position_without_description():
    pos = SEARCH["data"]["positions"][0]
    assert phenom.parse_position(pos, "Microsoft")["description"] == ""


def test_require_ok_rejects_bad_tenant():
    with pytest.raises(ValueError):
        phenom._require_ok({"status": 500, "data": None})
    with pytest.raises(ValueError):
        phenom._require_ok({"status": 200, "data": None})


def test_bad_slug_raises():
    with pytest.raises(ValueError):
        phenom.fetch("no-domain", "X", session=_FakeSession())


@pytest.mark.parametrize("slug", [
    "127.0.0.1/microsoft.com",      # loopback
    "169.254.169.254/x",            # cloud metadata
    "10.0.0.5/x",                   # private
    "2130706433/x",                 # decimal-notation loopback
])
def test_internal_host_slug_rejected(slug):
    # The slug's first segment IS the request host and the charset check can't tell
    # a public hostname from an internal IP literal — so the host itself is guarded.
    with pytest.raises(ValueError):
        phenom.fetch(slug, "X", session=_FakeSession())


def test_fetch_two_step_hydrates_and_paginates():
    sess = _FakeSession()
    out = phenom.fetch(SLUG, "Microsoft", session=sess, timeout=20)
    assert len(out) == 2
    assert all(o["description"] for o in out)          # each hydrated from detail
    search_starts = [(p or {}).get("start") for u, p in sess.gets if u.endswith("/search")]
    assert search_starts == [0, 2]                     # advance by rows, then empty page
    detail_pids = [(p or {}).get("position_id") for u, p in sess.gets if u.endswith("/position_details")]
    assert len(detail_pids) == 2
    assert all("apply.careers.microsoft.com" in u for u, _ in sess.gets)
    assert all((p or {}).get("domain") == "microsoft.com" for _, p in sess.gets)


def test_fetch_keeps_posting_when_detail_fails():
    pid0 = str(SEARCH["data"]["positions"][0]["id"])
    out = phenom.fetch(SLUG, "Microsoft", session=_FakeSession(bad_ids=[pid0]))
    assert len(out) == 2                               # not dropped despite failed detail
    kept = next(o for o in out if o["external_id"] == pid0)
    assert kept["description"] == ""


def test_fetch_propagates_search_http_error():
    class _BoomSession:
        def get(self, url, **kw):
            return _Resp(None, raise_exc=requests.HTTPError("500"))

    with pytest.raises(requests.HTTPError):
        phenom.fetch(SLUG, "Microsoft", session=_BoomSession())


# --- stub-gate: skip the detail GET for postings the gates already reject ----

_GATE_SEARCH = {"status": 200, "data": {"count": 3, "positions": [
    {"id": 11, "name": "Sales Manager", "locations": ["United States, Washington, Redmond"],
     "postedTs": 1784386514, "positionUrl": "/careers/job/11"},
    {"id": 22, "name": "Software Engineer II", "locations": ["India, Telangana, Hyderabad"],
     "postedTs": 1784386514, "positionUrl": "/careers/job/22"},
    {"id": 33, "name": "Software Engineer, AI", "locations": ["United States, Washington, Redmond"],
     "postedTs": 1784386514, "positionUrl": "/careers/job/33"},
]}}


class _GateSession:
    """Serves _GATE_SEARCH on the first page, an empty page after, and the detail
    fixture for any position. Records every detail position_id it is asked for."""

    def __init__(self):
        self.detail_ids: list[str] = []

    def get(self, url, params=None, timeout=None):
        params = params or {}
        if url.endswith("/search"):
            if params.get("start", 0) == 0:
                return _Resp(_GATE_SEARCH)
            return _Resp({"status": 200, "data": {"count": 3, "positions": []}})
        self.detail_ids.append(str(params.get("position_id")))
        return _Resp(DETAIL)


def _gate(stub):
    """Title miss -> drop; India on-site -> discard; otherwise hydrate."""
    if "engineer" not in (stub["job_title"] or "").lower():
        return "drop"
    if "India" in (stub["location"] or ""):
        return "discard"
    return "hydrate"


def test_stub_gate_hydrates_only_the_survivor():
    sess = _GateSession()
    out = phenom.fetch(SLUG, "Microsoft", session=sess, keep=_gate)

    assert sess.detail_ids == ["33"]                       # exactly ONE detail GET
    assert sorted(o["external_id"] for o in out) == ["22", "33"]
    dropped = [o for o in out if o["external_id"] == "11"]
    assert dropped == []                                   # title miss never returned
    discarded = next(o for o in out if o["external_id"] == "22")
    assert discarded["description"] == ""                  # stored, never hydrated
    assert discarded["job_title"] == "Software Engineer II"
    assert discarded["location"] == "India, Telangana, Hyderabad"
    hydrated = next(o for o in out if o["external_id"] == "33")
    assert hydrated["description"]                          # JD fetched


def test_stub_gate_row_ids_match_the_hydrated_ids():
    # A stub row and a hydrated row for the same position must carry the same
    # (source, external_id) dedup key, or a later pass double-inserts.
    ungated = phenom.fetch(SLUG, "Microsoft", session=_GateSession())
    gated = phenom.fetch(SLUG, "Microsoft", session=_GateSession(), keep=_gate)
    ungated_by_id = {o["external_id"]: o for o in ungated}
    for row in gated:
        assert row["external_id"] in ungated_by_id
        assert row["job_title"] == ungated_by_id[row["external_id"]]["job_title"]


def test_stub_gate_fails_open_on_an_unknown_verdict():
    sess = _GateSession()
    out = phenom.fetch(SLUG, "Microsoft", session=sess, keep=lambda stub: "nonsense")
    assert len(out) == 3                       # nothing lost
    assert sorted(sess.detail_ids) == ["11", "22", "33"]   # all hydrated


def test_no_keep_is_todays_behavior():
    sess = _GateSession()
    out = phenom.fetch(SLUG, "Microsoft", session=sess)
    assert len(out) == 3
    assert sorted(sess.detail_ids) == ["11", "22", "33"]
    assert all(o["description"] for o in out)
