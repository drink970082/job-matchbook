"""TDD for the orchestration state machine.

The critical invariant: one bad row must never abort a batch — it is marked
'failed' and the rest proceed.
"""
from __future__ import annotations

import json as _json

import pytest

from ats_worker import db, pipeline, score
from tests._helpers import (
    LATER,
    NOW,
    make_posting as _posting,
    seed_new as _seed_new,
    seed_scored as _seed_scored,
)


def _assessment(**over):
    """A minimally-valid fit assessment scorecard — passes score._normalize_score's
    enum checks (seniority/domain verdicts) so a fit_fn fake's card doesn't itself
    raise ScoreError before run_score's fallback logic is what's under test."""
    base = {
        "seniority": {"verdict": "match", "note": ""},
        "domain": {"verdict": "match", "note": ""},
        "must_haves": {"met": [], "missing": []},
        "nice_to_haves": {"missing": []},
        "summary": "",
    }
    base.update(over)
    return base


# --- run_fetch ------------------------------------------------------------

def test_run_fetch_inserts_filtered_postings(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        return [
            _posting("1", job_title="Python Engineer", location="Remote"),
            _posting("2", job_title="Sales Rep", location="NYC"),
        ]

    companies = [{"source": "greenhouse", "slug": "acme", "name": "Acme"}]
    inserted = pipeline.run_fetch(conn, companies, ["engineer"], now=NOW, fetch_fn=fetch_fn)
    assert inserted == 1
    rows = db.get_by_status(conn, "new")
    assert [r["external_id"] for r in rows] == ["1"]
    # run_fetch stamps the company's slug onto each ingested posting before upsert.
    assert rows[0]["company_slug"] == "acme"


def test_run_fetch_one_company_failing_does_not_abort(db_path):
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        if slug == "bad":
            raise RuntimeError("boom")
        return [_posting("ok")]

    companies = [
        {"source": "greenhouse", "slug": "bad", "name": "Bad"},
        {"source": "lever", "slug": "good", "name": "Good"},
    ]
    inserted = pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn)
    assert inserted == 1


def test_run_fetch_logs_the_skipped_company(db_path, capsys):
    # The docstring promises "logged-and-skipped", but the bare except was silent —
    # a dead board / typo'd source vanished with no trace. It must now print.
    conn = db.connect(db_path)

    def fetch_fn(source, slug, name):
        raise RuntimeError("boom")

    companies = [{"source": "greenhouse", "slug": "bad", "name": "Bad"}]
    pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn)
    out = capsys.readouterr().out
    assert "greenhouse/bad" in out and "boom" in out


def test_run_fetch_requires_injected_fetch_fn():
    # fetch_fn defaults to None: the real adapter is wired only in run.py.
    import inspect
    assert inspect.signature(pipeline.run_fetch).parameters["fetch_fn"].default is None


def test_run_fetch_raises_when_fetch_fn_missing(db_path):
    # Omitting fetch_fn must fail loud (a wiring mistake), not degrade into a
    # per-company swallowed TypeError that silently fetches nothing.
    conn = db.connect(db_path)
    companies = [{"source": "greenhouse", "slug": "x", "name": "X"}]
    with pytest.raises(ValueError):
        pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=None)


# --- run_score ------------------------------------------------------------

