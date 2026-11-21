"""TDD for the worker_runs pass record (#247): one row per pass, stage counts, the
effective runtime config without secrets, and closed provider-failure categories."""
from __future__ import annotations

import json
import subprocess
from decimal import Decimal

import pytest

from ats_worker import config as cfgmod
from ats_worker import db, pipeline, run
from ats_worker.jev import JevError
from ats_worker.screening import backends
from ats_worker.screening.errors import ScoreError, provider_failure_category
from tests._helpers import NOW, bootstrap_db, make_posting

CFG = ("companies:\n  - { source: greenhouse, slug: a, name: A }\n"
       "candidate:\n  highest_degree: \"Master's\"\n")


def _runs(dbfile) -> list[dict]:
    conn = db.connect(dbfile)
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM worker_runs ORDER BY id")]
    finally:
        conn.close()
    for r in rows:
        r["config"] = json.loads(r["config_json"])
        r["counts"] = json.loads(r["counts_json"])
    return rows


@pytest.fixture
def offline(monkeypatch):
    """Fake every network seam run_once wires: boards list two postings, nothing is
    re-checked, quota capture is a no-op."""
    monkeypatch.setattr(run, "fetch_company", lambda source, slug, name, **_: [
        make_posting("1"), make_posting("2")])
    monkeypatch.setattr(run, "fetch_one_company", lambda *_a, **_k: None)
    monkeypatch.setattr(run, "capture_usage", lambda *_a, **_k: None)


def _dead_backend(*_a, **_k):
    def extract(prompt, schema):
        raise ConnectionRefusedError("ollama is not running")
    return extract


def test_a_pass_with_a_failing_screen_backend_records_ok_with_errors_counted(
        monkeypatch, tmp_path, offline):
    dbfile = bootstrap_db(tmp_path / "a.db")
    monkeypatch.setattr(run, "make_screener", _dead_backend)
    run.run_once(cfgmod.load_config(CFG), db_path=dbfile, env={})
    [row] = _runs(dbfile)
    assert row["status"] == "ok" and row["error_category"] is None
    assert row["finished_at"] and row["started_at"]
    assert row["fetch_only"] == 0 and row["jev_enabled"] == 0
    assert row["counts"]["fetch"]["inserted"] == 2
    screen = row["counts"]["screen"]
    assert screen["errors"] == 2 and screen["attempted"] == 2
    assert screen["errors_by_category"] == {"provider_unreachable": 2}


def test_a_pass_raising_midway_stays_running_and_the_next_pass_marks_it_failed(
        monkeypatch, tmp_path, offline):
    dbfile = bootstrap_db(tmp_path / "a.db")
    monkeypatch.setattr(run, "make_screener", _dead_backend)

    def boom(*_a, **_k):
        raise RuntimeError("worker killed mid-pass")

    real_expire = run.pipeline.run_expire
    monkeypatch.setattr(run.pipeline, "run_expire", boom)
    with pytest.raises(RuntimeError):
        run.run_once(cfgmod.load_config(CFG), db_path=dbfile, env={})
    [dead] = _runs(dbfile)
    assert dead["status"] == "running" and dead["finished_at"] is None
    assert dead["counts"]["fetch"]["inserted"] == 2   # stages before the crash are kept

    monkeypatch.setattr(run.pipeline, "run_expire", real_expire)
    run.run_once(cfgmod.load_config(CFG), db_path=dbfile, env={})
    dead, live = _runs(dbfile)
    assert (dead["status"], dead["error_category"], dead["finished_at"]) == \
        ("failed", "abandoned", None)
    assert live["status"] == "ok"


def test_a_fetch_only_pass_records_its_mode_and_no_screen(monkeypatch, tmp_path, offline):
    dbfile = bootstrap_db(tmp_path / "a.db")
    run.run_once(cfgmod.load_config(CFG), db_path=dbfile, env={}, fetch_only=True)
    [row] = _runs(dbfile)
    assert row["status"] == "ok" and row["fetch_only"] == 1
    assert set(row["counts"]) == {"fetch", "feed", "expire"}


def test_the_recorded_config_is_the_effective_one_and_never_a_secret(
        monkeypatch, tmp_path, offline):
    dbfile = bootstrap_db(tmp_path / "a.db")
    monkeypatch.setattr(run, "make_screener", lambda *_a, **_k: None)
    monkeypatch.setattr(run, "_run_jev", lambda *_a, **_k: {"skipped": "no_profile"})
    env = {"SCREEN_API_KEY": "sk-SECRET-screen", "OPENROUTER_API_KEY": "or-SECRET-jev",
           "SCREEN_API_BASE_URL": "https://user:pw-SECRET@example.test/v1"}
    cfg = cfgmod.load_config(CFG + "max_age_days: 14\nenable_browser_sources: true\n"
                             "feeds:\n  simplify:\n    enabled: false\n")
    run.run_once(cfg, db_path=dbfile, env=env, screen_backend="api", screen_model="m-1",
                 screen_limit=7, screen_workers=2, jev_enabled=True, jev_limit=9,
                 jev_max_usd=Decimal("0.25"))
    [row] = _runs(dbfile)
    assert "SECRET" not in json.dumps(row)
    assert row["config"] == {
        "screen": {"backend": "api", "model": "m-1", "effort": None, "limit": 7,
                   "workers": 2, "rescreen": False},
        "triage": {"backend": "openrouter-native", "limit": 9, "max_usd": "0.25"},
        "feeds": [], "browser_sources": True, "max_age_days": 14,
    }
    assert row["jev_enabled"] == 1 and row["counts"]["triage"] == {"skipped": "no_profile"}


