"""Preflight (`ats_worker.doctor`): status-line report, core-hard exit semantics."""
import sqlite3

from ats_worker import doctor


def _find_all(name):      # every dep present
    return object()


def _find_none(name):     # every dep missing
    return None


def _http_ok(url):
    return type("R", (), {"status_code": 200})()


def _http_raise(url):
    raise ConnectionError("refused")


def _by_label(checks):
    return {c.label: c for c in checks}


def _make_db(path, *, with_table=True):
    conn = sqlite3.connect(path)
    if with_table:
        conn.execute("CREATE TABLE job_postings (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()


def _run(**over):
    kw = dict(env={}, find_spec=_find_all, which=lambda c: f"/usr/bin/{c}",
              http_get=_http_ok, connect=sqlite3.connect, db_path=":memory:")
    kw.update(over)
    # :memory: has no job_postings table, so default db_row is a miss unless overridden
    return doctor.run_checks(**kw)


def test_all_present_no_core_failure(tmp_path):
    db = tmp_path / "applications.db"
    _make_db(str(db))
    checks = _run(db_path=str(db),
                  env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c",
                       "ANTHROPIC_API_KEY": "k", "OPENAI_API_KEY": "k"})
    assert all(c.ok for c in checks)
    assert [c for c in checks if c.core and not c.ok] == []


def test_missing_dep_is_core_failure():
    row = _by_label(_run(find_spec=_find_none))["worker python deps"]
    assert row.core and not row.ok and "make setup" in row.detail


def test_missing_db_file_is_core_failure(tmp_path):
    row = _by_label(_run(db_path=str(tmp_path / "nope.db")))["database"]
    assert row.core and not row.ok and "make setup" in row.detail


def test_db_without_table_is_core_failure(tmp_path):
    db = tmp_path / "empty.db"
    _make_db(str(db), with_table=False)
    row = _by_label(_run(db_path=str(db)))["database"]
    assert row.core and not row.ok


def test_ollama_unreachable_is_soft(tmp_path):
    db = tmp_path / "applications.db"
    _make_db(str(db))
    row = _by_label(_run(db_path=str(db), http_get=_http_raise))["ollama"]
    assert not row.ok and not row.core  # provider row: never fails the exit code
    assert [c for c in _run(db_path=str(db), http_get=_http_raise)
            if c.core and not c.ok] == []


def test_telegram_optional_and_soft():
    both = _by_label(_run(env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}))
    assert both["telegram"].ok
    partial = _by_label(_run(env={"TELEGRAM_BOT_TOKEN": "t"}))  # chat id missing
    assert not partial["telegram"].ok and not partial["telegram"].core


def test_main_exit_zero_when_core_ok(tmp_path, monkeypatch, capsys):
    db = tmp_path / "applications.db"
    _make_db(str(db))
    monkeypatch.chdir(tmp_path)              # no .env here -> {}
    monkeypatch.setenv("DB_PATH", str(db))
    assert doctor.main() == 0
    assert "[ok] worker python deps" in capsys.readouterr().out


def test_main_exit_one_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "nope.db"))
    assert doctor.main() == 1
