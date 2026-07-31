import pytest

from ats_worker import run
from tests._helpers import bootstrap_db


@pytest.fixture(autouse=True)
def _isolated_pass_lock(tmp_path, monkeypatch):
    """Every test that reaches run.main() takes the pass lock for real, so point the
    no-db fallback at a per-test temp file: the suite must not contend with a live
    pass on this host (nor leave a lock behind in the shared temp dir). A test that
    reaches main() is already isolated by its `--db`, which is where the real lock is
    keyed; this covers the paths that never name one. Tests that exercise the lock
    itself pass their own path explicitly."""
    monkeypatch.setattr(run, "_LOCK_PATH", tmp_path / "pass.lock")
    # And redirect the DEFAULT --db, which `main` reads from the environment. A test that
    # calls main() without naming one would otherwise resolve the operator's real
    # ../web/prisma/applications.db and leave a lock file in the live db/ directory —
    # observed, not hypothetical. Isolating it here covers every such test at once.
    monkeypatch.setenv("DB_PATH", str(tmp_path / "default-applications.db"))


@pytest.fixture
def db_path(tmp_path) -> str:
    """A temp, file-based SQLite db with the Prisma schema applied.

    File-based (not :memory:) so WAL-mode behaviour can be exercised. Schema
    bootstrap is shared with the integration tier via tests._helpers.bootstrap_db.
    """
    return bootstrap_db(tmp_path / "applications.db")
