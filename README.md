# Job Matchbook

**Your job sources, evidence and application history — available to your AI assistant.**

[![CI](https://github.com/drink970082/job-matchbook/actions/workflows/ci.yml/badge.svg)](https://github.com/drink970082/job-matchbook/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Job Matchbook collects jobs from official company boards, stores their descriptions,
and tracks applications in a self-hosted SQLite database. Its MCP tools let an AI
assistant such as ChatGPT inspect jobs and application history for personal analysis and
a Daily Job Brief. Hard-requirements screening and a JEV keep/skip filter are available
as **optional assistance**.

> **Collect and preserve job evidence → query with your AI assistant → review and apply by hand → track.**

AI-led judgment and delivery are the product direction, not a claim that every roadmap
feature is implemented; see the [feature readiness matrix](docs/ROADMAP.md#feature-readiness).

<p align="center">
  <img src="docs/images/dashboard.png" alt="Current tracker dashboard" width="900">
</p>

## What is available

- **Discover:** scheduled watchlists and public discovery feeds, official-board JD
  retrieval, generic HTTP/browser recipes and unresolved-source records.
- **Read with ChatGPT:** ten bounded read-only MCP tools covering postings, full JD
  chunks, standalone screenings, applications/history and the other ATS record types.
- **Track:** manual application entry, Mark Applied, status history, CSV import/export,
  KPIs and charts; a web-managed watchlist.
- **Assist optionally:** hard-requirement screening (local Ollama by default, or a
  CLI/API backend) and the paid JEV keep/skip filter (OpenRouter).
- **Write API:** a key-scoped loopback `/api/v1` for applications and the watchlist,
  off until a key is set. MCP write tools on top of it are planned (#154).

A scheduled assistant task must be configured and tested separately for unattended daily
delivery. MCP tools are read-only today. Cross-day deduplication is best-effort until a
persistent delivery ledger exists.

No auto-apply, no public multi-tenant service and no CAPTCHA workarounds. Private
configuration, résumé files and databases are gitignored. A hosted screen backend
receives JD text and your hard requirements, the JEV filter sends JD text and your
private `jev_dir` profile to OpenRouter, and connecting an assistant exposes
the data returned by the enabled MCP tools to that chat.

## Quick start

**Tracker only** — no worker or model required:

```bash
make install && make db-push && make dev     # http://localhost:3000
```

**Discovery and optional assistance** — native Python worker plus web app:

```bash
make setup     # dependencies, DB and non-clobbering private config templates
make doctor    # inspect prerequisites for the selected path
make up        # web app in Docker; does not start the native worker
cd apps/worker
python -m ats_worker.run --fetch-only --once
```

Fetch-only calls no model, but still uses configured intake filters and the existing
expiry/retry flow.

To opt into standalone subscription-backed screening:

```bash
python -m ats_worker.run --screen-only --screen-backend codex \
  --screen-model gpt-5.6-luna --screen-effort medium --screen-limit 40 --once
```

Run `codex login` on the host first. `--screen-unlimited` is an explicit alternative to
`--screen-limit`, not unlimited subscription entitlement. Read [SETUP](docs/SETUP.md)
before enabling a metered provider or the JEV filter (`--jev`).

## Sources and components

11 platform adapters: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable,
Pinpoint, iCIMS, Phenom, Oracle and Jobvite; plus custom HTTP and browser recipes.
Oracle/Jobvite resolve feed listings rather than per-company watchlist rows.

Next.js 14 / React 18 / Prisma 6 / SQLite web app; Python 3.11 native worker;
stdio MCP through a private tunnel; Docker Compose for web/autoheal.
See [current and target architecture](docs/ARCHITECTURE.md) and the detailed
[implementation specification](docs/SPEC.md).

## Documentation

| Document | Purpose |
|---|---|
| [Architecture](docs/ARCHITECTURE.md) | Ownership boundary and current implementation |
| [Roadmap](docs/ROADMAP.md) | Feature readiness and delivery order |
| [Pivot decision](docs/superpowers/specs/2026-10-22-chatgpt-first-pivot-design.md) | Approved ChatGPT-primary direction |
| [Setup](docs/SETUP.md) | Tracker, discovery, optional screen/JEV, MCP and write-API paths |
| [Spec](docs/SPEC.md) | Shipped capabilities, contracts, data model and operational reference |
| [Progress](docs/PROGRESS.md) | Branch claims, next work and current limitations |
| [Backlog](docs/BACKLOG.md) | Open and deferred work |
| [Evaluation](docs/EVALUATION.md) | Which checks apply, eval tools and private corpus limitations |
| [Scoring reference](docs/SCORING.md) | Screen contracts and measured failure modes |
| [Principles](docs/PRINCIPLES.md) / [Development](docs/DEVELOPMENT.md) | Design and contribution protocol |
| [Rejected proposals](docs/REJECTED.md) | Negative findings to consult before redesign |
| [Contributing](CONTRIBUTING.md) / [Security](SECURITY.md) | Tests, conventions and accepted-risk scope |
| [Changelog](CHANGELOG.md) | Release history |

[MIT license](LICENSE) · [Code of conduct](CODE_OF_CONDUCT.md)
