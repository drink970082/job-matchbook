"""Guard against drift between the worker's test schema and the real Prisma schema.

The worker bootstraps test databases from tests/fixtures/schema.sql, a hand-kept
copy of apps/web/prisma/schema.prisma (Prisma owns the real schema — there are no
migrations). If a column is added to Prisma but not mirrored here, worker tests
would pass against a schema production never uses. This test fails loudly on any
such drift (it's how the missing status_history table was caught).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SCHEMA_SQL = Path(__file__).parent / "fixtures" / "schema.sql"
PRISMA = Path(__file__).parents[3] / "apps" / "web" / "prisma" / "schema.prisma"


def _prisma_models() -> dict[str, set[str]]:
    """Map model name -> set of SCALAR field names (relation fields excluded)."""
    # Strip // comments first: some contain { } (e.g. the score_detail JSON shape)
    # that would otherwise prematurely close the brace-matched model body.
    text = re.sub(r"//.*", "", PRISMA.read_text())
    models = dict(re.findall(r"model\s+(\w+)\s*\{(.*?)\}", text, re.S))
    names = set(models)
    out: dict[str, set[str]] = {}
    for name, body in models.items():
        fields: set[str] = set()
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("@@") or line.startswith("//"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            field, ftype = parts[0], parts[1].rstrip("?").rstrip("[]").rstrip("?")
            if ftype in names:   # a relation field, not a column
                continue
            fields.add(field)
        out[name] = fields
    return out


def _sql_tables() -> dict[str, set[str]]:
    """Map table name -> set of column names from CREATE TABLE statements."""
    text = SCHEMA_SQL.read_text()
    out: dict[str, set[str]] = {}
    for tname, body in re.findall(r'CREATE TABLE "(\w+)"\s*\((.*?)\n\);', text, re.S):
        cols: set[str] = set()
        for line in body.splitlines():
            line = line.strip()
            m = re.match(r'"(\w+)"', line)
            if m and not line.startswith("CONSTRAINT"):
                cols.add(m.group(1))
        out[tname] = cols
    return out


@pytest.mark.skipif(not PRISMA.exists(), reason="prisma schema not present")
def test_schema_sql_matches_prisma_models():
    prisma = _prisma_models()
    sql = _sql_tables()
    for model, fields in prisma.items():
        assert model in sql, f"schema.sql is missing table {model!r} (Prisma drift)"
        missing = fields - sql[model]
        assert not missing, f"schema.sql {model!r} missing columns {sorted(missing)} (Prisma drift)"
        extra = sql[model] - fields
        assert not extra, f"schema.sql {model!r} has columns {sorted(extra)} not in Prisma"