def test_start_pass_abandons_only_running_rows(tmp_path):
    conn = db.connect(bootstrap_db(tmp_path / "a.db"))
    first = db.start_pass(conn, now=NOW, fetch_only=False, jev_enabled=False, config={})
    db.finish_pass(conn, first, now=NOW, counts={"fetch": {}})
    second = db.start_pass(conn, now=NOW, fetch_only=False, jev_enabled=False, config={})
    third = db.start_pass(conn, now=NOW, fetch_only=True, jev_enabled=False, config={})
    rows = {r["id"]: (r["status"], r["error_category"])
            for r in conn.execute("SELECT * FROM worker_runs")}
    assert rows == {first: ("ok", None), second: ("failed", "abandoned"),
                    third: ("running", None)}


# --- stage tallies ---------------------------------------------------------

def test_run_fetch_counts_every_drop_by_cause(tmp_path):
    conn = db.connect(bootstrap_db(tmp_path / "a.db"))
    listing = [
        make_posting("ok"),
        make_posting("title", job_title="Sales Manager"),
        make_posting("old", posted_at="2020-01-01"),
        make_posting("far", location="Berlin, Germany"),
        make_posting("blank", description=""),
    ]

    def fetch_fn(source, slug, name, **_):
        if slug == "down":
            raise RuntimeError("board is down")
        return [dict(p) for p in listing]

    companies = [{"source": "greenhouse", "slug": "a", "name": "A"},
                 {"source": "greenhouse", "slug": "down", "name": "D"}]
    counts: dict = {}
    inserted = pipeline.run_fetch(
        conn, companies, ["engineer"], now=NOW, fetch_fn=fetch_fn, max_age_days=30,
        candidate={"locations": ["Remote"]}, counts=counts)
    assert inserted == 2   # ok + the location discard
    assert counts == {
        "boards_attempted": 2, "boards_failed": 1, "listed": 5, "dropped_title": 1,
        "dropped_age": 1, "discarded": 1, "discarded_by_reason": {"location": 1},
        "bodyless": 1, "closed_by_absence": 0, "inserted": 2,
    }


def test_run_fetch_counts_stub_gate_drops_by_cause(tmp_path):
    conn = db.connect(bootstrap_db(tmp_path / "a.db"))
    stubs = [make_posting("ok"), make_posting("title", job_title="Sales Manager"),
             make_posting("old", posted_at="2020-01-01")]

    def fetch_fn(source, slug, name, *, keep, **_):
        return [dict(s) for s in stubs if keep(s) != "drop"]

    from ats_worker.fetch import STUB_GATE_SOURCES
    source = sorted(STUB_GATE_SOURCES - {"browser"})[0]
    counts: dict = {}
    pipeline.run_fetch(conn, [{"source": source, "slug": "s", "name": "S"}], ["engineer"],
                       now=NOW, fetch_fn=fetch_fn, max_age_days=30, counts=counts)
    assert (counts["listed"], counts["dropped_title"], counts["dropped_age"],
            counts["inserted"]) == (3, 1, 1, 1)


def test_run_feed_counts_listings_drops_resolution_and_inserts(tmp_path):
    conn = db.connect(bootstrap_db(tmp_path / "a.db"))
    listings = [
        {"url": "https://boards.greenhouse.io/acme/jobs/1", "title": "Software Engineer"},
        {"url": "https://boards.greenhouse.io/acme/jobs/2", "title": "Sales Lead"},
        {"url": "https://unknown.example/jobs/3", "title": "Data Engineer"},
        {"url": "https://boards.greenhouse.io/acme/jobs/4", "title": "Engineer", "gate": "no"},
    ]
    counts: dict = {}
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=[],
        prefilter_fn=lambda xs, _c: [x for x in xs if x.get("gate") != "no"],
        resolve_fn=lambda url: ("greenhouse", "acme", url.rsplit("/", 1)[1])
            if "greenhouse" in url else None,
        classify_fn=lambda url: ("unknown.example", "unsupported_host"),
        fetch_fn=lambda s, sl, n: [make_posting("1")],
        title_filter=["engineer"], counts=counts)
    assert inserted == 1
    assert counts == {"listings": 4, "prefilter_dropped": 1, "dropped_title": 1,
                      "dropped_age": 0, "dropped_age_board": 0, "resolved": 1,
                      "unresolved_by_reason": {"unsupported_host": 1}, "inserted": 1}


