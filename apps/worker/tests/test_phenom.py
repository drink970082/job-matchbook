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
    """Mimics requests' contract: raise_for_status() raises for a >=400 status_code
    (with the response attached), and headers are readable off the response."""

    def __init__(self, data, *, raise_exc=None, status_code=None, headers=None):
        self._data = data
        self._raise_exc = raise_exc
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc
        if self.status_code is not None and self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

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


# --- job_url must be absolute: a discarded (un-hydrated) row's compensating -----
# --- control ("it still has a clickable link") only works if the link resolves. -

def test_fetch_builds_absolute_job_url_from_slug_host():
    # Every position in phenom_search.json carries only a relative positionUrl
    # ("/careers/job/<id>") — no publicUrl. Absolutized against the slug's host.
    sess = _FakeSession()
    out = phenom.fetch(SLUG, "Microsoft", session=sess)
    assert len(out) == 2
    for o in out:
        assert o["job_url"].startswith("https://apply.careers.microsoft.com/")


def test_fetch_keeps_an_already_absolute_public_url_unchanged():
    class _AbsSession:
        def get(self, url, params=None, timeout=None):
            params = params or {}
            if url.endswith("/search"):
                if params.get("start", 0) == 0:
                    return _Resp({"status": 200, "data": {"count": 1, "positions": [
                        {"id": 99, "name": "Some Role", "locations": ["Remote"],
                         "postedTs": 1784386514,
                         "publicUrl": "https://careers.microsoft.com/us/en/job/99"},
                    ]}})
                return _Resp({"status": 200, "data": {"count": 1, "positions": []}})
            return _Resp(DETAIL)

    out = phenom.fetch(SLUG, "Microsoft", session=_AbsSession())
    assert len(out) == 1
    assert out[0]["job_url"] == "https://careers.microsoft.com/us/en/job/99"


# --- stub-gate against the REAL captured fixture (19-digit ids, positionUrl- -----
# --- only, standardizedLocations, workLocationOption) — not the hand-written --
# --- synthetic _GATE_SEARCH payload above. -------------------------------------

# --- HTTP 429 mid-pagination: retry, then salvage the pages already collected ---
# The 2026-07-22 watchlist pass lost careers.qualcomm.com entirely to a 429 at
# start=930: the search raised, the exception unwound the whole page loop, and the
# board yielded NOTHING instead of the ~93 pages it had already walked.

_PAGE1 = {"status": 200, "data": {"count": SEARCH["data"]["count"], "positions": [
    {"id": 4242, "name": "Second Page Role", "locations": ["United States, Remote"],
     "postedTs": 1784386514, "positionUrl": "/careers/job/4242"},
]}}


class _ThrottledSearchSession:
    """Search: start=0 serves the fixture page (2 positions); the NEXT page answers
    429 `throttles` times before serving _PAGE1 and then an empty page. Details
    always succeed. Records every search `start` asked for, in order."""

    def __init__(self, *, throttles, retry_after=None, throttle_first_page=False,
                 status=429):
        self._throttles = throttles
        self._retry_after = retry_after
        self._throttle_first = throttle_first_page
        self._status = status
        self.rate_limited = 0        # throttle responses served
        self.starts: list[int] = []  # every search start requested, in order

    def _throttle(self):
        self.rate_limited += 1
        headers = {} if self._retry_after is None else {"Retry-After": self._retry_after}
        return _Resp(None, status_code=self._status, headers=headers)

    def get(self, url, params=None, timeout=None):
        params = params or {}
        if not url.endswith("/search"):
            return _Resp(DETAIL)
        start = params.get("start", 0)
        self.starts.append(start)
        if self.rate_limited < self._throttles and (start > 0 or self._throttle_first):
            return self._throttle()
        if start == 0:
            return _Resp(SEARCH)
        if start == 2:
            return _Resp(_PAGE1)
        return _Resp({"status": 200, "data": {"count": SEARCH["data"]["count"], "positions": []}})


def test_search_429_is_retried_and_pagination_resumes():
    waits: list[float] = []
    sess = _ThrottledSearchSession(throttles=1)
    out = phenom.fetch(SLUG, "Microsoft", session=sess, sleep=waits.append)

    assert len(out) == 3                      # 2 from page 0 + 1 from the retried page
    assert sess.starts == [0, 2, 2, 3]        # the 429'd page is re-requested, not skipped
    assert waits == [phenom.RETRY_BASE_WAIT]  # backed off exactly once


def test_persistent_429_mid_pagination_keeps_the_pages_already_collected():
    waits: list[float] = []
    sess = _ThrottledSearchSession(throttles=99)
    out = phenom.fetch(SLUG, "Microsoft", session=sess, sleep=waits.append)

    assert len(out) == 2                                    # page 0 survives; board not lost
    assert all(o["description"] for o in out)               # and is fully hydrated
    assert sess.rate_limited == phenom.RETRY_ATTEMPTS + 1   # bounded: one try + N retries
    assert len(waits) == phenom.RETRY_ATTEMPTS              # then it gives up, no hang
    assert all(w <= phenom.RETRY_MAX_WAIT for w in waits)


