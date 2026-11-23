"""Evaluate once (#225), through whole passes: each posting is screened and triaged at
most once inside the shared window, and the stored verdict never moves afterwards."""
from __future__ import annotations

import json

import pytest

from ats_worker import config as cfgmod
from ats_worker import db, run
from tests._helpers import bootstrap_db, make_posting

CFG = "companies:\n  - { source: greenhouse, slug: a, name: A }\n"
PROFILE = dict(target_roles='["Backend engineer"]',
               education='[{"degree":"master\'s","field":"CS"}]',
               locations='["remote","USA"]')


@pytest.fixture
def board(monkeypatch):
    """The board lists whatever the test puts here; nothing is re-checked."""
    listed = [make_posting("1"), make_posting("2", job_title="Data Engineer")]
    monkeypatch.setattr(run, "fetch_company", lambda *_a, **_k: [dict(p) for p in listed])
    monkeypatch.setattr(run, "fetch_one_company", lambda *_a, **_k: None)
    monkeypatch.setattr(run, "capture_usage", lambda *_a, **_k: None)
    return listed


@pytest.fixture
def provider(monkeypatch):
    """One fake extract serving both the screen and the triage packs; records calls."""
    calls = []
    picks = {"preference": "strong", "domain": "swe", "required_yoe_for_candidate": "within_candidate"}

    def extract(prompt, schema):
        stage = "screen" if "screen" in schema["properties"] else "triage"
        calls.append(stage)
        if stage == "screen":
            return {"screen": {}}
        return {k: picks.get(k, next(iter(v.get("enum", [0])))) for k, v in schema["properties"].items()}
    monkeypatch.setattr(run, "make_screener", lambda *_a, **_k: extract)
    return calls


def _profile(dbfile, **cols):
    conn = db.connect(dbfile)
    cols = {"actor": "web", "updated_at": "2026-11-20T00:00:00.000Z", **PROFILE, **cols}
    conn.execute(f"INSERT INTO candidate_profile (id, {', '.join(cols)}) "
                 f"VALUES (1, {', '.join('?' * len(cols))})", tuple(cols.values()))
    conn.commit()
    conn.close()


def _state(dbfile) -> dict:
    conn = db.connect(dbfile)
    try:
        return {r["external_id"]: (r["verdict"], r["screen_version"], r["triage_version"])
                for r in conn.execute(
                    "SELECT p.external_id, p.verdict, s.profile_version AS screen_version, "
                    "j.profile_version AS triage_version FROM job_postings p "
                    "LEFT JOIN job_screenings s ON s.job_posting_id=p.id "
                    "LEFT JOIN job_jev_assessments j ON j.job_posting_id=p.id ORDER BY p.id")}
    finally:
        conn.close()


def _pass(dbfile, **kw):
    run.run_once(cfgmod.load_config(CFG), db_path=dbfile, env={}, screen_backend="ollama",
                 jev_enabled=True, jev_backend="extract", **kw)


def test_editing_the_profile_requeues_nothing(tmp_path, board, provider):
    dbfile = bootstrap_db(tmp_path / "a.db")
    _profile(dbfile)
    _pass(dbfile)
    first = _state(dbfile)
    assert {v[0] for v in first.values()} <= {"keep", "skip"}
    assert first["1"][1:] == (1, 1)
    calls_before = len(provider)

    # The operator edits every section the stages read: requirements, background,
    # preferences.
    conn = db.connect(dbfile)
    conn.execute("UPDATE candidate_profile SET version=2, target_roles='[\"Data engineer\"]', "
                 "education='[{\"degree\":\"phd\",\"field\":\"Math\"}]', "
                 "work_authorization='needs visa sponsorship', changed_at='2026-11-21T00:00:00.000Z'")
    conn.commit()
    conn.close()
    board.append(make_posting("3"))
    _pass(dbfile)

    after = _state(dbfile)
    # The old verdicts and their recorded versions stand; only the new posting ran, under v2.
    assert {k: after[k] for k in first} == first
    assert after["3"][1:] == (2, 2)
    # One posting, two triage packs: nothing old was asked again.
    assert provider[calls_before:].count("triage") == 2


def test_without_triage_a_passing_screen_is_the_final_keep(tmp_path, board, provider):
    dbfile = bootstrap_db(tmp_path / "a.db")
    _profile(dbfile)
    run.run_once(cfgmod.load_config(CFG), db_path=dbfile, env={}, screen_backend="ollama")
    assert {k: v[0] for k, v in _state(dbfile).items()} == {"1": "keep", "2": "keep"}
    assert "triage" not in provider


