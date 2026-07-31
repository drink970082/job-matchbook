# Contributing

Thanks for taking a look. This repo holds two cooperating services that share
one SQLite database:

| Service        | What it is                          | Stack                          |
| -------------- | ----------------------------------- | ------------------------------ |
| [`apps/web/`](./apps/web)       | The web app (tracker + dashboard)   | Next.js 14, Prisma, SQLite     |
| [`apps/worker/`](./apps/worker) | The semi-automated pipeline worker  | Python 3.11, pytest            |

See [`docs/SPEC.md`](./docs/SPEC.md) for the authoritative system spec
(architecture, data model, conventions, setup) and [`README.md`](./README.md) for
the product overview.

## Prerequisites

- Node.js 20+ and npm
- Python 3.11+
- (Optional, for the full pipeline) Docker + Docker Compose, Ollama, and either
  the Codex CLI (`codex login` — the default fit-score backend) or an
  Anthropic API key (`SCORE_BACKEND=claude`, metered alternate)

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
(Ollama, the Codex CLI, Claude, Telegram) is mocked, so it runs anywhere
Python + pytest exist, with no network and no API keys.

CI (`.github/workflows/ci.yml`) runs both suites on every pull request, on pushes
to `main`, and nightly. Pushes to a feature branch do **not** trigger it — open the
PR to get a run.

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
- **Worker dependencies**: any new module-load or test-exercised runtime import
  MUST be mirrored into `apps/worker/requirements-dev.txt` in the same commit
  that adds it to `requirements.txt` — the two files duplicate their pins (no
  include mechanism exists without adding tooling), and that duplication has
  broken CI once already (the `geonamescache` fix in the
  [CHANGELOG](./CHANGELOG.md)).

## Branching and releases

`main` is the only long-lived branch, and it is always releasable.

```bash
git switch -c feat/dead-link-sweep main   # feat/ · fix/ · docs/ · chore/
# ... commits ...
gh pr create --fill                       # CI runs; squash-merge when green
```

- **Pull requests** are the norm for anything substantive — they're squash-merged
  (one commit per PR on `main`) and the branch is deleted automatically. Small doc
  fixes may be pushed straight to `main`.
- **`main` is protected**: CI (`Web` + `Worker`) must pass, force-pushes and branch
  deletion are blocked, and history stays linear. Long-lived `dev`/`release/*`
  branches are deliberately not used.
- **Agent sessions** follow the same rules plus a few extra guards (claiming work
  through `PROGRESS.md`, verifying a PR's base, the squash-divergence conflict recipe,
  and what a session may merge on its own): [`docs/DEVELOPMENT.md`](./docs/DEVELOPMENT.md)
  §7.
- **Releases** are [SemVer](https://semver.org/) tags on `main`. To cut one: move
  `CHANGELOG.md`'s `[Unreleased]` entries into a new dated version section, bump the
  version in `apps/web/package.json` and `apps/worker/pyproject.toml`, tag, then
  `gh release create vX.Y.Z` with that section as the notes.

## Keeping your real resume private

All of `apps/worker/resume/` is gitignored; the only tracked files there are
`README.md`, `resume.txt.example`, and `personal_profile.txt.example`. Copy the
template to get started:

```bash
cd apps/worker
cp resume/resume.txt.example resume/resume.txt
```

See `apps/worker/resume/README.md` for the multi-resume convention (multiple
targeted versions, the optional profile file, and how labels are derived).

Secrets (`apps/worker/.env`), the résumé (`apps/worker/resume/`), and the
database (`db/`) are gitignored — never commit them.
