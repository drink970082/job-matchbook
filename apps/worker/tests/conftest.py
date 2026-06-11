import pytest

from tests._helpers import bootstrap_db


@pytest.fixture
def db_path(tmp_path) -> str:
    """A temp, file-based SQLite db with the Prisma schema applied.

    File-based (not :memory:) so WAL-mode behaviour can be exercised. Schema
    bootstrap is shared with the integration tier via tests._helpers.bootstrap_db.
    """
    return bootstrap_db(tmp_path / "applications.db")