def test_run_score_only_new_and_one_failure_isolated(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3"])

    # The failure is a screen-stage error (e.g. Ollama down) — one bad SCREEN
    # call must not abort the pass; the other two rows still get scored.
    def screen_fn(posting):
        if posting["external_id"] == "2":
            raise RuntimeError("ollama down")
        return {"disqualified": False}

    def fit_fn(postings):
        return [{"score": 90, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)

    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["1"] == "scored"
    assert statuses["3"] == "scored"
    assert statuses["2"] == "failed"


def test_run_score_skips_non_new(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pid = conn.execute("SELECT id FROM job_postings").fetchone()[0]
    db.save_score(conn, pid, score=10, score_detail={}, now=NOW)  # now 'scored'

    called = []

    def screen_fn(posting):
        called.append(posting["external_id"])
        return {"disqualified": False}

    def fit_fn(postings):
        raise AssertionError("fit must not run — there are no 'new' rows")

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    assert called == []


# --- run_notify -----------------------------------------------------------

# A save_score detail whose seniority + domain verdicts are both 'match' —
# db.get_notifiable's notify gate. Shared by every run_notify test below that
# just needs "this row is notifiable" without caring about the verdict values.
_MATCH_MATCH = {"assessment": {"seniority": {"verdict": "match"},
                               "domain": {"verdict": "match"}}}


def test_run_notify_pings_only_verdict_matches(db_path):
    conn = db.connect(db_path)

    def add(ext_id, sen, dom):
        db.upsert_postings(conn, [_posting(ext_id)], now=NOW)
        row = conn.execute(
            "SELECT id FROM job_postings WHERE external_id=?", (ext_id,)
        ).fetchone()
        db.save_score(conn, row["id"], score=50, now=NOW, status="scored",
                      score_detail={"assessment": {"seniority": {"verdict": sen},
                                                    "domain": {"verdict": dom}}})

    add("hi", "match", "match")       # ping
    add("lo", "match", "adjacent")    # no ping (below the verdict bar)

    notified = []

    def notify_fn(posting, *, token, chat_id):
        notified.append(posting["external_id"])

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="test_token", chat_id="c")
    assert notified == ["hi"]

    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["hi"] == "notified"
    assert statuses["lo"] == "scored"  # untouched, not a match/match verdict pair


def test_run_notify_advances_and_passes_token_chat(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"1": 90, "2": 95}, detail=_MATCH_MATCH)

    notified = []

    def notify_fn(posting, *, token, chat_id):
        notified.append((posting["external_id"], token, chat_id))

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="tok", chat_id="cid")
    assert {n[0] for n in notified} == {"1", "2"}
    assert all(n[1] == "tok" and n[2] == "cid" for n in notified)
    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses == {"1": "notified", "2": "notified"}


