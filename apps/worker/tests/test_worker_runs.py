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


def test_the_recorded_max_age_days_is_the_profile_not_the_config_seed(monkeypatch, tmp_path, offline):
    dbfile = bootstrap_db(tmp_path / "a.db")
    conn = db.connect(dbfile)
    conn.execute("INSERT INTO candidate_profile (id, max_age_days, actor, updated_at) "
                 "VALUES (1, 3, 'web', '2026-11-20T00:00:00Z')")
    conn.commit()
    conn.close()
    cfg = cfgmod.load_config(CFG + "max_age_days: 14\n")
    run.run_once(cfg, db_path=dbfile, env={}, fetch_only=True)
    [row] = _runs(dbfile)
    assert row["config"]["max_age_days"] == 3


def test_triage_skip_reasons_follow_the_profile(monkeypatch):
    from ats_worker import profile
    assert run._run_jev_extract(None, None, extract=None, limit=1, model="m", now="x") == {
        "skipped": "no_profile"}
    no_role = profile.CandidateProfile()
    assert run._run_jev(None, no_role, env={"OPENROUTER_API_KEY": "k"}, limit=1,
                        max_usd=Decimal("1"), now="x") == {"skipped": "no_profile"}
    bad = profile.CandidateProfile(target_roles=("SWE",),
                                   custom_packs={"preference_pack": "{}", "yoe_pack": "{}"})
    assert run._run_jev_extract(None, bad, extract=None, limit=1, model="m", now="x") == {
        "skipped": "invalid_packs"}


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
        "bodyless": 1, "detail_failed": 0, "closed_by_absence": 0, "inserted": 2,
    }


def test_run_fetch_counts_id_less_stubs_and_lost_details(tmp_path):
    # workday's parse_stub carries no external_id, so `listed` must count gate calls,
    # and a stub the gate passed whose detail GET failed comes back as nothing.
    conn = db.connect(bootstrap_db(tmp_path / "a.db"))
    stubs = [{"job_title": "Software Engineer", "location": "Remote"},
             {"job_title": "Software Engineer II", "location": "Remote"},
             {"job_title": "Sales Manager", "location": "Remote"},
             {"job_title": "Account Executive", "location": "Remote"}]

    def fetch_fn(source, slug, name, *, keep, now):
        passed = [s for s in stubs if keep(s) != "drop"]
        return [make_posting("w1")] if passed else []   # the second detail GET failed

    counts: dict = {}
    pipeline.run_fetch(conn, [{"source": "workday", "slug": "t/d/s", "name": "W"}],
                       ["engineer"], now=NOW, fetch_fn=fetch_fn, counts=counts)
    assert (counts["listed"], counts["dropped_title"], counts["detail_failed"],
            counts["inserted"]) == (4, 2, 1, 1)


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
    db.upsert_postings(conn, [make_posting("7")], now=NOW)
    gh = "https://boards.greenhouse.io/acme/jobs/"
    listings = [
        {"url": gh + "1", "title": "Software Engineer"},          # resolved + inserted
        {"url": gh + "2", "title": "Sales Lead"},                 # title
        {"url": "https://unknown.example/jobs/3", "title": "Data Engineer"},  # unresolved
        {"url": gh + "4", "title": "Engineer", "gate": "no"},     # feed's own gate
        {"url": "", "title": "Engineer"},                         # no url
        {"url": gh + "1", "title": "Software Engineer"},          # duplicate id
        {"url": gh + "7", "title": "Engineer"},                   # already stored
        {"url": gh + "8", "title": "Engineer"},                   # board no longer lists it
        {"url": "https://jobs.lever.co/x/9", "title": "Engineer"},  # list fetch fails
    ]

    def resolve(url):
        if "greenhouse" in url:
            return ("greenhouse", "acme", url.rsplit("/", 1)[1])
        if "lever" in url:
            return ("lever", "x", "9")
        return None

    def fetch_fn(source, slug, name):
        if source == "lever":
            raise RuntimeError("board down")
        return [make_posting("1"), make_posting("7")]

    counts: dict = {}
    inserted = pipeline.run_feed(
        conn, now=NOW, feed_fn=lambda: listings, keep_categories=[],
        prefilter_fn=lambda xs, _c: [x for x in xs if x.get("gate") != "no"],
        resolve_fn=resolve, classify_fn=lambda url: ("unknown.example", "unsupported_host"),
        fetch_fn=fetch_fn, title_filter=["engineer"], counts=counts)
    assert inserted == 1
    assert counts == {
        "listings": 9, "prefilter_dropped": 1, "dropped_title": 1, "dropped_age": 0,
        "no_url": 1, "unresolved_by_reason": {"unsupported_host": 1, "list_fetch_failed": 1},
        "duplicate": 1, "already_stored": 1, "not_on_board": 1, "resolved": 1,
        "dropped_age_board": 0, "inserted": 1}
    buckets = ("prefilter_dropped", "dropped_title", "dropped_age", "no_url", "duplicate",
               "already_stored", "not_on_board", "resolved")
    assert counts["listings"] == sum(counts[k] for k in buckets) + \
        sum(counts["unresolved_by_reason"].values())


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
    ("error: unexpected status 429 Too Many Requests", "quota_exhausted"),
    ("HTTP/1.1 401", "provider_auth"),
    ("segfault", None),
    # JD text echoed into stderr must not read as a cause.
    ("Benefits: 401(k) match, sales quota attainment, login to our portal", None),
    ("We offer a 401k and 429 days of PTO", None),
    # Only the last lines count: an early echo of the prompt is ignored.
    ("not logged in\n" + "context\n" * 6 + "segfault", None),
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


# --- daemon startup -----------------------------------------------------------

@pytest.mark.parametrize("has_table", [True, False])
def test_the_daemon_refuses_to_start_on_a_db_without_worker_runs(
        has_table, monkeypatch, tmp_path):
    import sqlite3
    dbfile = bootstrap_db(tmp_path / "a.db")
    if not has_table:
        with sqlite3.connect(dbfile) as raw:
            raw.execute("DROP TABLE worker_runs")    # a DB pushed before #247
    cfg = tmp_path / "config.yaml"
    cfg.write_text("companies: []\n")
    started = []
    monkeypatch.setattr(run, "_run_scheduler", lambda job, hours: started.append(hours))
    argv = ["--config", str(cfg), "--db", dbfile, "--env", str(tmp_path / "none.env")]
    if has_table:
        run.main(argv)
        assert started
    else:
        with pytest.raises(SystemExit) as info:
            run.main(argv)
        assert "make db-push" in str(info.value.code) and started == []