def test_run_expire_counts_checked_and_closed(tmp_path):
    conn = db.connect(bootstrap_db(tmp_path / "a.db"))
    db.upsert_postings(conn, [make_posting("a", source="smartrecruiters"),
                              make_posting("b", source="smartrecruiters")], now=NOW)

    class Gone(Exception):
        response = type("R", (), {"status_code": 404})()

    def detail(source, slug, ext, name):
        if ext == "a":
            raise Gone()
        return make_posting(ext)

    counts: dict = {}
    assert pipeline.run_expire(conn, now=NOW, detail_fetch_fn=detail, counts=counts) == 1
    assert counts == {"checked": 2, "closed": 1, "inconclusive": 0}


def test_run_screen_counts_disqualifications_by_check(tmp_path):
    conn = db.connect(bootstrap_db(tmp_path / "a.db"))
    db.upsert_postings(conn, [make_posting("a"), make_posting("b")], now=NOW)

    def screen_fn(posting):
        if posting["external_id"] == "a":
            return {"disqualified": True, "disqualification_reason": "x",
                    "screen": {"degree": {"pass": False}, "location": {"pass": False}}}
        return {"disqualified": False, "screen": {"degree": {"pass": True}}}

    tally = pipeline.run_screen(conn, now=NOW, screen_fn=screen_fn, extract=None,
                                backend="none", model=None, effort=None)
    assert tally["disqualified_by_reason"] == {"degree": 1, "location": 1}
    assert tally["errors_by_category"] == {}


def test_run_jev_counts_errors_by_category(tmp_path):
    conn = db.connect(bootstrap_db(tmp_path / "a.db"))
    db.upsert_postings(conn, [make_posting("a", posted_at=NOW[:10])], now=NOW)
    pid = conn.execute("SELECT id FROM job_postings").fetchone()[0]
    db.save_screening(conn, pid, state="complete", result={"screen": {}}, error_category=None,
                      backend="none", model=None, effort=None, evaluator_version="v", now=NOW)

    def jev_fn(posting):
        raise JevError("invalid_response")

    tally = pipeline.run_jev(conn, now=NOW, jev_fn=jev_fn, policy_sha="p", model="m",
                             limit=5, max_usd=Decimal("1"))
    assert tally["errors_by_category"] == {"invalid_response": 1}


# --- closed provider-failure categories --------------------------------------

class _HTTPError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.response = type("R", (), {"status_code": status})()


@pytest.mark.parametrize("exc,category", [
    (_HTTPError(401), "provider_auth"),
    (_HTTPError(403), "provider_auth"),
    (_HTTPError(429), "quota_exhausted"),
    (_HTTPError(500), "provider_error"),
    (ConnectionRefusedError(), "provider_unreachable"),
    (type("ConnectionError", (OSError,), {})(), "provider_unreachable"),  # requests'
    (TimeoutError(), "timeout"),
    (FileNotFoundError(), "executable_missing"),
    (ScoreError("x", category="quota_exhausted"), "quota_exhausted"),
    (ValueError("anything"), "provider_error"),
])
def test_provider_failure_category_names_the_cause(exc, category):
    assert provider_failure_category(exc) == category


def test_provider_failure_category_follows_the_cause_chain():
    try:
        try:
            raise ConnectionRefusedError()
        except ConnectionRefusedError as inner:
            raise ScoreError("wrapped") from inner
    except ScoreError as exc:
        assert provider_failure_category(exc) == "provider_unreachable"


@pytest.mark.parametrize("stderr,category", [
    ("Error: Not logged in. Run `codex login`.", "provider_auth"),
    ("401 Unauthorized: token expired", "provider_auth"),
    ("You've hit your usage limit. Try again later.", "quota_exhausted"),
    ("rate limit exceeded", "quota_exhausted"),
    ("segfault", None),
])
def test_cli_failures_are_categorized_from_stderr(stderr, category):
    def runner(cmd, **_):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=stderr)
    with pytest.raises(ScoreError) as info:
        backends._run_cli(runner, ["codex"], "prompt", 5, "codex screen")
    assert info.value.category == category


def test_a_categorized_screen_failure_is_stored_on_the_screening(tmp_path):
    from ats_worker.screening import screen_posting
    posting = make_posting("a")

    def extract(prompt, schema):
        raise _HTTPError(401)

    out = screen_posting(posting, extract=extract, candidate={"highest_degree": "Master's"})
    assert out["provider_error_category"] == "provider_auth"
    conn = db.connect(bootstrap_db(tmp_path / "a.db"))
    db.upsert_postings(conn, [posting], now=NOW)
    pid = conn.execute("SELECT id FROM job_postings").fetchone()[0]
    db.save_screening(conn, pid, state="provider_error", result=None,
                      error_category="provider_auth", backend="api", model="m",
                      effort=None, evaluator_version="v", now=NOW)
