"""Guard the third watchlist write boundary: the onboard-board CLI.

`.claude/skills/onboard-board/scripts/add_watched.py` writes `args.slug` straight to
`db.import_watchlist`. Unlike the web (`actions.ts`) and worker-config (`config.py`)
write boundaries, it never validated the slug charset — an unsafe slug scraped from an
untrusted careers page (e.g. a host-injection payload) could land in `watched_companies`
and get interpolated into a fetch URL every cycle. This test loads the *real* script (not
a copy) via importlib, since it lives outside the `ats_worker` package and outside CI's
normal collection root.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from ats_worker import config, db
from tests._helpers import NOW

SCRIPT = Path(__file__).resolve().parents[3] / ".claude/skills/onboard-board/scripts/add_watched.py"

_spec = importlib.util.spec_from_file_location("add_watched", SCRIPT)
add_watched = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(add_watched)


def test_add_watched_rejects_unsafe_slug():
    # Host-injection payload: an unsafe slug must be rejected BEFORE any DB access —
    # no --db is passed, so a real add would blow up on the missing-DB check first if
    # the slug guard weren't running earlier.
    with pytest.raises(SystemExit):
        add_watched.main(["--source", "workday", "--slug", "x@evil:80/../y", "--name", "Evil"])


def test_add_watched_accepts_clean_slug(tmp_path):
    db_path = tmp_path / "applications.db"
    from tests._helpers import bootstrap_db
    bootstrap_db(db_path)

    add_watched.main([
        "--source", "greenhouse", "--slug", "acme", "--name", "Acme", "--db", str(db_path),
    ])

    conn = db.connect(str(db_path))
    rows = db.get_watchlist(conn)
    assert [r["slug"] for r in rows] == ["acme"]
