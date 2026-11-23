"""#273: Workday requests are paced per host, and a 429 is retried before it is
recorded inconclusive. A fake clock (its sleep advances time) and a fake session
stand in for the network; nothing here opens a socket or really sleeps."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from ats_worker import db, pipeline
from ats_worker.fetch import _pacing, workday
from tests._helpers import NOW, make_posting

DETAIL = json.loads((Path(__file__).parent / "fixtures" / "workday_detail.json").read_text())
A = "acme/wd5/Careers"      # host acme.wd5.myworkdayjobs.com
B = "beta/wd1/Jobs"         # host beta.wd1.myworkdayjobs.com
LATER = "2026-12-01T00:00:00Z"


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class Resp:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._data = DETAIL if data is None else data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return self._data


class Session:
    """Answers each GET from a per-host script (the last entry repeats); records
    (clock time, host) for every request actually sent."""

    def __init__(self, clock, scripts):
        self.clock, self.scripts, self.sent = clock, scripts, []

    def get(self, url, headers=None, timeout=None):
        host = url.split("/")[2].split(".")[0]
        self.sent.append((self.clock.now(), host))
        script = self.scripts.get(host, [Resp()])
        return script.pop(0) if len(script) > 1 else script[0]


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(workday, "_PACER", _pacing.HostPacer(clock=c.now, sleep=c.sleep))
    return c


def _one(slug, sess, path="/job/NYC/Quant_R1"):
    return workday.fetch_one(slug, path, "Acme", session=sess)


def test_requests_to_one_host_are_spaced_but_other_hosts_are_not(clock):
    sess = Session(clock, {})
    _one(A, sess)
    _one(A, sess)
    _one(B, sess)
    (t1, _), (t2, _), (t3, _) = sess.sent
    assert t2 - t1 >= _pacing.MIN_INTERVAL
    assert t3 == t2        # beta never waits on acme's interval


def test_429_then_200_retries_after_retry_after_and_succeeds(clock):
    sess = Session(clock, {"acme": [Resp(429, headers={"Retry-After": "7"}), Resp()]})
    assert _one(A, sess)["source"] == "workday"
    (t1, _), (t2, _) = sess.sent
    assert t2 - t1 == 7


def test_429_without_retry_after_backs_off_exponentially_and_bounded(clock):
    sess = Session(clock, {"acme": [Resp(429), Resp(429), Resp()]})
    assert _one(A, sess) is not None
    gaps = [b - a for (a, _), (b, _) in zip(sess.sent, sess.sent[1:])]
    assert gaps == [_pacing.BACKOFF, 2 * _pacing.BACKOFF]


def test_retry_after_at_the_cap_is_still_waited_and_retried(clock):
    sess = Session(clock, {"acme": [Resp(429, headers={"Retry-After": "30"}), Resp()]})
    _one(A, sess)
    (t1, _), (t2, _) = sess.sent
    assert t2 - t1 == _pacing.MAX_DELAY


def test_persistent_429_gives_up_as_http_429_and_cools_the_host(clock):
    sess = Session(clock, {"acme": [Resp(429)]})
    with pytest.raises(requests.HTTPError) as exc:
        _one(A, sess)
    assert exc.value.response.status_code == 429
    assert len(sess.sent) == 1 + _pacing.RETRIES
    # Another host is served at once; acme answers 429 without a request while cooling.
    before = len(sess.sent)
    t0 = clock.t
    assert _one(B, sess) is not None
    assert clock.t == t0
    with pytest.raises(requests.HTTPError):
        _one(A, sess)
    assert len(sess.sent) == before + 1   # only beta's request went out


def test_board_list_post_is_paced_and_retried(clock):
    posts = []

    class Board:
        def post(self, url, json=None, headers=None, timeout=None):
            posts.append(clock.now())
            if len(posts) == 1:
                return Resp(429, headers={"Retry-After": "3"})
            return Resp(data={"total": 0, "jobPostings": []})

    assert workday.fetch(A, "Acme", session=Board()) == []
    assert posts[1] - posts[0] == 3


def test_expire_records_a_throttled_tenant_inconclusive_and_still_checks_others(
        clock, db_path):
    conn = db.connect(db_path)
    rows = [make_posting(f"g{i}", source="workday", company_slug=slug,
                         job_url=f"https://{host}.myworkdayjobs.com/s/job/X/R{i}")
            for i, (slug, host) in enumerate([(A, "acme.wd5"), (A, "acme.wd5"),
                                              (B, "beta.wd1")])]
    db.upsert_postings(conn, rows, now=NOW)
    sess = Session(clock, {"acme": [Resp(429)]})
    counts = {}
    pipeline.run_expire(
        conn, now=LATER, counts=counts,
        detail_fetch_fn=lambda s, sl, e, n: workday.fetch_one(sl, e, n, session=sess))
    assert counts == {"checked": 3, "closed": 0, "inconclusive": 2}
    cats = {r["external_id"]: (r["source_last_check_outcome"],
                               r["source_last_check_error_category"])
            for r in conn.execute("SELECT * FROM job_postings")}
    assert cats["g0"] == cats["g1"] == ("inconclusive", "http_429")
    assert cats["g2"][0] == "found"


def test_retry_after_above_the_cap_gives_up_at_once_and_cools_for_it(clock):
    sess = Session(clock, {"acme": [Resp(429, headers={"Retry-After": "600"}), Resp()]})
    with pytest.raises(requests.HTTPError):
        _one(A, sess)
    assert len(sess.sent) == 1                 # no clamped retry
    clock.t += 599
    with pytest.raises(requests.HTTPError):    # still cooling for the server's 600s
        _one(A, sess)
    clock.t += 2
    assert _one(A, sess) is not None
    assert len(sess.sent) == 2


def test_huge_retry_after_cools_for_at_most_the_ceiling(clock):
    sess = Session(clock, {"acme": [Resp(429, headers={"Retry-After": "99999"}), Resp()]})
    with pytest.raises(requests.HTTPError):
        _one(A, sess)
    clock.t += _pacing.MAX_COOLDOWN + 1
    assert _one(A, sess) is not None


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "soon"])
def test_a_non_finite_retry_after_falls_back_to_backoff(clock, value):
    sess = Session(clock, {"acme": [Resp(429, headers={"Retry-After": value}), Resp()]})
    assert _one(A, sess) is not None
    (t1, _), (t2, _) = sess.sent
    assert t2 - t1 == _pacing.BACKOFF


def test_a_host_that_cools_while_a_request_waits_is_not_sent(clock):
    # Another thread's request puts acme into cooldown while this one sleeps for its
    # slot: the waiting request must take the cached 429, not send.
    other = Session(clock, {"acme": [Resp(429, headers={"Retry-After": "600"})]})
    mine = Session(clock, {})
    real_sleep, fired = clock.sleep, []

    def sleep(s):
        real_sleep(s)
        if not fired:
            fired.append(1)
            with pytest.raises(requests.HTTPError):
                _one(A, other)

    workday._PACER._sleep = sleep
    _one(A, mine)                      # first send, no wait
    with pytest.raises(requests.HTTPError) as exc:
        _one(A, mine)                  # waits 0.5s; acme cools meanwhile
    assert exc.value.response.status_code == 429
    assert len(mine.sent) == 1
