# Contributing

Thanks for taking a look. This repo holds two cooperating services that share
one SQLite database:

| Service        | What it is                          | Stack                          |
| -------------- | ----------------------------------- | ------------------------------ |
| [`apps/web/`](./apps/web)       | The web app (tracker + dashboard)   | Next.js 14, Prisma, SQLite     |
| [`apps/worker/`](./apps/worker) | The semi-automated pipeline worker  | Python 3.11, pytest            |

See [`README.md`](./README.md) for the product overview and
[`docs/SETUP.md`](./docs/SETUP.md) for full environment setup.

## Prerequisites

- Node.js 20+ and npm
- Python 3.11+
- (Optional, for the full pipeline) Docker + Docker Compose, Ollama, `tectonic`

## Getting started

```bash
make install        # web deps
make db-push        # create/sync the SQLite schema
make dev            # http://localhost:3000
```

`make help` lists every target. Each wraps the underlying per-service command,
so you can always drop into `apps/web/` or `apps/worker/` and run npm/pytest
directly.

## Running the tests

```bash
make test           # both suites
make test-web       # Jest  (cd apps/web && npm test)
make test-worker    # pytest (cd apps/worker && python -m pytest)
```

The worker suite is **fully dependency-injected** — every external service
(Ollama, Claude, Telegram) and binary (`tectonic`, `pypdf`) is mocked, so it
runs anywhere Python + pytest exist, with no network and no API keys.

CI (`.github/workflows/ci.yml`) runs both suites on every push and pull request.

## Conventions

- **TypeScript / React**: 2-space indent; follow the existing component and
  Server-Action patterns in `apps/web/src/`. Run `make lint` before pushing.
- **Python**: 4-space indent; keep modules pure and inject externals (the test
  suite depends on this). Wiring to real services lives only in
  `ats_worker/run.py`.
- **Database schema** is owned solely by Prisma
  (`apps/web/prisma/schema.prisma`). The worker reads/writes rows but issues no
  DDL. Change the schema there, then `make db-push`.
- **Commits**: short imperative subject, optional `type(scope):` prefix
  (e.g. `feat(worker): ...`, `fix(web): ...`). Keep each commit self-consistent
  and green.

## Keeping your real resume private

The worker ships template `resume/master.tex` and `resume/resume.txt` so a clean
clone runs out of the box. Replace them with your real resume locally, but keep
your edits out of git:

```bash
cd apps/worker
git update-index --skip-worktree resume/master.tex resume/resume.txt
```

Secrets (`apps/worker/.env`), the database (`db/`), and tailored output
(`resumes/`) are gitignored — never commit them.