def test_a_triage_pass_without_a_target_role_keeps_what_passed(tmp_path, board, provider):
    # Triage is enabled but has nothing to judge against: requirements are the last stage.
    dbfile = bootstrap_db(tmp_path / "a.db")
    _profile(dbfile, target_roles="[]")
    _pass(dbfile)
    assert {k: v[0] for k, v in _state(dbfile).items()} == {"1": "keep", "2": "keep"}


def test_a_fetch_discard_is_final_and_counted(tmp_path, board, provider):
    dbfile = bootstrap_db(tmp_path / "a.db")
    _profile(dbfile)
    board.append(make_posting("far", location="Shanghai, China"))
    _pass(dbfile, fetch_only=True)
    assert _state(dbfile)["far"] == ("discarded", 1, None)
    _pass(dbfile)
    assert _state(dbfile)["far"] == ("discarded", 1, None)


def test_postings_that_leave_the_window_unevaluated_are_final_and_counted(tmp_path, board, provider):
    dbfile = bootstrap_db(tmp_path / "a.db")
    _profile(dbfile)
    _pass(dbfile, fetch_only=True)
    conn = db.connect(dbfile)
    conn.execute("UPDATE job_postings SET posted_at='2020-01-01' WHERE external_id='1'")
    conn.commit()
    conn.close()
    _pass(dbfile)
    state = _state(dbfile)
    assert state["1"] == ("not_evaluated", None, None)
    assert state["2"][0] in {"keep", "skip"}
    conn = db.connect(dbfile)
    counts = [json.loads(r[0]) for r in conn.execute("SELECT counts_json FROM worker_runs ORDER BY id")]
    conn.close()
    assert counts[-1]["verdict"]["aged_out"] == 1


def test_a_pass_refuses_while_legacy_discards_await_the_migration(tmp_path, board, provider):
    dbfile = bootstrap_db(tmp_path / "a.db")
    conn = db.connect(dbfile)
    db.upsert_postings(conn, [make_posting("old")], now="2026-06-04T08:00:00.000Z")
    conn.execute("UPDATE job_postings SET pipeline_status='discarded', score_detail=?",
                 (json.dumps({"screen": {}, "disqualified": True, "disqualification_reason": "x"}),))
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="migrate_evaluate_once"):
        _pass(dbfile)


@pytest.mark.parametrize("unsettled", [
    "INSERT INTO job_screenings (job_posting_id, state, result_json, backend, evaluator_version, "
    "last_attempted_at, completed_at, created_at) VALUES (1, 'complete', "
    "'{\"screen\":{},\"disqualified\":true}', 'ollama', 'v', 'x', 'x', 'x')",
    "INSERT INTO job_jev_assessments (job_posting_id, state, verdict, model, "
    "last_attempted_at, created_at) VALUES (1, 'complete', 'keep', 'm', 'x', 'x')",
])
def test_a_pass_refuses_with_no_legacy_discard_but_an_unsettled_verdict(
        tmp_path, board, provider, unsettled):
    """Zero legacy discards (or a migration killed after moving them): a pending posting
    with a finished screen discard or triage verdict still needs the backfill, and a pass
    would age it out as not_evaluated. It refuses before it seeds or writes anything."""
    dbfile = bootstrap_db(tmp_path / "a.db")
    conn = db.connect(dbfile)
    db.upsert_postings(conn, [make_posting("old")], now="2026-06-04T08:00:00.000Z")
    conn.execute(unsettled)
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="migrate_evaluate_once"):
        _pass(dbfile)
    conn = db.connect(dbfile)
    assert conn.execute("SELECT COUNT(*) FROM candidate_profile").fetchone()[0] == 0
    assert conn.execute("SELECT verdict FROM job_postings").fetchone()[0] == "pending"
    conn.close()


def test_the_daemon_refuses_to_start_while_legacy_discards_remain(monkeypatch, tmp_path):
    dbfile = bootstrap_db(tmp_path / "a.db")
    conn = db.connect(dbfile)
    db.upsert_postings(conn, [make_posting("old")], now="2026-06-04T08:00:00.000Z")
    conn.execute("UPDATE job_postings SET pipeline_status='discarded'")
    conn.commit()
    conn.close()
    cfg = tmp_path / "config.yaml"
    cfg.write_text("companies: []\n")
    started = []
    monkeypatch.setattr(run, "_run_scheduler", lambda job, hours: started.append(hours))
    with pytest.raises(SystemExit, match="migrate_evaluate_once"):
        run.main(["--config", str(cfg), "--db", dbfile, "--env", str(tmp_path / "none.env")])
    assert started == []