def test_run_notify_failure_isolated(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"1": 90, "2": 95}, detail=_MATCH_MATCH)

    def notify_fn(posting, *, token, chat_id):
        if posting["external_id"] == "1":
            raise RuntimeError("telegram 429")

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="test_token", chat_id="c")
    rows = {r["external_id"]: r for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    # A send error is transient: the row stays 'scored' for a next-pass retry,
    # with the failure recorded on it; the sibling is unaffected.
    assert rows["1"]["pipeline_status"] == "scored"
    assert rows["1"]["attempts"] == 1
    assert "telegram" in rows["1"]["pipeline_error"]
    assert rows["2"]["pipeline_status"] == "notified"


def test_run_score_disqualified_is_discarded_with_reason(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2"])

    def screen_fn(posting):
        if posting["external_id"] == "1":
            return {"disqualified": True, "disqualification_reason": "requires a PhD"}
        return {"disqualified": False}

    def fit_fn(postings):
        return [{"score": 80, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    rows = {r["external_id"]: r for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    assert rows["1"]["pipeline_status"] == "discarded"
    assert rows["2"]["pipeline_status"] == "scored"
    # A disqualified posting never reaches the fit scorer (screened out before
    # the fit phase even runs) — so it's persisted with score 0, not a fit score.
    assert rows["1"]["score"] == 0
    detail = _json.loads(rows["1"]["score_detail"])
    assert detail["disqualified"] is True
    assert detail["disqualification_reason"] == "requires a PhD"


def test_run_score_insufficient_context_persisted(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    def screen_fn(posting):
        return {"disqualified": False}

    def fit_fn(postings):
        return [{"score": 55, "insufficient_context": True, "assessment": _assessment()}
                for _ in postings]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    rows = {r["external_id"]: r for r in conn.execute("SELECT * FROM job_postings").fetchall()}
    assert rows["1"]["pipeline_status"] == "scored"   # still scored; the UI routes it
    detail = _json.loads(rows["1"]["score_detail"])
    assert detail["insufficient_context"] is True


# --- failure bookkeeping + stage gating -----------------------------------

def test_run_score_failure_records_error_and_increments_attempts(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    def screen_fn(posting):
        raise RuntimeError("ollama down")

    def fit_fn(postings):
        raise AssertionError("fit must not run — the screen failed")

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "failed"
    assert row["attempts"] == 1
    assert "ollama down" in row["pipeline_error"]


def test_run_score_passes_full_posting_to_scorer(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    seen = {}

    def screen_fn(posting):
        return {"disqualified": False}

    def fit_fn(postings):
        seen.update(postings[0])
        return [{"score": 50, "assessment": _assessment()}]

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
    assert seen.get("description")   # the JD text reached the scorer, not just the id
    assert seen.get("job_title")


def test_run_score_persists_recommended_resume(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2"])

    def screen_fn(posting):
        return {"disqualified": False}

    def fit_fn(postings):
        out = []
        for p in postings:
            card = {"score": 88, "assessment": _assessment()}
            if p["external_id"] == "1":
                card["recommended_resume"] = "swe"
            out.append(card)
        return out

    pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)

    details = {
        r["external_id"]: _json.loads(r["score_detail"])
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert details["1"]["recommended_resume"] == "swe"
    # absent from the scorer result -> absent from the stored JSON (old shape)
    assert "recommended_resume" not in details["2"]


def test_run_score_batches_survivors_and_falls_back_on_batch_error(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3"])
    calls = {"batch": [], "single": 0}

    def fit_fn(postings):
        ids = [p["id"] for p in postings]
        calls["batch"].append(ids)
        if len(ids) > 1:
            raise score.ScoreError("batch parse failed")      # force fallback
        calls["single"] += 1
        return [{"score": 70, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=NOW, batch_size=10,
                       screen_fn=lambda p: {"disqualified": False},
                       fit_fn=fit_fn)
    assert calls["batch"][0] == [1, 2, 3]     # tried as one batch
    assert calls["single"] == 3               # fell back to singles
    assert len(db.get_by_status(conn, "scored")) == 3


def test_run_score_falls_back_on_non_scoreerror_batch_failure(db_path):
    # A transient NON-ScoreError from the batch call (e.g. make_claude_scorer lets an
    # anthropic.RateLimitError from client.messages.create() propagate — it only
    # wraps json.loads in ScoreError) must ALSO trigger the singles fallback, not
    # escape run_score and abort every remaining chunk + skip run_notify. The
    # batch-level catch is `except Exception`, not `except ScoreError`, to cover this.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3"])
    calls = {"batch": [], "single": 0}

    def fit_fn(postings):
        ids = [p["id"] for p in postings]
        calls["batch"].append(ids)
        if len(ids) > 1:
            raise RuntimeError("api down")          # NON-ScoreError -> must still fall back
        calls["single"] += 1
        return [{"score": 70, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=NOW, batch_size=10,
                       screen_fn=lambda p: {"disqualified": False},
                       fit_fn=fit_fn)
    assert calls["batch"][0] == [1, 2, 3]     # tried as one batch
    assert calls["single"] == 3               # fell back to singles despite RuntimeError
    # Every survivor still processed to 'scored' — the pass was NOT aborted.
    assert len(db.get_by_status(conn, "scored")) == 3


def test_run_score_falls_back_when_batch_returns_short(db_path):
    # A backend that returns FEWER cards than postings without raising must not
    # zip-misalign and orphan the tail — it falls back to singles so all score.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2", "3"])
    calls = {"single": 0}

    def fit_fn(postings):
        if len(postings) > 1:
            return [{"score": 70, "assessment": _assessment()}]   # short by 2
        calls["single"] += 1
        return [{"score": 70, "assessment": _assessment()}]

    pipeline.run_score(conn, now=NOW, batch_size=10,
                       screen_fn=lambda p: {"disqualified": False}, fit_fn=fit_fn)
    assert calls["single"] == 3
    assert len(db.get_by_status(conn, "scored")) == 3


def test_run_score_persists_disqualified_without_fit(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pipeline.run_score(
        conn, now=NOW, batch_size=10,
        screen_fn=lambda p: {"disqualified": True, "disqualification_reason": "x"},
        fit_fn=lambda ps: (_ for _ in ()).throw(AssertionError("fit must not run")),
    )
    assert db.get_by_status(conn, "discarded")[0]["id"] == 1


def test_run_score_fallback_single_failure_is_isolated(db_path):
    # The batch fails (forcing the single-item fallback); within that fallback,
    # ONE posting's single fit_fn call still fails — it alone is marked 'failed',
    # its batch-mate is still scored.
    conn = db.connect(db_path)
    _seed_new(conn, ["1", "2"])

    def fit_fn(postings):
        if len(postings) > 1:
            raise score.ScoreError("batch parse failed")
        posting = postings[0]
        if posting["external_id"] == "1":
            raise RuntimeError("codex exec failed for this one JD")
        return [{"score": 70, "assessment": _assessment()}]

    pipeline.run_score(conn, now=NOW, batch_size=10,
                       screen_fn=lambda p: {"disqualified": False}, fit_fn=fit_fn)

    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["1"] == "failed"
    assert statuses["2"] == "scored"


def test_run_notify_send_error_retries_then_parks_failed(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90}, detail=_MATCH_MATCH)
    calls = []

    def notify_fn(posting, *, token, chat_id):
        calls.append(posting["external_id"])
        raise RuntimeError("telegram 429")

    # Each pass retries the still-'scored' row; the 3rd cumulative failure
    # (NOTIFY_MAX_ATTEMPTS) parks it 'failed'.
    for expected_attempts, expected_status in ((1, "scored"), (2, "scored"), (3, "failed")):
        pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="test_token", chat_id="c")
        row = conn.execute("SELECT * FROM job_postings").fetchone()
        assert row["attempts"] == expected_attempts
        assert row["pipeline_status"] == expected_status
        assert "telegram" in row["pipeline_error"]
    assert calls == ["a", "a", "a"]
    # Parked rows are terminal: a further pass must not retry them.
    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token="test_token", chat_id="c")
    assert calls == ["a", "a", "a"]


def test_run_notify_retry_then_success_clears_error(db_path):
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90}, detail=_MATCH_MATCH)
    sends = []

    def flaky_notify(posting, *, token, chat_id):
        sends.append(posting["external_id"])
        if len(sends) == 1:
            raise RuntimeError("telegram 429")

    pipeline.run_notify(conn, now=NOW, notify_fn=flaky_notify, token="test_token", chat_id="c")
    pipeline.run_notify(conn, now=NOW, notify_fn=flaky_notify, token="test_token", chat_id="c")
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "notified"
    assert row["pipeline_error"] is None   # cleared on the successful send
    assert row["attempts"] == 1            # the earlier failure stays counted


def test_run_notify_scrubs_token_from_recorded_and_printed_error(db_path, capsys):
    # requests embeds the request URL (which carries the bot token) in its exception
    # text; run_notify writes str(exc) into pipeline_error (shown in the web Failed
    # bucket) and prints it — the token must never reach either sink.
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90}, detail=_MATCH_MATCH)
    token = "123456789:AAExampleSecretBotToken"

    def notify_fn(posting, *, token, chat_id):
        raise RuntimeError(
            "HTTPSConnectionPool: Max retries exceeded with url: "
            f"https://api.telegram.org/bot{token}/sendMessage")

    pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token=token, chat_id="c")

    err = conn.execute("SELECT pipeline_error FROM job_postings").fetchone()["pipeline_error"]
    assert token not in err and "***" in err
    out = capsys.readouterr().out
    assert token not in out and "***" in out


def test_stages_ignore_wrong_status_rows(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["n"])                                  # stays 'new'
    _seed_scored(conn, {"hi": 90}, detail=_MATCH_MATCH)      # match/match -> notifiable
    _seed_scored(conn, {"lo": 50}, detail={                 # not match/match -> ignored
        "assessment": {"seniority": {"verdict": "match"}, "domain": {"verdict": "adjacent"}},
    })

    notified = []
    pipeline.run_notify(
        conn, now=NOW, token="x", chat_id="y",
        notify_fn=lambda p, *, token, chat_id: notified.append(p["external_id"]),
    )
    assert notified == ["hi"]         # only 'scored' + match/match ('new' + non-matching ignored)
    statuses = {
        r["external_id"]: r["pipeline_status"]
        for r in conn.execute("SELECT * FROM job_postings").fetchall()
    }
    assert statuses["n"] == "new"
    assert statuses["lo"] == "scored"


# --- run_retry --------------------------------------------------------------

def test_run_retry_requeues_then_caps_at_retry_max_attempts(db_path):
    # A row that keeps failing SCREEN: each run_score pass parks it 'failed'
    # (attempts+1); run_retry requeues it to 'new' while attempts < RETRY_MAX_ATTEMPTS
    # (3) so it's rescored next pass. On the 3rd cumulative failure the cap is hit
    # and run_retry requeues NOTHING — permanently parked.
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    def screen_fn(posting):
        raise RuntimeError("ollama down")

    def fit_fn(postings):
        raise AssertionError("fit must not run — the screen failed")

    for expected_attempts in (1, 2, 3):
        pipeline.run_score(conn, now=NOW, screen_fn=screen_fn, fit_fn=fit_fn)
        row = conn.execute("SELECT * FROM job_postings").fetchone()
        assert row["attempts"] == expected_attempts
        assert row["pipeline_status"] == "failed"

        requeued = pipeline.run_retry(conn, now=NOW)
        if expected_attempts < pipeline.RETRY_MAX_ATTEMPTS:
            assert requeued == 1
            assert conn.execute(
                "SELECT pipeline_status FROM job_postings"
            ).fetchone()[0] == "new"
        else:
            assert requeued == 0    # cap hit — the 3rd failure never comes back
            assert conn.execute(
                "SELECT pipeline_status FROM job_postings"
            ).fetchone()[0] == "failed"


def test_run_retry_does_not_requeue_notify_exhausted_rows(db_path):
    # A row parked 'failed' via the NOTIFY_MAX_ATTEMPTS-th notify send failure has
    # attempts == 3 == RETRY_MAX_ATTEMPTS — the SAME shared counter — so it must
    # never requeue. No other code path writes pipeline_status='failed'.
    conn = db.connect(db_path)
    _seed_scored(conn, {"a": 90}, detail=_MATCH_MATCH)

    def failing_notify(posting, *, token, chat_id):
        raise RuntimeError("telegram 429")

    for _ in range(3):
        pipeline.run_notify(conn, now=NOW, notify_fn=failing_notify, token="t", chat_id="c")
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["attempts"] == 3
    assert row["pipeline_status"] == "failed"

    requeued = pipeline.run_retry(conn, now=LATER)
    assert requeued == 0
    assert conn.execute(
        "SELECT pipeline_status FROM job_postings"
    ).fetchone()[0] == "failed"


def test_run_retry_recovery_clears_pipeline_error_keeps_attempts(db_path):
    # fail once -> requeue -> the retry SCREEN survives and fit_fn succeeds ->
    # 'scored', pipeline_error cleared (None), attempts preserved at 1 (not reset).
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])

    def failing_screen(posting):
        raise RuntimeError("ollama down")

    pipeline.run_score(
        conn, now=NOW, screen_fn=failing_screen,
        fit_fn=lambda ps: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "failed"
    assert row["attempts"] == 1
    assert row["pipeline_error"]

    requeued = pipeline.run_retry(conn, now=LATER)
    assert requeued == 1

    def ok_screen(posting):
        return {"disqualified": False}

    def ok_fit(postings):
        return [{"score": 90, "assessment": _assessment()} for _ in postings]

    pipeline.run_score(conn, now=LATER, screen_fn=ok_screen, fit_fn=ok_fit)
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "scored"
    assert row["pipeline_error"] is None     # no stale error survives a recovery
    assert row["attempts"] == 1              # the earlier failure stays counted


def test_run_retry_sets_updated_at_to_passed_now(db_path):
    conn = db.connect(db_path)
    _seed_new(conn, ["1"])
    pid = conn.execute("SELECT id FROM job_postings").fetchone()[0]
    db.mark_failed(conn, pid, error="boom", now=NOW)

    requeued = pipeline.run_retry(conn, now=LATER)
    assert requeued == 1
    row = conn.execute("SELECT * FROM job_postings").fetchone()
    assert row["pipeline_status"] == "new"
    assert row["updated_at"] == LATER
