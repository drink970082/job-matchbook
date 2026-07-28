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
              http_get=_http_ok, connect=sqlite3.connect, db_path=":memory:",
              run_cmd=lambda argv: (0, "active\n"))
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


def test_the_daemon_row_reports_the_systemd_user_unit_but_never_fails_the_exit_code():
    # An unsupervised checkout is a legitimate way to use this — hand-run `--once` is
    # documented — so the row is informational like the other provider rows. It exists
    # because a daemon that is NOT running looks identical to one merely waiting for its
    # next wall-clock slot: the pipeline prints nothing either way.
    [row] = [c for c in _run() if c.label == "worker daemon (systemd unit)"]
    assert row.ok is True and row.core is False
    assert "active" in row.detail

    [row] = [c for c in _run(run_cmd=lambda argv: (3, "inactive\n"))
             if c.label == "worker daemon (systemd unit)"]
    assert row.ok is False and row.core is False
    assert "inactive" in row.detail
    assert "ats-worker.service.example" in row.detail   # says where to go next


def test_the_daemon_row_asks_systemd_the_user_scoped_question():
    # `systemctl is-active ats-worker` without --user queries the SYSTEM manager, which
    # on a machine with no system-wide unit answers "inactive" — reporting a correctly
    # running user daemon as down.
    seen = []
    _run(run_cmd=lambda argv: (seen.append(argv), (0, "active"))[1])
    assert seen == [["systemctl", "--user", "is-active", "ats-worker"]]


def test_a_host_without_systemd_reports_the_daemon_row_soft_rather_than_crashing(
        monkeypatch, tmp_path, capsys):
    # doctor's whole job is diagnosing a broken checkout, so it must survive a host where
    # `systemctl` does not exist at all (a container, a non-systemd distro, WSL without
    # systemd enabled). This drives the REAL main(), not an injected fake: the mapping
    # from FileNotFoundError to a soft row lives in main()'s run_cmd closure, so injecting
    # `(1, "unavailable")` into run_checks would assert nothing about the code that has to
    # catch it — delete the except clause and an injected test still passes while
    # `make doctor` dies with a traceback.
    import subprocess
    real_run = subprocess.run

    def boom(argv, **kw):
        if argv and argv[0] == "systemctl":
            raise FileNotFoundError(2, "No such file or directory", "systemctl")
        return real_run(argv, **kw)

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.chdir(tmp_path)
    assert doctor.main([]) == 1          # core DB row fails in an empty dir, not a crash
    out = capsys.readouterr().out
    assert "worker daemon (systemd unit)" in out
    assert "unavailable" in out


def test_the_daemon_dep_row_flags_apscheduler_before_the_unit_crash_loops():
    # apscheduler is deliberately out of _WORKER_DEPS (`--once` never imports it), so a
    # checkout installed from requirements-dev alone passes every other row and then
    # crash-loops as a systemd unit ~2.5 min after a clean `enable`. Soft, because a
    # hand-run workflow genuinely does not need it.
    [row] = [c for c in _run(find_spec=lambda n: None if n == "apscheduler" else object())
             if c.label == "daemon dep"]
    assert row.ok is False and row.core is False
    assert "crash-loop" in row.detail

    [row] = [c for c in _run() if c.label == "daemon dep"]
    assert row.ok is True
