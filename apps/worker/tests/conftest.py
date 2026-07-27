import pytest

from ats_worker import run
from tests._helpers import bootstrap_db


# The shipped default, captured at import before the autouse fixture below redirects it.
# Without this nothing in the suite can assert where the lock actually lives, and it
# could silently move under db/ (bind-mounted into the web container) unnoticed.
SHIPPED_LOCK_PATH = run._LOCK_PATH


@pytest.fixture(autouse=True)
def _isolated_pass_lock(tmp_path, monkeypatch):
    """Every test that reaches run.main() takes the pass lock for real, so point it
    at a per-test temp file: the suite must not contend with a live pass on this
    host (nor leave a lock behind in the shared temp dir). Tests that exercise the
    lock itself pass their own path explicitly."""
    monkeypatch.setattr(run, "_LOCK_PATH", tmp_path / "pass.lock")


@pytest.fixture
def db_path(tmp_path) -> str:
    """A temp, file-based SQLite db with the Prisma schema applied.

    File-based (not :memory:) so WAL-mode behaviour can be exercised. Schema
    bootstrap is shared with the integration tier via tests._helpers.bootstrap_db.
    """
    return bootstrap_db(tmp_path / "applications.db")