def test_retry_after_header_is_honored_over_the_default_backoff():
    waits: list[float] = []
    sess = _ThrottledSearchSession(throttles=1, retry_after="7")
    out = phenom.fetch(SLUG, "Microsoft", session=sess, sleep=waits.append)

    assert waits == [7.0]
    assert len(out) == 3


@pytest.mark.parametrize("header", ["3600", "Fri, 24 Jul 2026 00:00:00 GMT", "", "-5"])
def test_unusable_or_absurd_retry_after_falls_back_to_the_capped_backoff(header):
    # A board must not be able to stall the SERIAL fetch loop with a huge or
    # unparseable Retry-After: honor it only as a sane delta-seconds value.
    waits: list[float] = []
    sess = _ThrottledSearchSession(throttles=1, retry_after=header)
    phenom.fetch(SLUG, "Microsoft", session=sess, sleep=waits.append)

    assert len(waits) == 1
    assert 0 < waits[0] <= phenom.RETRY_MAX_WAIT


def test_persistent_429_on_the_very_first_page_raises_and_terminates():
    # Nothing collected yet, so there is nothing to salvage: fail loudly (the
    # pipeline's per-company try/except isolates it) rather than report an empty
    # board. Still bounded - it must not retry forever.
    waits: list[float] = []
    sess = _ThrottledSearchSession(throttles=99, throttle_first_page=True)
    with pytest.raises(requests.HTTPError):
        phenom.fetch(SLUG, "Microsoft", session=sess, sleep=waits.append)

    assert sess.rate_limited == phenom.RETRY_ATTEMPTS + 1
    assert len(waits) == phenom.RETRY_ATTEMPTS


# --- HTTP 403 mid-pagination: the SAME throttle, wearing a different status code ---
# `careers.qualcomm.com` fails every live pass with a 403 deep in pagination, at a
# VARYING offset (start=990 / 1060 / 1220), so the board is lost six times a day.
# Probed cold on 2026-07-31, those exact offsets return 200 — so it is not the offset
# and not a missing page; it is a WAF tripping on the pass's cumulative request volume.

def test_search_403_mid_pagination_is_retried_like_a_429():
    waits: list[float] = []
    sess = _ThrottledSearchSession(throttles=1, status=403)
    out = phenom.fetch(SLUG, "Microsoft", session=sess, sleep=waits.append)

    assert len(out) == 3
    assert sess.starts == [0, 2, 2, 3]        # re-requested, not skipped
    assert waits == [phenom.RETRY_BASE_WAIT]


def test_persistent_403_mid_pagination_keeps_the_pages_already_collected():
    # The whole point: before this, a 403 raised and the board yielded NOTHING.
    waits: list[float] = []
    sess = _ThrottledSearchSession(throttles=99, status=403)
    out = phenom.fetch(SLUG, "Microsoft", session=sess, sleep=waits.append)

    assert len(out) == 2                                    # page 0 survives
    assert sess.rate_limited == phenom.RETRY_ATTEMPTS + 1   # bounded
    assert len(waits) == phenom.RETRY_ATTEMPTS


def test_a_403_on_the_first_page_still_raises():
    # Nothing to salvage, and a board that refuses from the very first request is a
    # block, not a throttle — it must not be reported as an empty board.
    waits: list[float] = []
    sess = _ThrottledSearchSession(throttles=99, throttle_first_page=True, status=403)
    with pytest.raises(requests.HTTPError):
        phenom.fetch(SLUG, "Microsoft", session=sess, sleep=waits.append)


def test_non_429_search_error_is_not_retried():
    class _ServerErrorSession:
        def __init__(self):
            self.calls = 0

        def get(self, url, params=None, timeout=None):
            self.calls += 1
            return _Resp(None, status_code=500)

    waits: list[float] = []
    sess = _ServerErrorSession()
    with pytest.raises(requests.HTTPError):
        phenom.fetch(SLUG, "Microsoft", session=sess, sleep=waits.append)
    assert sess.calls == 1                     # no backoff budget spent on a 500
    assert waits == []


def test_backoff_sleeps_with_time_sleep_by_default(monkeypatch):
    # The wait mechanism is injected like the http session (default = the real one),
    # so run.py needs no wiring and the suite never sleeps for real.
    calls: list[float] = []
    monkeypatch.setattr(phenom.time, "sleep", calls.append)
    out = phenom.fetch(SLUG, "Microsoft", session=_ThrottledSearchSession(throttles=1))

    assert calls == [phenom.RETRY_BASE_WAIT]
    assert len(out) == 3


def _keep_india(stub):
    if "India" in (stub["location"] or ""):
        return "discard"
    return "hydrate"


def test_stub_gate_against_real_fixture_discards_india_positions():
    sess = _FakeSession()
    out = phenom.fetch(SLUG, "Microsoft", session=sess, keep=_keep_india)

    fixture_positions = SEARCH["data"]["positions"]
    assert len(out) == len(fixture_positions)              # both India -> discard, not drop
    detail_gets = [p for u, p in sess.gets if u.endswith("/position_details")]
    assert detail_gets == []                                # no detail GET for either
    by_id = {o["external_id"]: o for o in out}
    for pos in fixture_positions:
        row = by_id[str(pos["id"])]
        assert row["description"] == ""
        assert row["job_url"].startswith("https://apply.careers.microsoft.com/")
