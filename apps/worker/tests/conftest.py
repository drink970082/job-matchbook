import sqlite3
from pathlib import Path

import pytest

SCHEMA = (Path(__file__).parent / "fixtures" / "schema.sql").read_text()


@pytest.fixture
def db_path(tmp_path) -> str:
    """A temp, file-based SQLite db with the Prisma schema applied.

    File-based (not :memory:) so WAL-mode behaviour can be exercised.
    """
    path = tmp_path / "applications.db"
    boot = sqlite3.connect(path)
    boot.executescript(SCHEMA)
    boot.commit()
    boot.close()
    return str(path)
