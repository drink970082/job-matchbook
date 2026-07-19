# Audit Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **This plan is long and self-contained — execute it phase by phase across as many sessions as needed. Each task ends green and committed, so you can stop after any task and resume cold.**

**Goal:** Fix every finding in the 2026-07-18 security / dead-code / architecture audit (recorded in `docs/PROGRESS.md`), from stopping the live PII exposure to the large module refactors, in risk order.

**Architecture:** Six phases, hardest-blast-radius-first for containment then easiest-first within each phase. Phase 0 stops active exposure (public PII, open bind, token leak). Phases 1–2 fix correctness defects and harden the security surface. Phase 3 deletes dead code. Phase 4 does the small, safe architecture fixes. Phase 5 does the three large behavior-preserving refactors. Every task is TDD (failing test → fix → green → commit) except operator shell actions and pure refactors, whose safety net is the existing suite staying green.

**Tech Stack:** Next.js 14 + Prisma 6 + SQLite (TS, Jest + Testing Library + Playwright) · Python 3.11 worker (pytest, fully mocked) · Docker Compose · GitHub Actions CI.

## Global Constraints

*Every task's requirements implicitly include this section.*

- **Prisma owns the schema.** The worker issues **no DDL**. To change the schema: edit `apps/web/prisma/schema.prisma` → `make db-push` → update the worker drift fixture `apps/worker/tests/fixtures/schema.sql` → keep both drift guards green (`tools/check_schema_drift.mjs` + `apps/worker/tests/test_schema_sync.py`, run via `make check-schema`).
- **Worker modules are pure + dependency-injected.** Real network/DB/service clients are wired **only** in `apps/worker/ats_worker/run.py`; tests mock everything (no network, no keys).
- **Status/category/source enums** live in `apps/web/src/lib/constants.ts` (web) and are mirrored in `apps/worker/ats_worker/config.py` + `fetch/__init__.py` (worker). Changing one side means changing the mirror.
- **Indentation:** web TS = 2 spaces; worker Python = 4 spaces. Run `make lint` (web) before pushing.
- **Coverage gates stay green:** worker `fail_under = 85` (`apps/worker/pyproject.toml`); web gated via `jest.all.config.ts`. Deleting production code means deleting or re-homing its tests without dropping below the gate.
- **Commits:** short imperative subject with a `type(scope):` prefix (`fix(web): …`, `refactor(worker): …`, `docs: …`). **Each commit must be green.** Git identity: `drink970082 <howdywu@gmail.com>` — never `cw555`.
- **Docs move with the code, same commit.** When a defect is fixed: **remove** its line from `docs/PROGRESS.md`, add a `docs/CHANGELOG.md` entry (under `## [Unreleased]`, correct `Added`/`Changed`/`Fixed`/`Removed` group), and update the matching `docs/SPEC.md` section if a behavior/capability/§11 claim changed. A fixed defect *leaves* PROGRESS.
- **Privacy:** never commit `apps/worker/.env`, `apps/worker/config.yaml`, `apps/worker/resume/`, or `db/` (all gitignored).
- **Test runners:** worker via `rtk proxy python3 -m pytest apps/worker/tests/...` (RTK mis-summarizes bare pytest — bypass it); web via `cd apps/web && npx jest ...` or `make test-web`; e2e `make test-e2e`; schema `make check-schema`.
- **Branch:** work on `dev` (long-lived); push to `origin/dev`. `master` stays behind by design — do not target it (CI is being fixed to run on `dev` in Phase 1).

## Phase map

| Phase | Theme | Why here | Risk |
|-------|-------|----------|------|
| **0** | Containment | Stop active exposure: public PII, `0.0.0.0` bind, token leak, debris | Low code risk, high urgency |
| **1** | Correctness defects | Shipped behavior that is wrong (data loss, silent swallow, CI gap) | Low |
| **2** | Security hardening | SSRF, `javascript:` URLs, CVE bump, injection seams, input validation | Low–med |
| **3** | Dead code removal | Delete ~120 production lines + debris (and their tests) | Low (verify no caller) |
| **4** | Small architecture | Drift guard, indexes, transactions, `busy_timeout`, DI cleanup | Med (one schema change) |
| **5** | Large refactors | Split `score.py` (1089 ln) + `Dashboard.tsx` (720 ln); dedup adapters | Med — behavior-preserving, suite is the net |

**Ordering rule within a phase:** easiest-first (XS → L). **Do not start Phase N+1 until Phase N is green and committed** — except Phase 0a (repo-private) which is do-it-right-now.

**Progress tracking:** as each task's docs step removes a line from `docs/PROGRESS.md`, that file *is* the live burndown — when its Defects/Unverified buckets and the two audit sub-sections under Enhancements are empty, the plan is done.

---

## Execution order & cross-phase reconciliation

Read this before starting — it resolves dependencies between phases.

- **Do phases in order; each task ends green + committed.** The only immediate action is **Task 0a** (repo → private). **Phase 4 must run before Phase 5** (Phase 4 edits `score.py` in place; Phase 5 then splits it into a package).
- **CHANGELOG convention:** many tasks add a `### Security` / `### Fixed` / `### Removed` / `### Added` / `### Changed` group under `## [Unreleased]`. **Create the group if absent, append if present** — never duplicate a heading.
- **`score_posting` is removed in Phase 3, before Phase 5.** So in Phase 5's `score/screen.py` extraction, **drop `score_posting` from the re-export surface** and don't carry it — it no longer exists. (Only if Phase 3's `score_posting` task was skipped do you carry it as the Phase 5 task text describes.)
- **Phase 4 removes `import requests` from `score.py`** (the DI task turns the two `http=requests` defaults into `http=None`). So in Phase 5's `score/screen.py` import list, **`requests` is not needed** (`_post` uses the injected `http`) — reconcile every Phase 5 module's import list against the actual post-Phase-4 source you read, not against the pre-audit line numbers.
- **`applications` `@@unique(company_name, job_title)` is deferred, not added** (Phase 4 decision): the real table may already hold duplicate (company, title) pairs from re-applications, so a hard unique needs a backup + dedupe migration (`prisma db push` would otherwise error / demand `--accept-data-loss`). Phase 4 instead makes `addApplication` transactional and records the hard-unique as a deferred schema change. **Operator: confirm you're OK deferring this.**
- **Line numbers drift as you edit.** Every task cites line numbers from the pre-remediation source; after earlier commits they shift. Trust the *quoted before-code*, not the number — grep for the snippet.

### Accepted / no task (documented in PROGRESS, deliberately not fixed)

- **autoheal holds the Docker socket** (`docker-compose.yml:41-51`) — deliberate local-only design; highest-privilege component but accepted as-is.
- **`requirements-dev.txt` base-pin duplication** — no include mechanism (`-r requirements.txt` minus heavy deps isn't expressible); accepted.
- **DNS-rebinding** is out of scope for the `is_safe_public_url` SSRF guard (pure, no DNS lookup) — documented accepted-residual (Phase 2), as is the `phenom`/`workday` internal-IP-host slug case.
- **Pre-existing standing items, NOT part of this audit** (out of scope for this plan; they predate it and stay in PROGRESS): JD prompt-injection (structurally closed, accepted), stale-mount recovery live drill, and the no-schema-migration-path `[L]` item.

---

## Phase 0 — Containment

*Stop active exposure first. Task 0a is immediate; the rest are quick and low-risk.*

### Task 0.1: Gitignore the untracked debris  [Phase 0]
**Files:** Modify `/home/halcyon/root/ats/.gitignore` (append after line 33)
*(Operator/config task — no automated test.)*

- [ ] Step 1: Confirm the debris is currently un-ignored (should print nothing):
  `cd /home/halcyon/root/ats && git check-ignore .playwright-mcp/ scrape_board.txt || echo "NOT IGNORED"`
- [ ] Step 2: Append to `.gitignore` (current file ends at line 33 `.claude/skills/*-workspace/`):
  ```
  # Untracked local scratch/debris — never commit (2026-07-18 audit).
  .playwright-mcp/
  scrape_board.txt
  ```
- [ ] Step 3: Verify both are now ignored and gone from `git status`:
  `git check-ignore .playwright-mcp/ scrape_board.txt` (prints both) and `git status --porcelain | grep -E 'playwright-mcp|scrape_board' || echo "clean"`
- [ ] Step 4: Docs — in `docs/PROGRESS.md` remove the two "Dead code / debris" bullets (`.playwright-mcp/ — untracked, not gitignored` and `scrape_board.txt — untracked scratch, not gitignored`). No CHANGELOG entry needed (pure repo hygiene, no shipped behavior).
- [ ] Step 5: Commit:
  ```
  git add .gitignore docs/PROGRESS.md
  git commit -m "chore: gitignore .playwright-mcp/ and scrape_board.txt"
  ```

### Task 0.2: Bind the published web port to loopback only  [Phase 0]
**Files:** Modify `/home/halcyon/root/ats/docker-compose.yml:13-14`
*(Config task — no automated test; single-user localhost, deliberately NO auth layer per the non-goal.)*

- [ ] Step 1: Confirm current exposure — `docker-compose.yml:13-14` publishes on all interfaces:
  ```yaml
      ports:
        - "3000:3000"
  ```
- [ ] Step 2: Replace with a loopback bind:
  ```yaml
      ports:
        # Loopback only — single-user localhost, no auth layer (a non-goal). Publishing
        # on 0.0.0.0 exposes the 26 unauthenticated server actions to any LAN peer.
        # See docs/SPEC.md §6 / §11.
        - "127.0.0.1:3000:3000"
  ```
- [ ] Step 3: Verify Compose resolves the loopback bind:
  `cd /home/halcyon/root/ats && docker compose config | grep -A2 'published'` → shows `published: "3000"`, `host_ip: 127.0.0.1`. (If the stack is up: `docker port ats-web` → `127.0.0.1:3000`.)
- [ ] Step 4: Docs — remove the `docs/PROGRESS.md` defect bullet ("Web UI published on `0.0.0.0` with no auth"). Add a CHANGELOG line under a `### Security` heading in `## [Unreleased]`:
  ```
  ### Security
  - **Web UI is published on loopback only (`127.0.0.1:3000`).** The Compose port bind
    was `0.0.0.0:3000`, exposing the unauthenticated server actions to any LAN peer;
    it now binds `127.0.0.1` (single-user localhost, no-auth is a non-goal). (SPEC §6/§11.)
  ```
  If SPEC §6/§11 states the bind, adjust that sentence to say loopback.
- [ ] Step 5: Commit:
  ```
  git add docker-compose.yml docs/PROGRESS.md CHANGELOG.md
  git commit -m "fix(web): bind published web port to loopback only"
  ```

### Task 0a: Make the public repo private (instant containment)  [Phase 0]
**Files:** none — GitHub repo setting via `gh`.
*(Operator shell action. Do this FIRST of the two PII tasks: it stops exposure immediately while 0b's history rewrite is prepared. No test, no commit.)*

- [ ] Step 1: Confirm current visibility:
  `gh repo view drink970082/personal-ats --json visibility -q .visibility` → expect `public`
- [ ] Step 2: Flip to private (newer `gh` prompts for confirmation / may need the consequences flag):
  `gh repo edit drink970082/personal-ats --visibility private --accept-visibility-change-consequences`
- [ ] Step 3: Verify:
  `gh repo view drink970082/personal-ats --json visibility -q .visibility` → `private`
- [ ] Safety note: This is containment, NOT eradication — the résumé/config blobs still exist in history and in any existing clone/fork. Do NOT close the PROGRESS "public git history" bullet on this step; it closes only after 0b.

### Task 0b: Rewrite git history to purge PII  [Phase 0]
**Files:** none — rewrites `origin/dev` + `origin/master` history.
*(Operator shell action. Destructive + force-push. No test, no ordinary commit. Requires `git-filter-repo` installed.)*

- [ ] Step 1: Full backup mirror first (recovery point if the rewrite goes wrong):
  `git clone --mirror https://github.com/drink970082/personal-ats.git /tmp/personal-ats-backup.git`
- [ ] Step 2: Confirm the target blobs are actually in history:
  `cd /home/halcyon/root/ats && git log --all --oneline -- apps/worker/resume/resume.txt apps/worker/config.yaml`
- [ ] Step 3: Strip the two paths from ALL history:
  `git filter-repo --path apps/worker/resume/resume.txt --path apps/worker/config.yaml --invert-paths`
  (filter-repo removes the `origin` remote by design.)
- [ ] Step 4: Re-add origin and force-push both branches:
  ```
  git remote add origin https://github.com/drink970082/personal-ats.git
  git push --force origin dev master
  ```
- [ ] Step 5: Verify the blobs are gone from history:
  `git log --all --oneline -- apps/worker/resume/resume.txt apps/worker/config.yaml` → empty
- [ ] Safety notes (do NOT skip):
  - **GitHub caches old blobs** — force-push does not purge them from cached views/PRs; open a GitHub Support request to purge cached views and check for forks.
  - **ROTATE any secret that lived in `config.yaml`** as a precaution (per the audit, `config.yaml` held companies/candidate config, not API keys/tokens — but rotate anything you're unsure of; `.env`/secrets were never in history).
  - **This breaks every existing clone** — re-sync the working checkout (`git fetch origin && git reset --hard origin/dev`) and re-clone any other copy.
- [ ] Step 6: Docs — in a normal follow-up commit, remove the `docs/PROGRESS.md` defect bullet ("Real résumé + `config.yaml` are in public git history") and add under CHANGELOG `### Security`:
  ```
  - **Removed real résumé + `config.yaml` from git history.** `apps/worker/resume/resume.txt`
    and the real `config.yaml` (committed 2026-06-05, untracked 2026-06-08) were purged from
    all history with `git filter-repo` and force-pushed; the repo was also made private as
    immediate containment. (SPEC §3/§11, Privacy-first.)
  ```
  ```
  git add docs/PROGRESS.md CHANGELOG.md
  git commit -m "docs: record PII history purge + repo-private containment"
  ```

### Task 0.5: Scrub the Telegram bot token from recorded/printed notify errors  [Phase 0]
**Files:** Modify `/home/halcyon/root/ats/apps/worker/ats_worker/pipeline.py:380-387` · Test `/home/halcyon/root/ats/apps/worker/tests/test_pipeline.py`
**Interfaces:** `run_notify(conn, *, now, notify_fn, token, chat_id)` — `token` already in scope, so the scrub is a pure choke-point fix; `db.record_notify_failure(...)`/stdout unchanged.

- [ ] Step 1: Add the failing test to `tests/test_pipeline.py` (reuses the existing `_MATCH_MATCH` detail constant + `_seed_scored` helper; place beside the other `run_notify` tests):
  ```python
  def test_run_notify_scrubs_token_from_recorded_and_printed_error(db_path, capsys):
      # requests embeds the request URL (which carries the bot token) in its exception
      # text; run_notify writes str(exc) into pipeline_error (shown in the web Failed
      # bucket) and prints it — the token must never reach either sink.
      conn = db.connect(db_path)
      _seed_scored(conn, {"a": 90}, detail=_MATCH_MATCH)
      token = "123456789:AAExampleSecretBotToken"

      def notify_fn(posting, *, token, chat_id):
          raise RuntimeError(
              "HTTPSConnectionPool: Max retries exceeded with url: "
              f"https://api.telegram.org/bot{token}/sendMessage")

      pipeline.run_notify(conn, now=NOW, notify_fn=notify_fn, token=token, chat_id="c")

      err = conn.execute("SELECT pipeline_error FROM job_postings").fetchone()["pipeline_error"]
      assert token not in err and "***" in err
      out = capsys.readouterr().out
      assert token not in out and "***" in out
  ```
- [ ] Step 2: Run it, expect FAIL (the token appears verbatim in both sinks):
  `rtk proxy python3 -m pytest apps/worker/tests/test_pipeline.py::test_run_notify_scrubs_token_from_recorded_and_printed_error -q`
  Expected: `AssertionError` on `token not in err`.
- [ ] Step 3: Implement — in `pipeline.py`, current `run_notify` except block:
  ```python
          except Exception as exc:  # noqa: BLE001
              attempt = row["attempts"] + 1
              exhausted = attempt >= NOTIFY_MAX_ATTEMPTS
              db.record_notify_failure(conn, row["id"], error=str(exc), now=now,
                                       exhausted=exhausted)
              print(f"[notify] send failed (attempt {attempt}/{NOTIFY_MAX_ATTEMPTS}) "
                    f"for posting id={row['id']}: {exc}"
                    + (" — parked as failed" if exhausted else "; will retry next pass"))
  ```
  Fixed:
  ```python
          except Exception as exc:  # noqa: BLE001
              attempt = row["attempts"] + 1
              exhausted = attempt >= NOTIFY_MAX_ATTEMPTS
              # The bot token rides in the Telegram URL, which requests embeds in the
              # exception text; scrub it before it lands in pipeline_error (rendered by
              # the web Failed bucket) or on stdout. (Guard the empty-token case: an
              # empty replace() would splice "***" between every character.)
              error = str(exc).replace(token, "***") if token else str(exc)
              db.record_notify_failure(conn, row["id"], error=error, now=now,
                                       exhausted=exhausted)
              print(f"[notify] send failed (attempt {attempt}/{NOTIFY_MAX_ATTEMPTS}) "
                    f"for posting id={row['id']}: {error}"
                    + (" — parked as failed" if exhausted else "; will retry next pass"))
  ```
- [ ] Step 4: Run test + the full notify suite, expect PASS:
  `rtk proxy python3 -m pytest apps/worker/tests/test_pipeline.py -k run_notify -q`
- [ ] Step 5: Docs — remove the `docs/PROGRESS.md` defect bullet ("Telegram bot token can leak into the shared DB + logs"). Add under CHANGELOG `### Security`:
  ```
  - **Telegram bot token is scrubbed from recorded/printed notify errors.** A `requests`
    failure embeds the full Telegram URL (with the token) in its exception text; `run_notify`
    now redacts the token to `***` before writing `job_postings.pipeline_error` (shown in the
    web Failed bucket) or printing it.
  ```
- [ ] Step 6: Commit:
  ```
  git add apps/worker/ats_worker/pipeline.py apps/worker/tests/test_pipeline.py docs/PROGRESS.md CHANGELOG.md
  git commit -m "fix(worker): scrub telegram bot token from recorded/printed notify errors"
  ```

## Phase 1 — Correctness defects

*Shipped behavior that is wrong. TDD; easiest-first.*

### Task 1.1: Run CI on `dev` branch pushes  [Phase 1]
**Files:** Modify `/home/halcyon/root/ats/.github/workflows/ci.yml:3-5`
*(Config task — no automated test.)*

- [ ] Step 1: Confirm current trigger — `ci.yml:3-5`:
  ```yaml
  on:
    push:
      branches: [master]
  ```
- [ ] Step 2: Add `dev`:
  ```yaml
  on:
    push:
      branches: [master, dev]
  ```
- [ ] Step 3: Verify + note the e2e consequence:
  `cd /home/halcyon/root/ats && grep -n 'branches:' .github/workflows/ci.yml` → `[master, dev]`. The `e2e` job gate fires on `github.event_name == 'push'`, so e2e now also runs on `dev` pushes — the intended effect (the audit flagged that e2e "effectively never fires"). No further change.
- [ ] Step 4: Docs — remove the `docs/PROGRESS.md` defect bullet ("CI runs only on `master`; `dev` pushes are ungated"). Add under CHANGELOG `### Fixed`:
  ```
  - **CI now runs on `dev` pushes, not just `master`.** All development lands on the
    long-lived `dev` branch (master stays far behind by design), so routine commits were
    getting zero CI and the gated e2e job never fired. `ci.yml` push trigger is now
    `[master, dev]`.
  ```
- [ ] Step 5: Commit:
  ```
  git add .github/workflows/ci.yml docs/PROGRESS.md CHANGELOG.md
  git commit -m "ci: run on dev branch pushes"
  ```

### Task 1.2: Log companies skipped by `run_fetch`  [Phase 1]
**Files:** Modify `/home/halcyon/root/ats/apps/worker/ats_worker/pipeline.py:51-52` · Test `/home/halcyon/root/ats/apps/worker/tests/test_pipeline.py`
**Interfaces:** `run_fetch(conn, companies, title_filter, *, now, fetch_fn=fetch_company)` — unchanged signature (Phase 4 later changes the default to `None`); adds a stdout log line on the swallowed exception.

- [ ] Step 1: Add the failing test to `tests/test_pipeline.py` (beside `test_run_fetch_one_company_failing_does_not_abort`):
  ```python
  def test_run_fetch_logs_the_skipped_company(db_path, capsys):
      # The docstring promises "logged-and-skipped", but the bare except was silent —
      # a dead board / typo'd source vanished with no trace. It must now print.
      conn = db.connect(db_path)

      def fetch_fn(source, slug, name):
          raise RuntimeError("boom")

      companies = [{"source": "greenhouse", "slug": "bad", "name": "Bad"}]
      pipeline.run_fetch(conn, companies, None, now=NOW, fetch_fn=fetch_fn)
      out = capsys.readouterr().out
      assert "greenhouse/bad" in out and "boom" in out
  ```
- [ ] Step 2: Run it, expect FAIL (no output captured):
  `rtk proxy python3 -m pytest apps/worker/tests/test_pipeline.py::test_run_fetch_logs_the_skipped_company -q`
  Expected: `AssertionError` (`out` is empty).
- [ ] Step 3: Implement — current `run_fetch` except (pipeline.py:51-52):
  ```python
          except Exception:  # noqa: BLE001 — one bad board must not abort the rest
              continue
  ```
  Fixed (mirrors `run_notify`'s print style):
  ```python
          except Exception as exc:  # noqa: BLE001 — one bad board must not abort the rest
              print(f"[fetch] {c.get('source')}/{c.get('slug')}: skipped after error: {exc}")
              continue
  ```
- [ ] Step 4: Run test + fetch suite, expect PASS:
  `rtk proxy python3 -m pytest apps/worker/tests/test_pipeline.py -k run_fetch -q`
- [ ] Step 5: Docs — remove the `docs/PROGRESS.md` defect bullet ("`run_fetch` swallows whole-company failures with no log"). Add under CHANGELOG `### Fixed`:
  ```
  - **`run_fetch` now logs a skipped company.** A failing board was swallowed by a bare
    `except: continue` despite the "logged-and-skipped" docstring; it now prints
    `[fetch] <source>/<slug>: skipped after error: <exc>`, matching `run_notify`.
  ```
- [ ] Step 6: Commit:
  ```
  git add apps/worker/ats_worker/pipeline.py apps/worker/tests/test_pipeline.py docs/PROGRESS.md CHANGELOG.md
  git commit -m "fix(worker): log companies skipped by run_fetch"
  ```

### Task 1.3: Isolate malformed recipe JSON in `get_watchlist`  [Phase 1]
**Files:** Modify `/home/halcyon/root/ats/apps/worker/ats_worker/db.py:77-85` · Test `/home/halcyon/root/ats/apps/worker/tests/test_watchlist_db.py`
**Interfaces:** `get_watchlist(conn) -> list[dict]` — same return shape for valid rows; a row whose `recipe` column is unparseable JSON is skipped + logged instead of raising through the whole read.

- [ ] Step 1: Add the failing test to `tests/test_watchlist_db.py`:
  ```python
  def test_get_watchlist_skips_a_row_with_malformed_recipe(db_path, capsys):
      # One corrupt recipe must not abort the entire watchlist read (which would make
      # the pass fetch nothing) — violates the "one bad row never aborts the batch"
      # invariant. Insert a valid row + a deliberately-broken one straight into the
      # raw String recipe column (import_watchlist always writes valid JSON).
      conn = db.connect(db_path)
      db.import_watchlist(conn, [
          {"source": "custom", "slug": "good", "name": "Good",
           "recipe": {"url": "https://x", "item_path": "jobs"}},
      ], now=NOW)
      conn.execute(
          "INSERT INTO watched_companies (source, slug, name, recipe, created_at) "
          "VALUES ('custom', 'bad', 'Bad', '{not valid json', ?)",
          (NOW,),
      )
      conn.commit()

      got = db.get_watchlist(conn)
      assert [c["slug"] for c in got] == ["good"]   # bad row skipped, not fatal
      assert "custom/bad" in capsys.readouterr().out
  ```
- [ ] Step 2: Run it, expect FAIL (`json.loads` raises out of the comprehension):
  `rtk proxy python3 -m pytest apps/worker/tests/test_watchlist_db.py::test_get_watchlist_skips_a_row_with_malformed_recipe -q`
  Expected: `json.decoder.JSONDecodeError` propagates (not a clean skip).
- [ ] Step 3: Implement — current `get_watchlist` (db.py:77-85):
  ```python
  def get_watchlist(conn: sqlite3.Connection) -> list[dict]:
      rows = conn.execute(
          "SELECT source, slug, name, recipe FROM watched_companies ORDER BY id ASC"
      ).fetchall()
      return [
          {"source": r["source"], "slug": r["slug"], "name": r["name"],
           "recipe": json.loads(r["recipe"]) if r["recipe"] else None}
          for r in rows
      ]
  ```
  Fixed (per-row guard):
  ```python
  def get_watchlist(conn: sqlite3.Connection) -> list[dict]:
      rows = conn.execute(
          "SELECT source, slug, name, recipe FROM watched_companies ORDER BY id ASC"
      ).fetchall()
      out: list[dict] = []
      for r in rows:
          try:
              recipe = json.loads(r["recipe"]) if r["recipe"] else None
          except json.JSONDecodeError:
              # One malformed recipe must not abort the whole read (the pass would then
              # fetch nothing) — skip it loudly; a recipe-source row can't fetch anyway.
              print(f"[watchlist] {r['source']}/{r['slug']}: skipping row with "
                    f"malformed recipe JSON")
              continue
          out.append({"source": r["source"], "slug": r["slug"], "name": r["name"],
                      "recipe": recipe})
      return out
  ```
- [ ] Step 4: Run the new test + the existing watchlist suite (existing `==` assertions still hold for valid rows), expect PASS:
  `rtk proxy python3 -m pytest apps/worker/tests/test_watchlist_db.py -q`
- [ ] Step 5: Docs — remove the `docs/PROGRESS.md` defect bullet ("Malformed `recipe` JSON in one watchlist row aborts the entire pass"). Add under CHANGELOG `### Fixed`:
  ```
  - **A malformed `recipe` in one watchlist row no longer aborts the whole pass.**
    `db.get_watchlist` decoded every row's `recipe` JSON in a comprehension before any
    per-company isolation, so one corrupt row raised through the entire read (fetching
    nothing). It now guards each row, skipping + logging the bad one (SPEC §9 invariant).
  ```
- [ ] Step 6: Commit:
  ```
  git add apps/worker/ats_worker/db.py apps/worker/tests/test_watchlist_db.py docs/PROGRESS.md CHANGELOG.md
  git commit -m "fix(worker): isolate malformed recipe JSON in get_watchlist"
  ```

### Task 1.4: Make the Toaster follow the system theme  [Phase 1]
**Files:** Modify `/home/halcyon/root/ats/apps/web/src/app/layout.tsx:29` · Test (new) `/home/halcyon/root/ats/apps/web/src/app/__tests__/layout.test.tsx`
**Decision/justification:** grep-verified there is NO manual theme toggle anywhere in the web app (only `ThemeProvider` with `enableSystem` + this one Toaster reference). So the smallest correct fix is sonner's `theme="system"` — it follows `prefers-color-scheme` via `matchMedia`, exactly matching `enableSystem`. A `useTheme()` client wrapper would be over-engineering with no toggle to track.

- [ ] Step 1: Write the failing test (nextJest auto-mocks `next/font` + CSS; mock `sonner` to capture the Toaster's props):
  ```tsx
  import { render } from '@testing-library/react'

  const captured: Record<string, unknown> = {}
  jest.mock('sonner', () => ({
      Toaster: (props: Record<string, unknown>) => {
          Object.assign(captured, props)
          return null
      },
  }))

  import RootLayout from '../layout'

  describe('RootLayout', () => {
      it('gives the Toaster a system-following theme (not hardcoded dark)', () => {
          render(<RootLayout>{null}</RootLayout>)
          expect(captured.theme).toBe('system')
      })
  })
  ```
- [ ] Step 2: Run it, expect FAIL (`theme` is `"dark"`):
  `cd /home/halcyon/root/ats/apps/web && npx jest src/app/__tests__/layout.test.tsx`
  Expected: `Expected: "system" / Received: "dark"`. (Benign jsdom `<html>`-nesting warning is expected.)
- [ ] Step 3: Implement — current `layout.tsx:29`:
  ```tsx
              <Toaster richColors position="top-right" theme="dark" />
  ```
  Fixed:
  ```tsx
              <Toaster richColors position="top-right" theme="system" />
  ```
- [ ] Step 4: Run test, expect PASS:
  `cd /home/halcyon/root/ats/apps/web && npx jest src/app/__tests__/layout.test.tsx`
- [ ] Step 5: Docs — remove the `docs/PROGRESS.md` defect bullet ("Toaster hardcoded `theme=\"dark\"`"). Add under CHANGELOG `### Fixed`:
  ```
  - **Toasts now follow the system theme.** `<Toaster>` was hardcoded `theme="dark"` while
    `ThemeProvider` is `enableSystem`; it is now `theme="system"`, so toasts track
    `prefers-color-scheme` like the rest of the UI. (No manual theme toggle exists.)
  ```
- [ ] Step 6: Commit:
  ```
  git add apps/web/src/app/layout.tsx apps/web/src/app/__tests__/layout.test.tsx docs/PROGRESS.md CHANGELOG.md
  git commit -m "fix(web): toaster follows system theme"
  ```

### Task 1.5: Honor `.env` keys for argparse defaults  [Phase 1]
**Files:** Modify `/home/halcyon/root/ats/apps/worker/ats_worker/run.py` (`main`, ~lines 285-337) · Test `/home/halcyon/root/ats/apps/worker/tests/test_run.py`
**Decision/justification (minimal correct approach = merge into `os.environ`):** the argparse defaults for `--db`/`--model`/`--score-backend`/`--codex-score-model`/`--batch-size` read `os.environ` at `add_argument` time, but `load_env()` ran *after* `parse_args` and its dict was never merged, so `SCORE_BACKEND`/`OLLAMA_MODEL`/`DB_PATH`/`CODEX_*` in `.env` were silently ignored. Fix: peek `--env`, load it, and `os.environ.setdefault`-merge it *before* the parser is built. `setdefault` preserves the required real-env-var path (docker-compose sets `DB_PATH` as a real container var) and keeps CLI flags overriding.

- [ ] Step 1: Add the failing test to `tests/test_run.py`:
  ```python
  def test_main_merges_env_file_into_argparse_defaults(monkeypatch, tmp_path):
      # SCORE_BACKEND / OLLAMA_MODEL / DB_PATH / CODEX_SCORE_MODEL set in .env must reach
      # run_once — regression guard for the bug where load_env's dict was never merged
      # into os.environ (so the os.environ-derived argparse defaults ignored .env).
      import os as _os
      monkeypatch.setattr(_os, "environ", dict(_os.environ))
      for k in ("SCORE_BACKEND", "OLLAMA_MODEL", "DB_PATH", "CODEX_SCORE_MODEL"):
          _os.environ.pop(k, None)

      envfile = tmp_path / ".env"
      envfile.write_text(
          "SCORE_BACKEND=claude\n"
          "OLLAMA_MODEL=custom:1b\n"
          "DB_PATH=/tmp/from-env.db\n"
          "CODEX_SCORE_MODEL=gpt-from-env\n"
          "ANTHROPIC_API_KEY=k\nTELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=c\n"
      )

      captured = {}
      monkeypatch.setattr(run, "run_once", lambda cfg, **kw: captured.update(kw))
      monkeypatch.setattr(run.config_mod, "load_config",
                          lambda path: cfgmod.load_config("companies: []\n"))
      monkeypatch.setattr(run, "load_resumes", lambda d: ({"resume": "r"}, ""))

      run.main(["--once", "--env", str(envfile)])

      assert captured["score_backend"] == "claude"
      assert captured["ollama_model"] == "custom:1b"
      assert captured["db_path"] == "/tmp/from-env.db"
      assert captured["codex_score_model"] == "gpt-from-env"
      assert captured["env"]["TELEGRAM_BOT_TOKEN"] == "t"   # dict still plumbed to run_once
  ```
  (Adjust `run.config_mod`/`cfgmod`/`run_once` kwarg names to the actual symbols in `test_run.py` when you read it.)
- [ ] Step 2: Run it, expect FAIL:
  `rtk proxy python3 -m pytest apps/worker/tests/test_run.py::test_main_merges_env_file_into_argparse_defaults -q`
  Expected: `AssertionError` — `captured["score_backend"] == "codex"` (the built-in default; `.env` was ignored).
- [ ] Step 3: Implement — in `run.py`, current `main` header:
  ```python
  def main(argv=None) -> None:
      parser = argparse.ArgumentParser(description="Job-hunt pipeline worker")
  ```
  Fixed — insert the pre-parse + merge before the parser is built:
  ```python
  def main(argv=None) -> None:
      # Load .env BEFORE the parser is built: the argparse defaults for --db/--model/
      # --score-backend/--codex-score-model/--batch-size read os.environ, so a .env value
      # has to be in os.environ by the time add_argument runs. setdefault = a real process
      # env var still wins (docker-compose sets DB_PATH that way) and an explicit CLI flag
      # still overrides; --env is peeked first so a custom path is honored.
      pre = argparse.ArgumentParser(add_help=False)
      pre.add_argument("--env", default=".env")
      env = load_env(pre.parse_known_args(argv)[0].env)
      for key, value in env.items():
          os.environ.setdefault(key, value)

      parser = argparse.ArgumentParser(description="Job-hunt pipeline worker")
  ```
  And remove the now-redundant later `env = load_env(args.env)` reload (delete it; `env` is already loaded above and still passed to `run_once`).
- [ ] Step 4: Run the new test + the full run suite (existing `run_once`/`load_env`/`make_scorer` tests call those directly, not `main`, so they're unaffected), expect PASS:
  `rtk proxy python3 -m pytest apps/worker/tests/test_run.py -q`
- [ ] Step 5: Docs — remove the `docs/PROGRESS.md` defect bullet ("`SCORE_BACKEND` / `OLLAMA_MODEL` / `DB_PATH` / `CODEX_*` in `.env` are silently ignored"). Add under CHANGELOG `### Fixed`:
  ```
  - **`.env` now feeds the argparse defaults.** `SCORE_BACKEND` / `OLLAMA_MODEL` / `DB_PATH`
    / `CODEX_*` set in `.env` were silently ignored — `load_env()` ran after `parse_args`
    and its dict was never merged into `os.environ`. `main()` now loads `.env` and
    `setdefault`-merges it before the parser is built, so a real env var still wins and an
    explicit CLI flag still overrides.
  ```
- [ ] Step 6: Commit:
  ```
  git add apps/worker/ats_worker/run.py apps/worker/tests/test_run.py docs/PROGRESS.md CHANGELOG.md
  git commit -m "fix(worker): honor .env keys for argparse defaults"
  ```

### Task 1.6: Remove the silently-dropped status-change notes field  [Phase 1]
**Files:** Modify `/home/halcyon/root/ats/apps/web/src/lib/actions.ts:490` · `.../components/Dashboard.tsx:186,188` · `.../components/StatusHistoryModal.tsx` (type ~34, onAddStatus type ~36, state ~70, handleSubmit ~73-81, render branch ~182, Add-Status textarea ~227-235) · Test `.../components/__tests__/StatusHistoryModal.test.tsx`
**Decision/justification (REMOVE, not persist):** the Update-Status form collected `notes` and threaded them through `updateApplicationStatus(id,status,date,notes)`, but the action never wrote them and `status_history` has no notes column — so the typed notes vanished. Remove the field end-to-end. **Do NOT touch the application-level notes** (`StatusHistoryModal` edit-form `editForm.notes`, the `application.notes` prop, and `updateApplicationDetails`' `notes` persist at `actions.ts:480`) — that path is separate and works. Keep the `Textarea`/`Label` imports (still used by the edit form + labels).

- [ ] Step 1: Update the existing test `StatusHistoryModal.test.tsx`. Change `mockHistory` to drop `notes`:
  ```tsx
      const mockHistory = [
          { id: 11, status: 'Applied', timestamp: '2023-01-01' },
          { id: 22, status: 'Interviewing: 1st round', timestamp: '2023-01-15' }
      ]
  ```
  Replace the `'should render history items'` body (was asserting the notes value) with a status-text assertion:
  ```tsx
      it('should render history items', () => {
          render(<StatusHistoryModal {...makeProps()} />)
          expect(screen.getAllByText('Applied').length).toBeGreaterThan(0)
          expect(screen.getByText('Interviewing: 1st round')).toBeInTheDocument()
      })
  ```
  Replace the `'should allow adding a new status'` body — drop the notes textarea, assert `onAddStatus` carries no `notes`, and add a "no notes UI" guard:
  ```tsx
      it('adds a new status without a notes field', async () => {
          const user = userEvent.setup()
          const props = makeProps()
          render(<StatusHistoryModal {...props} />)

          // The Update-Status form no longer has a notes input (it was silently dropped).
          expect(screen.queryByLabelText(/notes/i)).not.toBeInTheDocument()

          await user.selectOptions(screen.getByLabelText(/status/i), 'Offer')
          await user.click(screen.getByRole('button', { name: /update status/i }))

          expect(props.onAddStatus).toHaveBeenCalledWith(
              expect.objectContaining({ status: 'Offer' }))
          expect(props.onAddStatus.mock.calls[0][0]).not.toHaveProperty('notes')
      })
  ```
- [ ] Step 2: Run it, expect FAIL (component still renders the notes label and passes `notes: ''`):
  `cd /home/halcyon/root/ats/apps/web && npx jest src/components/__tests__/StatusHistoryModal.test.tsx`
  Expected: `queryByLabelText(/notes/i)` finds the element → `not.toBeInTheDocument()` fails.
- [ ] Step 3: Implement the removals.
  `StatusHistoryModal.tsx` history type — drop `notes?: string`:
  ```tsx
      history: Array<{
          id: number
          status: string
          timestamp: string
      }>
  ```
  onAddStatus type:
  ```tsx
      onAddStatus: (data: { status: string; date: string }) => void
  ```
  State — drop `newNotes`:
  ```tsx
      const [newStatus, setNewStatus] = useState<string>(STATUSES[0])
      const [newDate, setNewDate] = useState(new Date().toISOString().split('T')[0])
  ```
  handleSubmit — drop `notes` + `setNewNotes`:
  ```tsx
      const handleSubmit = (e: React.FormEvent) => {
          e.preventDefault()
          onAddStatus({
              status: newStatus,
              date: newDate,
          })
      }
  ```
  Render branch (delete it):
  ```tsx
                                                  {item.notes && <div className="text-sm mt-0.5 text-muted-foreground">{item.notes}</div>}
  ```
  Add-Status notes block (delete the whole `<div>`):
  ```tsx
                          <div className="space-y-2">
                              <Label htmlFor="notes">Notes</Label>
                              <Textarea
                                  id="notes"
                                  placeholder="Notes..."
                                  value={newNotes}
                                  onChange={(e) => setNewNotes(e.target.value)}
                              />
                          </div>
  ```
  `Dashboard.tsx` handleAddStatus:
  ```tsx
      const handleAddStatus = async (data: { status: string; date: string }) => {
          if (selectedApp) {
              const result = await updateApplicationStatus(selectedApp.id, data.status, data.date)
  ```
  (Leave `Dashboard.tsx`'s `handleEditApplication` `notes: string` type — that is application-notes, untouched.)
  `actions.ts:490` — drop the unused 4th param:
  ```tsx
  export async function updateApplicationStatus(id: number, status: string, date?: string) {
  ```
- [ ] Step 4: Run the modal test + the actions test (existing `updateApplicationStatus` test calls it with 2 args, still valid) + lint, expect PASS:
  ```
  cd /home/halcyon/root/ats/apps/web && npx jest src/components/__tests__/StatusHistoryModal.test.tsx src/__tests__/actions.test.ts && npm run lint
  ```
- [ ] Step 5: Docs — remove the `docs/PROGRESS.md` defect bullet ("Status-change notes are silently dropped") AND the dead-code bullet ("Web: `updateApplicationStatus` `notes` param + `StatusHistoryModal` notes branch — dead"). Add under CHANGELOG a `### Removed` group:
  ```
  ### Removed
  - **Status-change notes field (was silently dropped).** The Update-Status form collected
    `notes` and threaded them through `updateApplicationStatus(id,status,date,notes)`, but the
    action never persisted them and `status_history` has no notes column, so users' notes
    vanished. Removed the textarea, the dead `notes` param, the history-row render branch, the
    `notes?` history type field, and the `Dashboard` call-site arg. (Application-level notes,
    edited via `updateApplicationDetails`, are unaffected.)
  ```
- [ ] Step 6: Commit:
  ```
  git add apps/web/src/lib/actions.ts apps/web/src/components/Dashboard.tsx apps/web/src/components/StatusHistoryModal.tsx apps/web/src/components/__tests__/StatusHistoryModal.test.tsx docs/PROGRESS.md CHANGELOG.md
  git commit -m "fix(web): remove silently-dropped status-change notes field"
  ```

## Phase 2 — Security hardening

*SSRF, `javascript:` URLs, the CVE bump, injection seams, input validation. TDD; easiest-first. Every finding got a task; three carry documented accepted-residuals (DNS-rebinding, phenom/workday IP-host slug, codex rollout ownership).*

### Task 2.1: Bump Next.js to latest 14.2.x patch (CVE-2024-56332)  [Phase 2]
**Files:** Modify `apps/web/package.json` (`next` spec), `apps/web/package-lock.json` (pinned exactly `14.2.0`). No source change.
- [ ] Step 1: no test file — the guard is the existing suite + build. Baseline: `cd apps/web && sed -n '/"node_modules\/next"/,+2p' package-lock.json` shows `14.2.0`.
- [ ] Step 2: confirm the fix is needed: `cd apps/web && npx jest` currently PASSES on 14.2.0 but the lockfile is exposed to CVE-2024-56332 (server-actions DoS, fixed 14.2.21+).
- [ ] Step 3: implement — `cd apps/web && npm view next@14 version` to read the latest 14.2.x, then `npm install next@^14.2.33` (use whatever `npm view` reports — do NOT jump to 15.x). This rewrites only `package-lock.json` + the `next` line in `package.json`.
- [ ] Step 4: run, expect PASS — `cd apps/web && npx jest && npm run build`. Build must succeed (standalone output).
- [ ] Step 5: docs — CHANGELOG `### Security`: "Bump Next.js 14.2.0 → 14.2.x (CVE-2024-56332 server-actions DoS)."
- [ ] Step 6: commit — `git add apps/web/package.json apps/web/package-lock.json CHANGELOG.md && git commit -m "fix(web): bump Next.js to 14.2.x patch (CVE-2024-56332)"`

### Task 2.2: Health route returns a generic error, not raw err.message  [Phase 2]
**Files:** Modify `apps/web/src/app/api/health/route.ts:16-21`; Modify test `apps/web/src/__tests__/health.test.ts:27-32`.
- [ ] Step 1: edit the existing 503 test to assert the generic body:
  ```ts
  test('GET returns 503 with a generic error when the DB query throws', async () => {
      mockQueryRaw.mockRejectedValue(new Error('SQLITE_CANTOPEN'))
      const res = await GET()
      expect(res.status).toBe(503)
      expect(await res.json()).toEqual({ status: 'error', error: 'database unreachable' })
  })
  ```
- [ ] Step 2: run, expect FAIL — `cd apps/web && npx jest src/__tests__/health.test.ts` → received `error: 'SQLITE_CANTOPEN'`.
- [ ] Step 3: implement — replace the catch block:
  ```ts
      } catch (err) {
          // Detail stays server-side only; the 503 body must not leak internals (paths,
          // driver strings). The autoheal sidecar keys on the status code, not the body.
          console.error('[health] DB probe failed:', err)
          return NextResponse.json({ status: 'error', error: 'database unreachable' }, { status: 503 })
      }
  ```
- [ ] Step 4: run, expect PASS — `cd apps/web && npx jest src/__tests__/health.test.ts`.
- [ ] Step 5: docs — CHANGELOG `### Security`: "Health probe 503 returns a generic message; error detail logged server-side only." (SPEC §6 mentions the digest-only browser view — reconcile.)
- [ ] Step 6: commit — `git add apps/web/src/app/api/health/route.ts apps/web/src/__tests__/health.test.ts CHANGELOG.md && git commit -m "fix(web): don't leak err.message from /api/health"`

### Task 2.3: CSV formula-injection guard in csvEscape  [Phase 2]
**Files:** Modify `apps/web/src/lib/actions.ts:730-737` (`csvEscape`, used by `exportApplicationsCSV`); Test `apps/web/src/__tests__/actions.int.test.ts`.
- [ ] Step 1: add a failing test (`csvEscape` isn't exported, so assert through `exportApplicationsCSV`):
  ```ts
  test('exportApplicationsCSV neutralizes formula-injection cells', async () => {
      await prisma.applications.create({ data: {
          company_name: '=1+2', job_title: 'x', date_applied: '2026-01-01',
          category: 'Others', status: 'Applied', application_url: '', notes: '@SUM(A1)',
          last_updated: '2026-01-01T00:00:00.000Z' } })
      const exp = await exportApplicationsCSV()
      expect(exp.csv).toContain(`'=1+2`)
      expect(exp.csv).toContain(`'@SUM(A1)`)
  })
  ```
- [ ] Step 2: run, expect FAIL — `cd apps/web && npx jest --config jest.integration.config.ts src/__tests__/actions.int.test.ts` → cells emitted unescaped.
- [ ] Step 3: implement — extend `csvEscape`:
  ```ts
  function csvEscape(value: string | null | undefined): string {
      if (value === null || value === undefined) return ''
      let s = String(value)
      // Formula-injection guard: a cell whose first char is one a spreadsheet may treat
      // as a formula lead (= + - @, or a tab/CR) is prefixed with a single quote so
      // Excel/Sheets render it as literal text. Prefix BEFORE the quote check so a
      // comma-bearing cell still gets wrapped.
      if (/^[=+\-@\t\r]/.test(s)) s = "'" + s
      if (/[",\r\n]/.test(s)) {
          return `"${s.replace(/"/g, '""')}"`
      }
      return s
  }
  ```
- [ ] Step 4: run, expect PASS — same command as Step 2.
- [ ] Step 5: docs — CHANGELOG `### Security`: "CSV export prefixes formula-lead cells (= + - @) with `'` to block spreadsheet formula injection."
- [ ] Step 6: commit — `git add apps/web/src/lib/actions.ts apps/web/src/__tests__/actions.int.test.ts CHANGELOG.md && git commit -m "fix(web): neutralize CSV formula injection in export"`

### Task 2.4: safeHref util blocks javascript:/data: scheme in scraped job_url links  [Phase 2]
**Files:** Modify `apps/web/src/lib/utils.ts` (add `safeHref`); Modify `apps/web/src/components/DiscoveredJobsTable.tsx:433` and `apps/web/src/components/JobDetailModal.tsx:298`; Test new `apps/web/src/lib/__tests__/utils.test.ts`.
**Interfaces:** `export function safeHref(url: string | null | undefined): string` — returns the URL when its scheme is http/https, else `'#'`.
- [ ] Step 1: failing test `apps/web/src/lib/__tests__/utils.test.ts`:
  ```ts
  import { safeHref } from '@/lib/utils'
  test('passes http/https through', () => {
      expect(safeHref('https://acme.example/jobs/1')).toBe('https://acme.example/jobs/1')
      expect(safeHref('http://x.test/a')).toBe('http://x.test/a')
  })
  test('neutralizes dangerous or empty hrefs to #', () => {
      expect(safeHref('javascript:alert(1)')).toBe('#')
      expect(safeHref('data:text/html,<script>')).toBe('#')
      expect(safeHref('')).toBe('#')
      expect(safeHref(null)).toBe('#')
  })
  ```
- [ ] Step 2: run, expect FAIL — `cd apps/web && npx jest src/lib/__tests__/utils.test.ts` → `safeHref` undefined.
- [ ] Step 3: implement — append to `utils.ts`:
  ```ts
  // Scraped job_url is untrusted; an <a href> with a javascript:/data: scheme executes
  // on click. Allow only http(s); anything else (or a parse failure) renders as '#'.
  export function safeHref(url: string | null | undefined): string {
    if (!url) return '#'
    try {
      const proto = new URL(url).protocol
      return proto === 'http:' || proto === 'https:' ? url : '#'
    } catch {
      return '#'
    }
  }
  ```
  Then in `DiscoveredJobsTable.tsx` add `import { safeHref } from '@/lib/utils'` (extend an existing `cn` import from `@/lib/utils` if present) and change `href={job.job_url}` → `href={safeHref(job.job_url)}`. Same edit in `JobDetailModal.tsx`.
- [ ] Step 4: run, expect PASS — `cd apps/web && npx jest src/lib/__tests__/utils.test.ts src/components/__tests__/DiscoveredJobsTable.test.tsx src/components/__tests__/JobDetailModal.test.tsx`.
- [ ] Step 5: docs — CHANGELOG `### Security`: "Job-posting links pass through safeHref (http/https only) to block javascript:/data: URLs in scraped job_url."
- [ ] Step 6: commit — `git add apps/web/src/lib/utils.ts apps/web/src/lib/__tests__/utils.test.ts apps/web/src/components/DiscoveredJobsTable.tsx apps/web/src/components/JobDetailModal.tsx CHANGELOG.md && git commit -m "fix(web): guard scraped job_url hrefs with safeHref"`

### Task 2.5: db._update rejects unknown SET columns (defense-in-depth)  [Phase 2]
**Files:** Modify `apps/worker/ats_worker/db.py:181-185` (`_update`; callers `save_score`, `mark_notified` — **2 callers**, not 3; `mark_failed`/`record_notify_failure` use fixed SQL); Test `apps/worker/tests/test_db.py`.
**Justification (seam only):** keys are code-constant dicts, never user input — a guard against a *future* caller passing an attacker-influenced key. Explicit `raise` (not `assert`, which `python -O` strips).
- [ ] Step 1: failing test in `test_db.py`:
  ```python
  import pytest
  from tests._helpers import bootstrap_db, seed_new, NOW

  def test_update_refuses_unknown_column(tmp_path):
      conn = db.connect(bootstrap_db(tmp_path / "db.sqlite"))
      seed_new(conn, ["1"])
      row = conn.execute("SELECT id FROM job_postings").fetchone()
      with pytest.raises(ValueError):
          db._update(conn, row["id"], {"job_title": "pwned"})  # not an allowed column
  ```
  (Adjust `bootstrap_db`/`seed_new` to the real helpers in `tests/_helpers.py` when you read it.)
- [ ] Step 2: run, expect FAIL — `rtk proxy python3 -m pytest apps/worker/tests/test_db.py::test_update_refuses_unknown_column` → no ValueError (SQL runs).
- [ ] Step 3: implement — in `db.py`:
  ```python
  # The only columns the state-transition helpers ever set. `_update` builds its SET
  # clause from dict keys, so gate them against this allowlist: a stray/untrusted key
  # must never reach the SQL string (defense-in-depth; today all callers pass constants).
  _UPDATABLE_COLUMNS = frozenset({
      "score", "score_detail", "pipeline_status", "pipeline_error",
      "attempts", "application_id", "updated_at",
  })


  def _update(conn: sqlite3.Connection, posting_id: int, sets: dict) -> None:
      unknown = set(sets) - _UPDATABLE_COLUMNS
      if unknown:
          raise ValueError(f"_update: refusing to build SET for unknown column(s): {sorted(unknown)}")
      cols = ", ".join(f"{k}=:{k}" for k in sets)
      params = {**sets, "id": posting_id}
      conn.execute(f"UPDATE job_postings SET {cols} WHERE id=:id", params)
      conn.commit()
  ```
  (Confirm the real column set against `save_score`/`mark_notified` when you read them.)
- [ ] Step 4: run, expect PASS — `rtk proxy python3 -m pytest apps/worker/tests/test_db.py` (guard must not break `save_score`/`mark_notified`).
- [ ] Step 5: docs — CHANGELOG `### Security`: "db._update validates SET columns against an allowlist."
- [ ] Step 6: commit — `git add apps/worker/ats_worker/db.py apps/worker/tests/test_db.py CHANGELOG.md && git commit -m "fix(worker): allowlist db._update columns"`

### Task 2.6: Parameterize the promotion-suggestions raw IN(...) list  [Phase 2]
**Files:** Modify `apps/web/src/lib/promotion-actions.ts:30,34-48,53-62`; Test `apps/web/src/__tests__/promotion.test.ts`.
**Chosen fix:** parameterizing removes the interpolation seam entirely (`$queryRawUnsafe` accepts positional bind params) — the smaller *correct* fix.
- [ ] Step 1: failing test in `promotion.test.ts`, `getPromotionSuggestions` block:
  ```ts
  it('binds VALID_SOURCES as query params (no inlined literals)', async () => {
    mockPrisma.$queryRawUnsafe.mockResolvedValue([] as any)
    await getPromotionSuggestions()
    const [sql, ...args] = mockPrisma.$queryRawUnsafe.mock.calls[0]
    expect(sql).not.toMatch(/'greenhouse'/)      // no inlined source literals
    expect(sql).toMatch(/IN \(\?(, \?)*\)/)      // placeholders instead
    expect(args).toEqual(expect.arrayContaining(['greenhouse', 'lever']))
  })
  ```
- [ ] Step 2: run, expect FAIL — `cd apps/web && npx jest src/__tests__/promotion.test.ts` → SQL still inlines `'greenhouse'`, args empty.
- [ ] Step 3: implement:
  ```ts
  // VALID_SOURCES bind as positional params (not inlined literals) so the raw SQL
  // carries no interpolated values. See getPromotionSuggestions.
  const WATCHLIST_PLACEHOLDERS = VALID_SOURCES.map(() => '?').join(', ')
  ```
  In `SUGGESTIONS_SQL` change `AND jp.source IN (${WATCHLIST_SOURCES})` → `AND jp.source IN (${WATCHLIST_PLACEHOLDERS})`, and change the call to `prisma.$queryRawUnsafe<...>(SUGGESTIONS_SQL, ...VALID_SOURCES)`. Delete the old `WATCHLIST_SOURCES` const.
- [ ] Step 4: run, expect PASS — `cd apps/web && npx jest src/__tests__/promotion.test.ts src/__tests__/promotion.int.test.ts`.
- [ ] Step 5: docs — CHANGELOG `### Security`: "promotion-suggestions query binds source list as params instead of string interpolation."
- [ ] Step 6: commit — `git add apps/web/src/lib/promotion-actions.ts apps/web/src/__tests__/promotion.test.ts CHANGELOG.md && git commit -m "fix(web): parameterize promotion-suggestions IN() list"`

### Task 2.7: Minimal security headers in next.config  [Phase 2]
**Files:** Modify `apps/web/next.config.mjs`. Verification is a live `curl -I` (a next.config `headers()` is awkward to unit-test under jest+`.mjs`; a request check is the honest gate for a config-only change).
- [ ] Step 1: baseline — with `make dev` up, `curl -sI http://localhost:3000/ | grep -i x-frame-options` returns nothing.
- [ ] Step 2: run, expect FAIL — the curl above prints no header on the current config.
- [ ] Step 3: implement:
  ```js
  /** @type {import('next').NextConfig} */
  const nextConfig = {
      output: 'standalone',
      async headers() {
          // Minimal hardening for a single-user localhost app. CSP intentionally permits
          // Next's inline runtime ('unsafe-inline'/'unsafe-eval'); the high-value wins here
          // are clickjacking + MIME-sniff + framing protection, not a strict script CSP.
          return [{
              source: '/:path*',
              headers: [
                  { key: 'X-Frame-Options', value: 'DENY' },
                  { key: 'X-Content-Type-Options', value: 'nosniff' },
                  { key: 'Referrer-Policy', value: 'same-origin' },
                  { key: 'Content-Security-Policy', value:
                      "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; " +
                      "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; " +
                      "base-uri 'self'; form-action 'self'; frame-ancestors 'none'" },
              ],
          }]
      },
  };
  export default nextConfig;
  ```
- [ ] Step 4: run, expect PASS — rebuild/restart (`make down && make up`, or `make dev`), then `curl -sI http://localhost:3000/ | grep -iE 'x-frame-options|content-security-policy|x-content-type-options'` prints all three; then `cd apps/web && npx jest && npm run build` (app still renders/builds — confirms CSP didn't break the inline runtime).
- [ ] Step 5: docs — SPEC §6: note the response-header set; CHANGELOG `### Security`: "Add X-Frame-Options/X-Content-Type-Options/Referrer-Policy/CSP response headers."
- [ ] Step 6: commit — `git add apps/web/next.config.mjs docs/SPEC.md CHANGELOG.md && git commit -m "feat(web): add minimal security response headers"`

### Task 2.8: Validate server-action inputs (status/category gates + page/size clamp)  [Phase 2]
**Files:** Modify `apps/web/src/lib/actions.ts` — `addApplication` (gate `status`+`category`), `updateApplicationDetails` (gate `category`), `getApplications` (clamp), `getJobPostings` (clamp); Test `apps/web/src/__tests__/actions.test.ts`.
- [ ] Step 1: failing tests in `actions.test.ts`:
  ```ts
  it('addApplication coerces an out-of-set status to Applied', async () => {
      mockPrisma.applications.findFirst.mockResolvedValue(null)
      mockPrisma.applications.create.mockResolvedValue({ id: 1 } as any)
      await addApplication({ company_name: 'A', job_title: 'B', date_applied: '2026-01-01', status: 'Hacked' })
      expect(mockPrisma.applications.create).toHaveBeenCalledWith(
          expect.objectContaining({ data: expect.objectContaining({ status: 'Applied' }) }))
  })
  it('getApplications clamps an oversized page size', async () => {
      mockPrisma.applications.findMany.mockResolvedValue([])
      mockPrisma.applications.count.mockResolvedValue(0)
      await getApplications({ page: -5, size: 99999 })
      expect(mockPrisma.applications.findMany).toHaveBeenCalledWith(
          expect.objectContaining({ skip: 0, take: 100 }))
  })
  ```
  (Add a matching `updateApplicationDetails` category-coercion test against `applications.update`. **Note:** if Task 4's `addApplication` transaction landed first, this test asserts through the `$transaction` mock — reconcile the mock shape.)
- [ ] Step 2: run, expect FAIL — `cd apps/web && npx jest src/__tests__/actions.test.ts` → status `Hacked` persisted; `take: 99999`.
- [ ] Step 3: implement:
  - `getApplications` (top): `const page = Math.max(0, Math.floor(params.page || 0)); const size = Math.min(100, Math.max(1, Math.floor(params.size || 10)))`
  - `getJobPostings` (top): same clamp with default 25: `const size = Math.min(100, Math.max(1, Math.floor(params.size ?? 25)))`, `const page = Math.max(0, Math.floor(params.page ?? 0))`
  - `addApplication`: `const status = (STATUSES as readonly string[]).includes(data.status ?? '') ? data.status! : 'Applied'` (replaces `data.status || 'Applied'`); `const category = (CATEGORIES as readonly string[]).includes(data.category ?? '') ? data.category! : 'Others'`.
  - `updateApplicationDetails`: `const category = (CATEGORIES as readonly string[]).includes(data.category) ? data.category : 'Others'` (write `category`, not free-text `data.category`).
- [ ] Step 4: run, expect PASS — `cd apps/web && npx jest src/__tests__/actions.test.ts src/__tests__/actions.int.test.ts`.
- [ ] Step 5: docs — CHANGELOG `### Security`: "Server actions gate status/category to the constants sets and clamp page/size."
- [ ] Step 6: commit — `git add apps/web/src/lib/actions.ts apps/web/src/__tests__/actions.test.ts CHANGELOG.md && git commit -m "fix(web): validate/clamp server-action inputs"`

### Task 2.9: SSRF guard helper + apply to the embedded-greenhouse feed resolver  [Phase 2]
**Files:** Modify `apps/worker/ats_worker/util.py` (add `is_safe_public_url`); Modify `apps/worker/ats_worker/feed/embedded_gh.py`; Test `apps/worker/tests/test_util.py` + `apps/worker/tests/test_embedded_gh.py`.
**Interfaces:** `def is_safe_public_url(url: str | None) -> bool` in `util.py` — True only for an `http(s)` URL whose host is neither `localhost` nor a private/loopback/link-local/reserved IP literal. Pure (no DNS). Reused by Task 2.10.
**Accepted residual:** the pure check blocks the concrete vectors a scraped feed URL carries (169.254.169.254, 127.0.0.1, ::1, RFC-1918, localhost). DNS-rebinding (a public name resolving to a private IP) is out of scope for this single-user worker — documented in PROGRESS.
- [ ] Step 1: failing tests. `test_util.py`:
  ```python
  from ats_worker.util import is_safe_public_url

  def test_is_safe_public_url_blocks_ssrf_targets():
      assert is_safe_public_url("https://boards.greenhouse.io/x") is True
      assert is_safe_public_url("http://169.254.169.254/latest/meta-data/") is False
      assert is_safe_public_url("http://127.0.0.1/") is False
      assert is_safe_public_url("http://localhost/") is False
      assert is_safe_public_url("http://[::1]/") is False
      assert is_safe_public_url("http://10.0.0.5/") is False
      assert is_safe_public_url("file:///etc/passwd") is False
      assert is_safe_public_url(None) is False
  ```
  `test_embedded_gh.py` (adapt `FakeSession`/`_WITH_TOKEN` to the real helpers in that file):
  ```python
  def test_refuses_internal_target_without_fetching():
      sess = FakeSession(text=_WITH_TOKEN)
      assert embedded_gh.resolve_embedded(
          "http://169.254.169.254/careers?gh_jid=1", session=sess) is None
      assert sess.calls == []   # blocked before any HTTP GET
  ```
- [ ] Step 2: run, expect FAIL — `rtk proxy python3 -m pytest apps/worker/tests/test_util.py apps/worker/tests/test_embedded_gh.py` → import error / fetch happens.
- [ ] Step 3: implement. In `util.py` add `import ipaddress` and `from urllib.parse import urlparse`, then:
  ```python
  def is_safe_public_url(url: str | None) -> bool:
      """True only for an http(s) URL whose host is a public target. Pure (no DNS):
      blocks the SSRF vectors a scraped URL can carry — non-http(s) schemes, `localhost`,
      and private/loopback/link-local/reserved IP literals (incl. 169.254.169.254). A
      plain DNS name is allowed as-is (rebinding is out of scope; see PROGRESS)."""
      try:
          p = urlparse(url or "")
      except ValueError:
          return False
      if p.scheme not in ("http", "https"):
          return False
      host = (p.hostname or "").strip().lower()
      if not host or host == "localhost" or host.endswith(".localhost"):
          return False
      try:
          return ipaddress.ip_address(host).is_global
      except ValueError:
          return True   # a DNS name, not an IP literal
  ```
  In `embedded_gh.py` add `from ats_worker.util import is_safe_public_url` and, right after the `if not jid: return None` guard:
  ```python
      if not is_safe_public_url(url):
          return None   # SSRF guard: never fetch an internal/loopback/non-http(s) target
  ```
- [ ] Step 4: run, expect PASS — `rtk proxy python3 -m pytest apps/worker/tests/test_util.py apps/worker/tests/test_embedded_gh.py`.
- [ ] Step 5: docs — SPEC (feed section): resolver only fetches public http(s) hosts; PROGRESS: add an accepted-residual line for DNS-rebinding; CHANGELOG `### Security`: "Embedded-greenhouse resolver refuses non-public/non-http(s) fetch targets."
- [ ] Step 6: commit — `git add apps/worker/ats_worker/util.py apps/worker/ats_worker/feed/embedded_gh.py apps/worker/tests/test_util.py apps/worker/tests/test_embedded_gh.py docs/ CHANGELOG.md && git commit -m "fix(worker): SSRF guard for embedded-greenhouse feed resolver"`

### Task 2.10: Apply the SSRF guard to custom + browser recipe executors  [Phase 2]
**Files:** Modify `apps/worker/ats_worker/fetch/custom.py` (top of `fetch`); Modify `apps/worker/ats_worker/fetch/browser.py` (top of `fetch`, before the Playwright import); Test `apps/worker/tests/test_custom.py` + `apps/worker/tests/test_browser.py`.
**Threat note (low):** recipe `url` is written by the single operator via `addWatchedCompany` — defense-in-depth, not an external surface, but the helper exists so the guard is one line each and a bad recipe fails loudly.
- [ ] Step 1: failing tests. `test_custom.py`:
  ```python
  import pytest
  from ats_worker.fetch import custom
  from tests._helpers import FakeSession

  def test_custom_fetch_refuses_internal_url():
      sess = FakeSession(payload={"jobs": []})
      with pytest.raises(ValueError):
          custom.fetch("slug", "Acme", {"url": "http://127.0.0.1/jobs"}, session=sess)
      assert sess.calls == []
  ```
  `test_browser.py` (the guard runs before the lazy Playwright import, so no browser needed):
  ```python
  import pytest
  from ats_worker.fetch import browser

  def test_browser_fetch_refuses_internal_url():
      with pytest.raises(ValueError):
          browser.fetch("slug", "Acme", {"url": "http://169.254.169.254/", "item": ".job"})
  ```
- [ ] Step 2: run, expect FAIL — `rtk proxy python3 -m pytest apps/worker/tests/test_custom.py apps/worker/tests/test_browser.py`.
- [ ] Step 3: implement. `custom.py` add `from ats_worker.util import is_safe_public_url` and as the first lines of `fetch`:
  ```python
      if not is_safe_public_url(recipe.get("url")):
          raise ValueError(f"custom recipe url is not a safe public http(s) URL: {recipe.get('url')!r}")
  ```
  `browser.py` add the same import and make it the FIRST statement of `fetch` (before `from playwright...`):
  ```python
      if not is_safe_public_url(recipe.get("url")):
          raise ValueError(f"browser recipe url is not a safe public http(s) URL: {recipe.get('url')!r}")
  ```
- [ ] Step 4: run, expect PASS — `rtk proxy python3 -m pytest apps/worker/tests/test_custom.py apps/worker/tests/test_browser.py`.
- [ ] Step 5: docs — CHANGELOG `### Security`: "custom/browser recipe executors validate recipe.url against the SSRF guard before fetching."
- [ ] Step 6: commit — `git add apps/worker/ats_worker/fetch/custom.py apps/worker/ats_worker/fetch/browser.py apps/worker/tests/test_custom.py apps/worker/tests/test_browser.py CHANGELOG.md && git commit -m "fix(worker): SSRF guard for custom/browser recipe urls"`

### Task 2.11: Validate watchlist slug structure at both write boundaries  [Phase 2]
**Files:** Modify `apps/web/src/lib/actions.ts` `addWatchedCompany`; Modify `apps/worker/ats_worker/config.py` `_parse_companies`; Tests `apps/web/src/__tests__/watchlist.test.ts` + `apps/worker/tests/test_config.py`.
**Correction to the finding:** a "no `/`" rule would reject legitimate multi-part slugs (`workday` "tenant/dc/site", `phenom` "host/domain"). The guard below allows single-`/`-joined segments but blocks host-injection metacharacters (`@ : ? # % \`, whitespace) and traversal (`..`, leading/trailing/doubled `/`).
**Accepted residual (low):** `phenom`/`workday` take a hostname as the first segment, so `"169.254.169.254/domain"` passes the structural guard. Watchlist rows are operator-authored (single user), so this internal-IP-host case is accepted; closable later by calling `is_safe_public_url` on the built host inside `phenom._parts`/`workday._parts`.
- [ ] Step 1: failing tests. `watchlist.test.ts`:
  ```ts
  it('rejects a slug with host-injection metacharacters', async () => {
      const r = await addWatchedCompany({ source: 'greenhouse', slug: 'a@evil.com', name: 'X' })
      expect(r.success).toBe(false)
      expect(mockPrisma.watched_companies.create).not.toHaveBeenCalled()
  })
  it('accepts a legit multi-part slug', async () => {
      mockPrisma.watched_companies.findFirst.mockResolvedValue(null)
      mockPrisma.watched_companies.create.mockResolvedValue({ id: 1 } as any)
      const r = await addWatchedCompany({ source: 'workday', slug: 'relx/wd3/relx', name: 'RELX' })
      expect(r.success).toBe(true)
  })
  ```
  `test_config.py`:
  ```python
  def test_rejects_slug_with_bad_chars():
      with pytest.raises(config.ConfigError):
          config.load_config("companies:\n  - {source: greenhouse, slug: 'a b', name: X}")

  def test_allows_multipart_slug():
      cfg = config.load_config("companies:\n  - {source: workday, slug: 't/wd3/site', name: X}")
      assert cfg.companies[0].slug == "t/wd3/site"
  ```
  (Adapt `config.load_config`'s input shape to the real loader — it may take a path, not a string; use `tmp_path` if so.)
- [ ] Step 2: run, expect FAIL — `cd apps/web && npx jest src/__tests__/watchlist.test.ts` and `rtk proxy python3 -m pytest apps/worker/tests/test_config.py`.
- [ ] Step 3: implement.
  - Web `addWatchedCompany`, after the `!source||!slug||!name` check:
  ```ts
          // Slug is interpolated into a fetch URL host/path in the worker
          // (e.g. https://{slug}.icims.com). Allow alnum . _ - and single '/'-joined
          // segments (workday "tenant/dc/site", phenom "host/domain"); block host-injection
          // metacharacters (@ : ? # % \ whitespace) and path traversal.
          if (!/^[A-Za-z0-9._/-]+$/.test(slug) || slug.includes('..') ||
              slug.startsWith('/') || slug.endsWith('/') || slug.includes('//')) {
              return { success: false, error: 'slug contains invalid characters' }
          }
  ```
  - Worker `config.py`: add `import re` (top) and a helper, then call it in `_parse_companies` after the source validation:
  ```python
  _SLUG_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

  def _valid_slug(slug: str) -> bool:
      return (bool(_SLUG_RE.match(slug)) and ".." not in slug
              and not slug.startswith("/") and not slug.endswith("/") and "//" not in slug)
  ```
  ```python
          slug = str(c["slug"])
          if not _valid_slug(slug):
              raise ConfigError(f"companies[{i}] slug {slug!r} has invalid characters")
  ```
- [ ] Step 4: run, expect PASS — both Step 2 commands, plus `rtk proxy python3 -m pytest apps/worker/tests/test_config.py apps/worker/tests/test_run.py`.
- [ ] Step 5: docs — SPEC (watchlist/config): document the slug charset rule; PROGRESS: accepted-residual line for phenom/workday internal-IP host; CHANGELOG `### Security`: "Validate watchlist slug structure at the web + config write boundaries."
- [ ] Step 6: commit — `git add apps/web/src/lib/actions.ts apps/web/src/__tests__/watchlist.test.ts apps/worker/ats_worker/config.py apps/worker/tests/test_config.py docs/ CHANGELOG.md && git commit -m "fix: validate watchlist slug charset at write boundaries"`

### Task 2.12: Harden codex usage-capture rollout deletion (harden + document)  [Phase 2]
**Files:** Modify `apps/worker/ats_worker/score.py` `_capture_usage` and the `fit()` exec block; Test `apps/worker/tests/test_score.py`.
**Why "harden + document":** codex owns the rollout filename, so we can't tag "ours" deterministically without depending on the rollout JSONL schema. Two schema-independent guards address the finding: (1) only delete the newest rollout when it is the *sole* rollout newer than `since_mtime` (0 or ≥2 newer ⇒ a concurrent session ran ⇒ skip deletion); (2) move the capture call into a `finally` so the résumé-bearing rollout is reaped even when the exec fails.
**Reconcile with Phase 5:** this task edits `score.py` while it is still a single module (Phase 2 < Phase 5). After Phase 5, `_capture_usage`/`_newest_rollout_after` live in `score/usage.py` — if you somehow do this after Phase 5, apply the edit there.
- [ ] Step 1: failing tests in `test_score.py` (adapt `_fake_sessions`/`_write_rollout`/`_rollout_line` to the real helpers):
  ```python
  def test_capture_usage_skips_delete_when_concurrent_rollout_present(tmp_path, monkeypatch):
      sess = _fake_sessions(monkeypatch, tmp_path)
      ours = _write_rollout(sess, [_rollout_line(32.0, 10080, 1)], name="rollout-a.jsonl")
      theirs = _write_rollout(sess, [_rollout_line(5.0, 300, 2)], name="rollout-b.jsonl")
      score._capture_usage(str(tmp_path / "u.json"), since_mtime=0.0)
      assert ours.exists() and theirs.exists()   # ambiguous -> delete nothing

  def test_codex_scorer_cleans_rollout_on_failure(monkeypatch, tmp_path):
      sess = _fake_sessions(monkeypatch, tmp_path)
      def run(cmd, **kw):
          _write_rollout(sess, [_rollout_line(1.0, 1, 1)])   # rollout written, then fail
          return Mock(returncode=1, stdout="boom", stderr="")
      monkeypatch.setattr(score.subprocess, "run", run)
      with pytest.raises(score.ScoreError):
          score.make_codex_scorer("gpt-5.6-sol", usage_path=str(tmp_path / "u.json"))(
              [{**POSTING, "id": 1}], {"swe": "r"})
      assert not (sess / "rollout-x.jsonl").exists()   # résumé prompt not left on disk
  ```
- [ ] Step 2: run, expect FAIL — `rtk proxy python3 -m pytest apps/worker/tests/test_score.py -k "capture_usage_skips_delete or cleans_rollout_on_failure"`.
- [ ] Step 3: implement.
  - `_capture_usage`: gather all newer rollouts once; read the newest for the snapshot; delete only when exactly one is newer:
  ```python
      try:
          newer = _rollouts_after(since_mtime)   # list[(mtime, path)], newest last
          if not newer:
              return
          roll = newer[-1][1]
          latest = None
          with open(roll, encoding="utf-8") as fh:
              for line in fh:
                  if "rate_limits" in line:
                      latest = line
          # Delete ONLY when this is unambiguously the sole new rollout: a concurrent
          # codex session would also land here, and removing its rollout would nuke the
          # operator's session history. Ambiguous -> leave every rollout in place.
          if len(newer) == 1:
              try:
                  os.remove(roll)
              except OSError:
                  pass
          if not latest:
              return
          # ... existing snapshot-write path continues unchanged ...
  ```
  Add the helper (replaces `_newest_rollout_after`, or sits beside it):
  ```python
  def _rollouts_after(mtime: float):
      out = []
      for root, _d, files in os.walk(_sessions_dir()):
          for f in files:
              if f.startswith("rollout-") and f.endswith(".jsonl"):
                  p = os.path.join(root, f)
                  try:
                      t = os.path.getmtime(p)
                  except OSError:
                      continue
                  if t > mtime:
                      out.append((t, p))
      return sorted(out)
  ```
  - `fit()` exec block: move usage capture into a `finally` so it runs on failure paths too (wrap the existing subprocess-run + JSON read; keep the exact ScoreError messages the current code raises):
  ```python
              usage_since = _rollout_mtime_ceiling() if usage_path else 0.0
              try:
                  # ... existing subprocess.run + returncode check + json.load(out_path) ...
              finally:
                  # Runs on success AND failure: since capture drops --ephemeral, the
                  # rollout (full résumé+JD prompt) must be reaped even when the exec fails.
                  if usage_path:
                      _capture_usage(usage_path, usage_since)
  ```
- [ ] Step 4: run, expect PASS — `rtk proxy python3 -m pytest apps/worker/tests/test_score.py` (the existing `deletes_it`/`captures_usage_and_drops_ephemeral` single-rollout tests still pass).
- [ ] Step 5: docs — SPEC §11 / §7.1: document the "delete only the sole new rollout" + finally-cleanup behavior; PROGRESS: close the rollout-race/résumé-on-disk item; CHANGELOG `### Security`: "codex usage capture only deletes an unambiguous rollout and cleans up on failure."
- [ ] Step 6: commit — `git add apps/worker/ats_worker/score.py apps/worker/tests/test_score.py docs/ CHANGELOG.md && git commit -m "fix(worker): harden codex rollout cleanup (race + resume-on-disk)"`

### Task 2.13: Pin Docker base image + CI actions by SHA digest (LOW — optional)  [Phase 2]
**Files:** Modify `apps/web/Dockerfile:3` (`node:20-alpine`); Modify `.github/workflows/ci.yml` (`actions/checkout@v4`, `setup-node@v4`, `setup-python@v5`, `upload-artifact@v4`, `cache@v4`). No test — verified by CI going green.
**Note:** optional / low priority. Digests must be resolved at execution time (`docker buildx imagetools inspect node:20-alpine`; each action's release-page commit SHA) — append `# tag` comments so renovate/dependabot can still bump them.
- [ ] Step 1: baseline — `grep -n '@v[0-9]' .github/workflows/ci.yml` lists the floating refs; `grep node:20-alpine apps/web/Dockerfile`.
- [ ] Step 2: N/A (config pin).
- [ ] Step 3: implement — Dockerfile line 3 → `FROM node:20-alpine@sha256:<digest> AS base` (resolve live). In `ci.yml` replace each `uses: actions/<x>@v4` with `uses: actions/<x>@<commit-sha> # v4`.
- [ ] Step 4: verify — push branch; CI (build + both suites + schema-drift guard) goes green.
- [ ] Step 5: docs — CHANGELOG `### Security`: "Pin CI actions and the web Docker base image by SHA digest."
- [ ] Step 6: commit — `git add apps/web/Dockerfile .github/workflows/ci.yml CHANGELOG.md && git commit -m "chore(ci): pin base image + actions by digest"`

## Phase 3 — Dead code removal

*Delete ~120 production lines + their tests. Grep-verify no caller before each deletion. `score_posting` is the one non-trivial item — its tests are the sole unit coverage for `screen_posting`/`_normalize_score`, so they must be MIGRATED, not dropped, or coverage falls 88% → 15%.*

### Task 3.1: Remove production-dead `score_posting` (coverage-gated migration)  [Phase 3]
**Files:**
- Modify `apps/worker/ats_worker/score.py` — delete `def score_posting(...)` (~lines 345-386, 42 ln); fix now-dangling doc refs (repoint "`score_posting` composes…" → `pipeline.run_score` / `_persist_scored`, the real composer today)
- Modify `apps/worker/tests/test_score.py` — **~50 `score.score_posting(...)` call sites**

**CRITICAL coverage finding (measured):** `score_posting`'s tests are the *sole* unit vehicle for `screen_posting` and `_normalize_score`. `test_pipeline`/`test_feed_pipeline` mock `screen_fn`, so blanket-deleting `test_score.py` drops `score.py` coverage 88% → 15% and breaks the 85% floor. The deletion must **migrate** the screen/normalize assertions, not drop them.

- [ ] Step 1 — Confirm production-dead + that `run_score` covers the composition:
  ```bash
  grep -rn "score_posting" apps/worker/ats_worker | grep -v "def score_posting"   # expect: no executable caller (only comments)
  grep -rn "score.score_posting" apps/worker/tests | grep -v test_score.py         # expect: NONE
  ```
  Composition is already covered by `test_pipeline.py` (`test_run_score_disqualified_is_discarded_with_reason` + `test_run_score_persists_disqualified_without_fit` = screen-gates-fit; `test_run_score_failure_records_error_and_increments_attempts` = normalize-raises→`mark_failed`; `test_run_score_falls_back_*` = normalize+screen happy path). So the pure-gating `score_posting` tests are redundant and may be deleted.
- [ ] Step 2 — Delete `score.score_posting` + repoint its doc refs. Then in `test_score.py`:
  - **DELETE (redundant with run_score/test_pipeline):** `test_screen_gates_the_paid_score_call`, `test_no_candidate_means_one_call_and_not_disqualified` (fold its "no checklist ⇒ no Ollama call" assert into the migrated screen test), `test_score_fit_error_propagates_to_mark_failed`, `test_candidate_screen_call_disqualifies_and_omits_resume`.
  - **MIGRATE to `score.screen_posting(POSTING, http=…, ollama_host="h", model="m", candidate=…)`** (drop the `score_fit=`/`RESUME` args; assert on `disqualified`/`disqualification_reason`/`screen`): `test_screen_parse_failure_falls_back_to_scored_not_screened` and the screen-behavior blocks (degree / clearance / sponsorship / work-auth / internship / location disqualification).
  - **MIGRATE to `score._normalize_score(card)`** (call with the raw scorecard dict): `test_assessment_lists_and_notes_coerced_to_defaults`, `test_absent_score_key_raises_not_silently_zero`, `test_missing_or_malformed_assessment_raises`, `test_non_numeric_score_raises_score_error`, `test_float_and_string_scores_accepted`, `test_assessment_keyword_coercion_tolerates_bare_string_and_nesting`, `test_recommended_resume_passed_through_normalization`, `test_insufficient_context_normalized_true`/`_absent_defaults_false`, `test_recommended_resume_absent_or_blank_is_omitted`. Delete `test_score_fit_receives_the_resumes_dict` (obsolete — `_normalize_score` takes no `resumes`).
- [ ] Step 3 — Run worker suite with the coverage gate; confirm PASS and score.py ≥ its 88% baseline:
  ```bash
  cd apps/worker && rtk proxy python3 -m pytest --cov --cov-report=term-missing
  ```
  If migration is skipped and tests are merely deleted, this FAILS at 15% on score.py — that is the guardrail.
- [ ] Step 4 — Docs: remove the `score_posting … production-dead` bullet from `docs/PROGRESS.md`; CHANGELOG `### Removed`: "Worker `score_posting()` removed (production-dead composer; screen/normalize unit assertions migrated to direct tests, coverage floor held)."
- [ ] Step 5 — Commit:
  ```bash
  git add apps/worker/ats_worker/score.py apps/worker/tests/test_score.py docs/PROGRESS.md CHANGELOG.md
  git commit -m "refactor(worker): drop dead score_posting; migrate screen/normalize unit tests"
  ```

### Task 3.2: Delete orphaned worker `Dockerfile` + `.dockerignore`  [Phase 3]
**Files:** Delete `apps/worker/Dockerfile` (25 ln), delete `apps/worker/.dockerignore` (orphaned — only the Dockerfile consumed it); Modify `docs/SPEC.md` §6. No tests.
- [ ] Step 1 — Confirm nothing builds it:
  ```bash
  grep -rniE "worker/Dockerfile|apps/worker/Dockerfile|dockerfile" docker-compose*.yml Makefile .github 2>/dev/null   # expect: NONE (only SPEC.md prose)
  ```
- [ ] Step 2 — `git rm apps/worker/Dockerfile apps/worker/.dockerignore`. In `docs/SPEC.md` §6 delete the sentence "`apps/worker/Dockerfile` remains in-tree but is referenced by nothing." (the de-containerization it describes stays). *(Note: Phase 3.9 also edits SPEC §6 host.docker.internal — order-independent, separate lines.)*
- [ ] Step 3 — No suite runs Docker; sanity: `make check-schema` (expect PASS, unaffected).
- [ ] Step 4 — Docs: remove the "Worker `Dockerfile` — orphaned" bullet from `docs/PROGRESS.md`; CHANGELOG `### Removed`: "Worker `Dockerfile` + `.dockerignore` deleted (de-containerized 2026-07-16; nothing built them)."
- [ ] Step 5 — Commit:
  ```bash
  git add -A apps/worker docs/SPEC.md docs/PROGRESS.md CHANGELOG.md
  git commit -m "chore(worker): delete orphaned Dockerfile/.dockerignore"
  ```

### Task 3.3: Remove never-read `threshold` config key  [Phase 3]
**Files:** Modify `apps/worker/ats_worker/config.py` (docstring, field, parse line, `DEFAULT_THRESHOLD`), `apps/worker/config.yaml.example`; Modify `apps/worker/tests/test_config.py`; cleanup `apps/worker/tests/integration/test_pipeline_e2e.py`. **Keep `_int_field`** (used by `schedule_hours`); `DEFAULT_THRESHOLD` becomes dead → remove it too.
- [ ] Step 1 — Confirm never read in production:
  ```bash
  grep -rn "\.threshold\|cfg.threshold\|DEFAULT_THRESHOLD" apps/worker/ats_worker   # expect: only config.py (def) + the "old score>=threshold gate is gone" comments
  ```
- [ ] Step 2 — Delete the `threshold: int = DEFAULT_THRESHOLD` field, the `threshold=_int_field(...)` parse line, `DEFAULT_THRESHOLD = 75`, and drop `threshold` from the module docstring. Delete the `config.yaml.example` threshold line. In `test_config.py`: drop `threshold: 80` from the FULL fixture and the `cfg.threshold == 80` asserts; delete the `assert cfg.threshold == 75`; drop `"threshold"` from the parametrize (leave `["schedule_hours"]`); in `test_load_from_plain_string_path` swap the probe to a live key (`schedule_hours`). `test_pipeline_e2e.py` still passes (unknown key ignored) but drop the stale `threshold: 75\n` line.
- [ ] Step 3 — Run worker suite + coverage gate: `cd apps/worker && rtk proxy python3 -m pytest --cov --cov-report=term-missing` (expect PASS, ≥85%).
- [ ] Step 4 — Docs: remove the "`threshold` config key … never read" bullet from `docs/PROGRESS.md`; CHANGELOG `### Removed`: "`threshold` config key removed (parsed/validated/documented but never read; notify gates on the verdict predicate)."
- [ ] Step 5 — Commit:
  ```bash
  git add apps/worker/ats_worker/config.py apps/worker/config.yaml.example apps/worker/tests/test_config.py apps/worker/tests/integration/test_pipeline_e2e.py docs/PROGRESS.md CHANGELOG.md
  git commit -m "refactor(worker): drop unused threshold config key"
  ```

### Task 3.4: Simplify `get_by_status` — drop test-only `min_score`/`limit` kwargs  [Phase 3]
**Files:** Modify `apps/worker/ats_worker/db.py:145-156`; Modify `apps/worker/tests/test_db.py`.
- [ ] Step 1 — Confirm the only prod call passes no kwargs:
  ```bash
  grep -rn "get_by_status" apps/worker/ats_worker   # expect: def + one call get_by_status(conn, "new") at pipeline.py
  ```
- [ ] Step 2 — Collapse the body to:
  ```python
  def get_by_status(conn: sqlite3.Connection, status: str):
      return conn.execute(
          "SELECT * FROM job_postings WHERE pipeline_status=? ORDER BY score DESC, id ASC",
          [status],
      ).fetchall()
  ```
  In `test_db.py` **delete** `test_get_by_status_can_filter_high_scores`, `test_get_by_status_min_score_is_inclusive_and_limited`, `test_get_by_status_null_score_excluded_by_min_score`, and trim the section comment. **Keep** `test_get_by_status_orders_by_score_then_id` (ordering retained).
- [ ] Step 3 — Coverage gate: `cd apps/worker && rtk proxy python3 -m pytest --cov --cov-report=term-missing` (expect PASS, ≥85%).
- [ ] Step 4 — Docs: remove the "`get_by_status` `min_score`/`limit` kwargs" bullet from `docs/PROGRESS.md`; CHANGELOG `### Removed`: "`db.get_by_status` `min_score`/`limit` kwargs removed (test-only; sole prod caller passes neither)."
- [ ] Step 5 — Commit:
  ```bash
  git add apps/worker/ats_worker/db.py apps/worker/tests/test_db.py docs/PROGRESS.md CHANGELOG.md
  git commit -m "refactor(worker): simplify get_by_status signature"
  ```

### Task 3.5: Combined micro-deletions — `simplify.SOURCE`, `_flag` "remote", `test:all`, stale `.gitignore`  [Phase 3]
**Files:** `apps/worker/ats_worker/feed/simplify.py`, `apps/worker/ats_worker/score.py` (`_flag` truthy set) + `apps/worker/tests/test_score.py` (its parametrize), `apps/web/package.json` (`test:all` line), `.gitignore` (stale entries). Grouped: worker pytest covers the Python edits, `git status` covers the config edits.
- [ ] Step 1 — Confirm each is truly unreferenced:
  ```bash
  cd /home/halcyon/root/ats
  grep -rn "simplify.SOURCE" apps/worker --include="*.py"                    # expect: NONE beyond the def
  grep -rn "\"remote\"" apps/worker/ats_worker/score.py                       # expect: only _flag's truthy set
  grep -rn "test:all" . --include="*.json" --include="*.yml" Makefile 2>/dev/null | grep -v node_modules   # expect: only package.json (CI/Make use test:coverage)
  ls -d logs screenshots .cursor 2>/dev/null; find . -name '*.tar' -not -path './node_modules/*'   # expect: nothing matches the 4 gitignore lines
  ```
- [ ] Step 2 — Delete: `feed/simplify.py` `SOURCE = "simplify"`; the `"remote"` token from `_flag`'s truthy set → `{"true", "yes", "1", "required"}` (in `test_score.py` move `"remote"` from the truthy parametrize into the falsy one so `_flag("remote") is False` stays asserted); the `"test:all": …` line in `package.json` (leave the JSON valid); the `.cursor`, `*.tar`, `logs/`, `screenshots/` lines in `.gitignore`.
- [ ] Step 3 — Verify both suites green + nothing newly tracked:
  ```bash
  cd apps/worker && rtk proxy python3 -m pytest --cov --cov-report=term-missing   # PASS, ≥85%
  cd ../.. && git status --short   # only intended edits; no previously-ignored file appears untracked
  ```
- [ ] Step 4 — Docs: remove the four bullets from `docs/PROGRESS.md`; CHANGELOG `### Removed`: "Debris swept: unused `simplify.SOURCE`, dead `\"remote\"` token in `_flag`, orphaned `test:all` npm script, and 4 stale `.gitignore` entries."
- [ ] Step 5 — Commit:
  ```bash
  git add apps/worker/ats_worker/feed/simplify.py apps/worker/ats_worker/score.py apps/worker/tests/test_score.py apps/web/package.json .gitignore docs/PROGRESS.md CHANGELOG.md
  git commit -m "chore: remove dead simplify.SOURCE, _flag remote token, test:all, stale gitignore"
  ```

### Task 3.6: Drop unused `allNodes` param from `SankeyChart.getNodeColumn`  [Phase 3]
**Files:** Modify `apps/web/src/components/SankeyChart.tsx` (signature + call site). No test dies — `getNodeColumn` is module-private; `Dashboard.test.tsx` renders `SankeyChart` end-to-end and stays green.
- [ ] Step 1 — Confirm private + param unused in body:
  ```bash
  grep -rn "getNodeColumn\|allNodes" apps/web/src   # expect: only def + call; allNodes never read inside
  ```
- [ ] Step 2 — Signature → `function getNodeColumn(name: string, data: { from: string; to: string }[]): number`. Call site → `getNodeColumn(n, data)`. Leave `nodeSet` (still used by the column-grouping loop).
- [ ] Step 3 — Lint + affected test: `cd apps/web && npx jest src/components/__tests__/Dashboard.test.tsx && npm run lint`.
- [ ] Step 4 — Docs: remove the "`SankeyChart.getNodeColumn` `allNodes` param unused" bullet from `docs/PROGRESS.md`; CHANGELOG `### Removed`: "`SankeyChart.getNodeColumn` unused `allNodes` param dropped."
- [ ] Step 5 — Commit:
  ```bash
  git add apps/web/src/components/SankeyChart.tsx docs/PROGRESS.md CHANGELOG.md
  git commit -m "refactor(web): drop unused allNodes param from SankeyChart.getNodeColumn"
  ```

### Task 3.7: Delete never-invoked `tools/seed_db.mjs`  [Phase 3]
**Files:** Delete `tools/seed_db.mjs`; Modify `CLAUDE.md` (repo-map line); optionally refresh the stale comment at `apps/web/e2e/helpers/seed.mjs`. No tests.
- [ ] Step 1 — Confirm nothing invokes it:
  ```bash
  grep -rn "seed_db" . --include="*.mjs" --include="*.js" --include="*.json" --include="*.yml" Makefile 2>/dev/null | grep -v node_modules   # expect: NONE that execute it
  ```
- [ ] Step 2 — `git rm tools/seed_db.mjs`. In `CLAUDE.md` drop ` · seed_db.mjs` from the `tools/` repo-map line (leave `check_schema_drift.mjs`).
- [ ] Step 3 — Confirm seeding paths still resolve: `ls apps/web/prisma/seed-dev.mjs apps/web/e2e/helpers/seed.mjs`.
- [ ] Step 4 — Docs: remove the "`tools/seed_db.mjs` — invoked by nothing" bullet from `docs/PROGRESS.md`; CHANGELOG `### Removed`: "`tools/seed_db.mjs` deleted (superseded by `prisma/seed-dev.mjs` + `e2e/helpers/seed.mjs`)."
- [ ] Step 5 — Commit:
  ```bash
  git add -A tools CLAUDE.md apps/web/e2e/helpers/seed.mjs docs/PROGRESS.md CHANGELOG.md
  git commit -m "chore(tools): delete unused seed_db.mjs"
  ```

### Task 3.8: Correct stale native-worker doc lines (host.docker.internal / requirements-dev)  [Phase 3] — doc-only
**Files:** Modify `apps/worker/.env.example`, `docs/SPEC.md`, `CLAUDE.md` (Gotchas), `.github/workflows/ci.yml` (comment). No code, no tests. *(The web notes dead-code is covered by Task 1.6 — not duplicated here.)*
- [ ] Step 1 — Enumerate the stale references (worker is native → Ollama is `localhost:11434`):
  ```bash
  grep -rn "host.docker.internal" CLAUDE.md docs/SPEC.md apps/worker/.env.example
  ```
- [ ] Step 2 — Edit (doc-only): `.env.example` → `OLLAMA_HOST=http://localhost:11434`, drop the Docker/`extra_hosts` sub-bullets. `SPEC.md` + `CLAUDE.md` Gotchas → native `localhost:11434` reality. `ci.yml` comment → current dep list.
- [ ] Step 3 — Confirm no code depended on the old default:
  ```bash
  grep -rn "host.docker.internal" apps/worker/ats_worker   # expect: NONE (docs only)
  cd apps/worker && rtk proxy python3 -m pytest -q   # PASS (unchanged)
  ```
- [ ] Step 4 — Docs: remove the "Stale doc lines" bullet from `docs/PROGRESS.md`; CHANGELOG `### Changed`: "Docs corrected for the native worker (OLLAMA_HOST default → localhost:11434; dropped stale host.docker.internal/extra_hosts notes; refreshed CI requirements-dev comment)."
- [ ] Step 5 — Commit:
  ```bash
  git add apps/worker/.env.example docs/SPEC.md CLAUDE.md .github/workflows/ci.yml docs/PROGRESS.md CHANGELOG.md
  git commit -m "docs: fix stale host.docker.internal refs for native worker"
  ```

## Phase 4 — Small / safe architecture fixes

*Drift guard, indexes, transactions, `busy_timeout`, DI cleanup. TDD; one schema change (index). The hard `@@unique` is deliberately deferred (see cross-phase notes).*

### Task 4.1: Add a cross-service source-enum drift guard  [Phase 4]
**Files:** NEW `apps/worker/tests/test_source_enums_sync.py`; reads `apps/web/src/lib/constants.ts`, `apps/worker/ats_worker/config.py`, `fetch/__init__.py`, `db.py`. Models on `tests/test_schema_sync.py` (text-parse the `.ts`, import the cheap Python modules — `config` avoids importing `requests`).
**Scope decision (Ponytail):** guard the three genuinely-duplicated + cheaply-comparable items — `VALID_SOURCES`, `RECIPE_SOURCES`, and the `LOW_CONTEXT_MAX_DESCRIPTION_LENGTH`/`>= 200` literal. Do **not** guard the scattered `pipeline_status` vocabulary or the full verdict-predicate SQL (fragile, low value) — record those as known-unguarded duplication in PROGRESS.
- [ ] Step 1: write the failing test:
  ```python
  """Guard: board-source allowlists and the low-context threshold must not drift
  across the worker (config.py / fetch) and the web UI (constants.ts).
  Mirrors test_schema_sync.py: text-parse the .ts, import the Python modules."""
  from __future__ import annotations
  import re
  from pathlib import Path

  from ats_worker import config, fetch, db

  CONSTANTS_TS = Path(__file__).parents[3] / "apps" / "web" / "src" / "lib" / "constants.ts"


  def _ts_array(name: str) -> list[str]:
      m = re.search(rf"export const {name}\s*=\s*\[(.*?)\]", CONSTANTS_TS.read_text(), re.S)
      assert m, f"{name} not found in constants.ts"
      return re.findall(r"'([^']+)'", m.group(1))


  def _ts_int(name: str) -> int:
      m = re.search(rf"export const {name}\s*=\s*(\d+)", CONSTANTS_TS.read_text())
      assert m, f"{name} not found in constants.ts"
      return int(m.group(1))


  def test_valid_sources_match_web():
      assert list(config.VALID_SOURCES) == _ts_array("VALID_SOURCES")


  def test_recipe_sources_match_web_and_fetch():
      assert list(config.RECIPE_SOURCES) == _ts_array("RECIPE_SOURCES")
      assert set(config.RECIPE_SOURCES) == set(fetch.RECIPE_SOURCES)


  def test_valid_sources_are_real_adapters():
      assert set(config.VALID_SOURCES) <= set(fetch.ADAPTERS)


  def test_low_context_threshold_matches_web():
      src = Path(db.__file__).read_text()
      m = re.search(r"LENGTH\(TRIM\(description\)\)\s*>=\s*(\d+)", src)
      assert m, "low-context length clause not found in db.get_notifiable"
      assert int(m.group(1)) == _ts_int("LOW_CONTEXT_MAX_DESCRIPTION_LENGTH")
  ```
  (Confirm `fetch.RECIPE_SOURCES` exists / the `db.get_notifiable` SQL literal shape when you read them; adjust the regex to the real clause.)
- [ ] Step 2: prove the guard bites — temporarily delete `'lever',` from `constants.ts` VALID_SOURCES, run `cd apps/worker && rtk proxy python3 -m pytest tests/test_source_enums_sync.py -q`; expect FAIL. Revert.
- [ ] Step 3: no product code changes — the guard passes against current source (all lists already agree).
- [ ] Step 4: run `cd apps/worker && rtk proxy python3 -m pytest tests/test_source_enums_sync.py -q`; expect PASS.
- [ ] Step 5: docs — PROGRESS: add a line noting `pipeline_status` vocabulary + the notify/matched verdict-predicate SQL remain documented-not-guarded. CHANGELOG `### Added`: "Cross-service drift guard for board-source allowlists + low-context threshold."
- [ ] Step 6: commit
  ```bash
  git add apps/worker/tests/test_source_enums_sync.py docs/PROGRESS.md CHANGELOG.md
  git commit -m "test(worker): guard source-enum/low-context drift across web + worker"
  ```

### Task 4.2: Extend the schema-drift guard to also check nullability  [Phase 4]
**Files:** Modify `apps/worker/tests/test_schema_sync.py` (extend the pytest guard only). Leave `tools/check_schema_drift.mjs` names-only + add a one-line comment noting the pytest guard is the deeper source of truth (extending both JS+Python isn't worth it; `make test-worker` runs the pytest guard in CI).
- [ ] Step 1: rewrite the two helpers to carry nullability (field → `nullable: bool`), and add the nullability assertion:
  ```python
  def _prisma_models() -> dict[str, dict[str, bool]]:
      """Map model name -> {scalar field: is_nullable}. Relation fields excluded."""
      text = re.sub(r"//.*", "", PRISMA.read_text())
      models = dict(re.findall(r"model\s+(\w+)\s*\{(.*?)\}", text, re.S))
      names = set(models)
      out: dict[str, dict[str, bool]] = {}
      for name, body in models.items():
          fields: dict[str, bool] = {}
          for line in body.splitlines():
              line = line.strip()
              if not line or line.startswith("@@") or line.startswith("//"):
                  continue
              parts = line.split()
              if len(parts) < 2:
                  continue
              field, raw_type = parts[0], parts[1]
              ftype = raw_type.rstrip("?").rstrip("[]").rstrip("?")
              if ftype in names:   # a relation field, not a column
                  continue
              fields[field] = raw_type.endswith("?")   # nullable iff optional
          out[name] = fields
      return out


  def _sql_tables() -> dict[str, dict[str, bool]]:
      """Map table name -> {column: is_nullable} from CREATE TABLE statements."""
      text = SCHEMA_SQL.read_text()
      out: dict[str, dict[str, bool]] = {}
      for tname, body in re.findall(r'CREATE TABLE "(\w+)"\s*\((.*?)\n\);', text, re.S):
          cols: dict[str, bool] = {}
          for line in body.splitlines():
              line = line.strip()
              m = re.match(r'"(\w+)"', line)
              if m and not line.startswith("CONSTRAINT"):
                  cols[m.group(1)] = "NOT NULL" not in line   # nullable iff no NOT NULL
          out[tname] = cols
      return out
  ```
  and the assertion body:
  ```python
      for model, fields in prisma.items():
          assert model in sql, f"schema.sql is missing table {model!r} (Prisma drift)"
          missing = set(fields) - set(sql[model])
          assert not missing, f"schema.sql {model!r} missing columns {sorted(missing)} (Prisma drift)"
          extra = set(sql[model]) - set(fields)
          assert not extra, f"schema.sql {model!r} has columns {sorted(extra)} not in Prisma"
          for col, nullable in fields.items():
              assert sql[model][col] == nullable, (
                  f"schema.sql {model!r}.{col} nullable={sql[model][col]} "
                  f"!= Prisma nullable={nullable} (Prisma drift)")
  ```
  (Reconcile helper/constant names — `PRISMA`, `SCHEMA_SQL` — with the current `test_schema_sync.py`.)
- [ ] Step 2: prove it bites — temporarily change fixture `schema.sql` `"score" INTEGER,` → `"score" INTEGER NOT NULL,` (Prisma has `score Int?`), run `cd apps/worker && rtk proxy python3 -m pytest tests/test_schema_sync.py -q`; expect FAIL. Revert.
- [ ] Step 3: add the `.mjs` note-comment: `// Nullability/type drift is caught by the deeper pytest guard tests/test_schema_sync.py; this JS guard stays names-only so make check-schema needs no Python.`
- [ ] Step 4: run `cd apps/worker && rtk proxy python3 -m pytest tests/test_schema_sync.py -q` (PASS) and `make check-schema` (in sync).
- [ ] Step 5: docs — CHANGELOG `### Added`: "Schema-drift guard now also checks column nullability (pytest guard)."
- [ ] Step 6: commit
  ```bash
  git add apps/worker/tests/test_schema_sync.py tools/check_schema_drift.mjs CHANGELOG.md
  git commit -m "test(worker): schema-drift guard checks column nullability"
  ```

### Task 4.3: Add missing index on status_history.application_id  [Phase 4]
**Files:** `apps/web/prisma/schema.prisma` (add index) → `make db-push` → `apps/worker/tests/fixtures/schema.sql` (add CREATE INDEX) → `make check-schema` + worker `test_schema_sync.py` (both ignore indexes, so they stay green — the fixture index is for test-DB fidelity).
- [ ] Step 1: confirm the index is absent — `grep -n "application_id" apps/worker/tests/fixtures/schema.sql` shows only the FK on `job_postings`.
- [ ] Step 2: `make check-schema` (PASS now, index-agnostic) — establishes the guard won't false-fail.
- [ ] Step 3: implement. In `schema.prisma` model `status_history`, add `@@index([application_id])`:
  ```prisma
  model status_history {
    id             Int          @id @default(autoincrement())
    application_id Int
    status         String
    timestamp      String
    applications   applications @relation(fields: [application_id], references: [id], onDelete: Cascade, onUpdate: NoAction)

    @@index([application_id])
  }
  ```
  Then `make db-push`. Then add to `schema.sql` (after the `feed_unresolved_reason_idx` line):
  ```sql
  CREATE INDEX "status_history_application_id_idx" ON "status_history"("application_id");
  ```
- [ ] Step 4: `make db-push` then `make check-schema` (in sync) and `cd apps/worker && rtk proxy python3 -m pytest tests/test_schema_sync.py -q` (PASS).
- [ ] Step 5: docs — SPEC §8: note the `status_history.application_id` index (queried by `getApplicationHistory`, `deleteHistoryItem`, `getStatusFlow`). CHANGELOG `### Added`: "Index on `status_history.application_id`."
- [ ] Step 6: commit
  ```bash
  git add apps/web/prisma/schema.prisma apps/worker/tests/fixtures/schema.sql docs/SPEC.md CHANGELOG.md
  git commit -m "perf(web): index status_history.application_id"
  ```

### Task 4.4: Record feed board-fetch failures instead of dropping ids  [Phase 4]
**Files:** `apps/worker/ats_worker/pipeline.py` (`_fetch_group` board branch + `run_feed` failure-recording reason); `apps/worker/tests/test_feed_pipeline.py`; `apps/web/prisma/schema.prisma` (extend the `reason` comment — comment-only, no db-push).
**Root cause:** the board branch does `_safe_call(fetch_fn,...) or []` and always returns `failed_ids=[]`, so a raising board list-fetch silently drops every feed-surfaced id (no `feed_unresolved` row). Only detail sources record failures.
- [ ] Step 1: extend `test_run_feed_isolates_a_failing_board` — after the existing `inserted` assert add:
  ```python
      # greenhouse's list fetch RAISED: its surfaced id is recorded, not dropped.
      n = conn.execute(
          "SELECT COUNT(*) FROM feed_unresolved WHERE reason='list_fetch_failed'"
      ).fetchone()[0]
      assert n == 1
  ```
- [ ] Step 2: run `cd apps/worker && rtk proxy python3 -m pytest tests/test_feed_pipeline.py::test_run_feed_isolates_a_failing_board -q`; expect FAIL (`0 == 1`).
- [ ] Step 3: implement. In `_fetch_group`, replace the board branch:
  ```python
      # Board source: list the whole board, keep only the feed-surfaced ids. A raise
      # (None) is a real failure — return the ids as failed so run_feed records them
      # rather than silently dropping the surfaced postings.
      postings = _safe_call(fetch_fn, source, slug, name)
      if postings is None:
          return [], list(missing)
      return [p for p in postings if p.get("external_id") in missing], []
  ```
  In `run_feed`, branch the recorded reason on source kind:
  ```python
                  reason=("detail_fetch_failed" if source in detail_sources
                          else "list_fetch_failed"),
  ```
  (Confirm the `missing`/`detail_sources` variable names against the real `_fetch_group`/`run_feed`.)
- [ ] Step 4: run `cd apps/worker && rtk proxy python3 -m pytest tests/test_feed_pipeline.py -q`; expect PASS (detail tests keep `detail_fetch_failed`; new board case gets `list_fetch_failed`).
- [ ] Step 5: docs — `schema.prisma` extend the `reason` comment to include `list_fetch_failed | detail_fetch_failed`. SPEC §7.1 feed section. CHANGELOG `### Fixed`: "Feed board-source fetch failures are recorded (feed_unresolved) instead of silently dropping surfaced ids."
- [ ] Step 6: commit
  ```bash
  git add apps/worker/ats_worker/pipeline.py apps/worker/tests/test_feed_pipeline.py apps/web/prisma/schema.prisma docs/SPEC.md CHANGELOG.md
  git commit -m "fix(worker): record feed board-fetch failures (list_fetch_failed)"
  ```

### Task 4.5: Stop binding real network callables as pure-module defaults  [Phase 4]
**Files:** `apps/worker/ats_worker/pipeline.py` (imports, `run_fetch`/`run_feed` defaults) ; `apps/worker/ats_worker/score.py` (`import requests`, `http=` defaults) ; `apps/worker/ats_worker/run.py` (inject the real callables).
**Decision (least-churn, preserves tests):** default the injected network callables to `None`, bind the real ones only in `run.py`. Every worker test already injects `fetch_fn`/`detail_fetch_fn`/`http` explicitly (or never exercises the path). `requests` becomes unused in `score.py` → drop the import.
**Reconcile with Phase 5:** this edits `score.py` while it's still one module (Phase 4 < Phase 5); the `http=None` default + removed `requests` import carry into the Phase 5 split — so Phase 5's `score/screen.py` import list should NOT re-add `requests`.
- [ ] Step 1: no new test — the existing suite is the guard. Add one contract-lock assertion in `apps/worker/tests/test_pipeline.py`:
  ```python
  def test_run_fetch_requires_injected_fetch_fn():
      # fetch_fn defaults to None: the real adapter is wired only in run.py.
      import inspect
      assert inspect.signature(pipeline.run_fetch).parameters["fetch_fn"].default is None
  ```
- [ ] Step 2: run `cd apps/worker && rtk proxy python3 -m pytest tests/test_pipeline.py::test_run_fetch_requires_injected_fetch_fn -q`; expect FAIL (default is currently `fetch_company`).
- [ ] Step 3: implement.
  - `pipeline.py`: `from .fetch import DETAIL_SOURCES, fetch_company, fetch_one_company, filter_postings` → `from .fetch import DETAIL_SOURCES, filter_postings`; `run_fetch(... fetch_fn=fetch_company)` → `fetch_fn=None`; `run_feed(... fetch_fn=fetch_company, detail_fetch_fn=fetch_one_company)` → both `=None`.
  - `score.py`: delete `import requests`; `http=requests` (both `screen_posting` + `score_posting` defaults, if `score_posting` still exists) → `http=None`; update the module docstring's "`http` … defaults to `requests`" line.
  - `run.py`: `pipeline.run_fetch(conn, companies, cfg.title_filter, now=now)` → add `fetch_fn=fetch_company`; the `screen_fn` lambda → add `http=requests` as the first kwarg of `screen_posting(...)` (`run.py` already imports `requests` + `fetch_company`).
  *(Note: Task 3.1 may have deleted `score_posting` already — if so, only `screen_posting`'s `http=` default needs changing.)*
- [ ] Step 4: run the full worker suite `cd apps/worker && rtk proxy python3 -m pytest --cov --cov-report=term-missing -q`; expect PASS, ≥85%.
- [ ] Step 5: docs — SPEC §7.1: note all real external callables (`fetch_company`, `fetch_one_company`, `http=requests`) are bound only in `run.py`. CHANGELOG `### Changed`: "Worker pure modules no longer bind real network callables as defaults (wired only in run.py)."
- [ ] Step 6: commit
  ```bash
  git add apps/worker/ats_worker/pipeline.py apps/worker/ats_worker/score.py apps/worker/ats_worker/run.py apps/worker/tests/test_pipeline.py docs/SPEC.md CHANGELOG.md
  git commit -m "refactor(worker): inject network callables in run.py, not as module defaults"
  ```

### Task 4.6: Give the web Prisma client a SQLite busy_timeout  [Phase 4]
**Files:** `apps/web/src/lib/db.ts` ; `apps/web/.env` (DATABASE_URL) ; `docker-compose.yml` (DATABASE_URL) ; `apps/web/src/test-utils/integration/setEnv.ts` ; NEW `apps/web/src/__tests__/db-pragma.int.test.ts`.
**Mechanism:** Prisma's SQLite connector exposes no `busy_timeout` URL param. The reliable minimal fix is `connection_limit=1` (one pooled connection) + fire `PRAGMA busy_timeout=5000` at client construction. Matches the worker's `busy_timeout=5000` so a worker write-lock makes web block-and-retry instead of throwing SQLITE_BUSY. For a single-user tracker `connection_limit=1` is harmless (SQLite is single-writer regardless).
- [ ] Step 1: failing integration test `apps/web/src/__tests__/db-pragma.int.test.ts`:
  ```ts
  /** The web Prisma connection must carry busy_timeout so a worker write-lock makes
   *  web block-and-retry (up to 5s) instead of throwing SQLITE_BUSY. */
  import { prisma } from '@/test-utils/db'

  afterAll(() => prisma.$disconnect())

  test('Prisma connection has busy_timeout >= 5000ms', async () => {
      const rows = await prisma.$queryRawUnsafe<Array<{ timeout: number | bigint }>>(
          'PRAGMA busy_timeout'
      )
      expect(Number(rows[0].timeout)).toBeGreaterThanOrEqual(5000)
  })
  ```
- [ ] Step 2: run `cd apps/web && npx jest --config jest.integration.config.ts db-pragma`; **observe the default**. Expect FAIL (Prisma's default SQLite busy_timeout is below 5000). Record the observed value. *If it already reports ≥5000, de-scope (Ponytail): keep only this test as a regression lock, skip the code/URL edits, and note in PROGRESS that Prisma already sets a sufficient busy_timeout.*
- [ ] Step 3: implement (assuming Step 2 failed).
  - `db.ts` — wrap client construction:
  ```ts
  function createPrisma() {
      const client = new PrismaClient()
      // SQLite co-writing: the Python worker briefly holds write locks (busy_timeout=5000).
      // Without this a colliding web write throws SQLITE_BUSY; set busy_timeout so it
      // blocks-and-retries for 5s. Requires connection_limit=1 in DATABASE_URL (single
      // pooled connection) so the pragma covers every query. Fire-and-forget: first op.
      void client.$queryRawUnsafe('PRAGMA busy_timeout = 5000').catch(() => {})
      return client
  }

  export const prisma = globalForPrisma.prisma ?? createPrisma()
  ```
  - `apps/web/.env`: `DATABASE_URL="file:./applications.db"` → `...applications.db?connection_limit=1"`
  - `docker-compose.yml`: `DATABASE_URL: "file:/data/applications.db"` → `...applications.db?connection_limit=1"`
  - `setEnv.ts` last line: `process.env.DATABASE_URL = url` → `process.env.DATABASE_URL = url + '?connection_limit=1'` (keeps the pragma on the single test connection; the `applications.db` guard still runs on raw `url`).
- [ ] Step 4: run `cd apps/web && npx jest --config jest.integration.config.ts db-pragma` (PASS, 5000). Then `cd apps/web && npm run test:integration` (confirm `connection_limit=1` broke nothing).
- [ ] Step 5: docs — SPEC §6 + §7.2: note the web Prisma client sets busy_timeout=5000 with connection_limit=1, mirroring the worker. CHANGELOG `### Fixed`: "Web Prisma client sets SQLite busy_timeout=5000 (connection_limit=1) so worker write-locks retry instead of throwing SQLITE_BUSY."
- [ ] Step 6: commit
  ```bash
  git add apps/web/src/lib/db.ts apps/web/.env docker-compose.yml apps/web/src/test-utils/integration/setEnv.ts apps/web/src/__tests__/db-pragma.int.test.ts docs/SPEC.md CHANGELOG.md
  git commit -m "fix(web): set SQLite busy_timeout on the Prisma client"
  ```

### Task 4.7: Wrap deleteHistoryItem and importApplicationsCSV in transactions  [Phase 4]
**Files:** `apps/web/src/lib/actions.ts` (`deleteHistoryItem`, `importApplicationsCSV`); Test `apps/web/src/__tests__/actions.int.test.ts`.
**Note (behavior change):** wrapping CSV import in one transaction makes it **all-or-nothing** (a mid-import DB error rolls back the whole file; per-row validation `continue`s unaffected) — the standard bulk-import expectation. A generous `timeout` avoids the 5s interactive-transaction default tripping on larger files.
- [ ] Step 1: add integration tests to `actions.int.test.ts`:
  ```ts
  test('deleteHistoryItem atomically deletes and recomputes status', async () => {
      const app = await prisma.applications.create({ data: makeApplication({ status: 'Offer' }) })
      await prisma.status_history.create({ data: makeStatusHistory({ application_id: app.id, status: 'Phone Screen', timestamp: '2026-01-01' }) })
      const h2 = await prisma.status_history.create({ data: makeStatusHistory({ application_id: app.id, status: 'Offer', timestamp: '2026-02-01' }) })
      const res = await deleteHistoryItem(h2.id)
      expect(res.success).toBe(true)
      const after = await prisma.applications.findUnique({ where: { id: app.id } })
      expect(after!.status).toBe('Phone Screen') // recomputed from remaining latest
  })

  test('importApplicationsCSV is atomic and dedupes on (company,title)', async () => {
      await prisma.applications.create({ data: makeApplication({ company_name: 'Acme', job_title: 'Eng' }) })
      const csv = 'company_name,job_title,date_applied\nAcme,Eng,2026-01-01\nBeta,DS,2026-01-02\n'
      const res = await importApplicationsCSV(csv)
      expect(res.success).toBe(true)
      expect(res).toMatchObject({ added: 1, skipped: 1 })
      expect(await prisma.applications.count()).toBe(2)
  })
  ```
  (Use the real `makeApplication`/`makeStatusHistory` factory names from `test-utils/factories.ts`.)
- [ ] Step 2: run `cd apps/web && npx jest --config jest.integration.config.ts actions.int -t "atomic"`; these primarily lock behavior before the refactor (deleteHistoryItem may already pass — its logic is correct, just non-atomic).
- [ ] Step 3: implement.
  - `deleteHistoryItem`: keep the initial `findUnique` + not-found return, then wrap the delete/recompute/update trio:
  ```ts
          await prisma.$transaction(async (tx) => {
              await tx.status_history.delete({ where: { id } })
              const latestHistory = await tx.status_history.findFirst({
                  where: { application_id: item.application_id },
                  orderBy: { timestamp: 'desc' },
              })
              const newStatus = latestHistory ? latestHistory.status : 'Applied'
              await tx.applications.update({
                  where: { id: item.application_id },
                  data: { status: newStatus },
              })
          })
          return { success: true }
  ```
  - `importApplicationsCSV`: wrap the counting loop in one transaction, switching `prisma.` → `tx.`:
  ```ts
          const result = await prisma.$transaction(async (tx) => {
              let added = 0
              let skipped = 0
              const errors: string[] = []
              for (let i = 0; i < dataRows.length; i++) {
                  // ... unchanged row parsing / validation (continue on missing field) ...
                  const existing = await tx.applications.findFirst({ where: { company_name, job_title } })
                  if (existing) { skipped++; continue }
                  // ... status/category normalization unchanged ...
                  await tx.applications.create({ data: { /* unchanged */ } })
                  added++
              }
              return { added, skipped, errors }
          }, { timeout: 60_000 })
          return { success: true, ...result }
  ```
- [ ] Step 4: run `cd apps/web && npx jest --config jest.integration.config.ts actions.int`; expect PASS.
- [ ] Step 5: docs — SPEC §9: note `deleteHistoryItem` and `importApplicationsCSV` are transactional. CHANGELOG `### Fixed`: "deleteHistoryItem and CSV import run in transactions."
- [ ] Step 6: commit
  ```bash
  git add apps/web/src/lib/actions.ts apps/web/src/__tests__/actions.int.test.ts docs/SPEC.md CHANGELOG.md
  git commit -m "fix(web): wrap deleteHistoryItem + CSV import in transactions"
  ```

### Task 4.8: Close addApplication's TOCTOU; defer the hard @@unique  [Phase 4]
**Files:** `apps/web/src/lib/actions.ts` (`addApplication`). Related dedupe sites: `markJobApplied` (already transactional), `importApplicationsCSV` (transactional after Task 4.7). Schema: `apps/web/prisma/schema.prisma`.
**Decision + existing-data risk (be explicit):** Do **not** add `@@unique([company_name, job_title])` in this phase — the real `applications` table may already contain duplicate (company, title) pairs (re-applications), so `prisma db push` can't build the unique index and would error / force `--accept-data-loss`. A hard unique needs a deliberate backed-up dedupe migration — out of scope for "small/safe." The minimal non-destructive fix for the actual defect (non-transactional findFirst→create TOCTOU) is to make `addApplication` transactional, matching `markJobApplied`.
- [ ] Step 1: add integration test to `actions.int.test.ts`:
  ```ts
  test('addApplication rejects a duplicate (company,title) atomically', async () => {
      const first = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-01-01' })
      expect(first.success).toBe(true)
      const dup = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-02-01' })
      expect(dup.success).toBe(false)
      expect(dup.error).toContain('already exists')
      expect(await prisma.applications.count()).toBe(1)
  })
  ```
- [ ] Step 2: run `cd apps/web && npx jest --config jest.integration.config.ts actions.int -t "addApplication rejects a duplicate"`; expect PASS on current code (single-threaded) — this is the behavior lock; the change closes the concurrent TOCTOU window (verified by structure, `$transaction`, not a race test).
- [ ] Step 3: implement. Replace the findFirst→create block with a transaction mirroring `markJobApplied` (throw-to-rollback; the existing outer `catch` returns `{success:false, error: error.message}`):
  ```ts
          const newApp = await prisma.$transaction(async (tx) => {
              const existing = await tx.applications.findFirst({
                  where: { company_name: data.company_name, job_title: data.job_title },
              })
              if (existing) {
                  throw new Error(
                      `Application for ${data.company_name} - ${data.job_title} already exists`
                  )
              }
              return tx.applications.create({
                  data: {
                      company_name: data.company_name,
                      job_title: data.job_title,
                      date_applied: data.date_applied,
                      category: data.category || 'Others',
                      status: data.status || 'Applied',
                      application_url: data.application_url || '',
                      notes: data.notes || '',
                      last_updated: new Date().toISOString(),
                  },
              })
          })
          return { success: true, data: newApp }
  ```
  *(If Task 2.8's status/category gating landed first, keep its validated `status`/`category` locals here instead of the `|| 'Applied'`/`|| 'Others'` fallbacks.)*
- [ ] Step 4: run `cd apps/web && npx jest --config jest.integration.config.ts actions.int`; expect PASS.
- [ ] Step 5: docs — PROGRESS: add a deferred item — "`applications` has no DB `@@unique(company_name, job_title)`; three paths dedupe in app code (now all transactional). Adding the hard constraint requires a backup + dedupe migration (existing rows may already violate it) — deferred as a deliberate schema change." SPEC §9: note all three dedupe paths are transactional. CHANGELOG `### Fixed`: "addApplication runs in a transaction (closes create-dedupe TOCTOU)."
- [ ] Step 6: commit
  ```bash
  git add apps/web/src/lib/actions.ts apps/web/src/__tests__/actions.int.test.ts docs/PROGRESS.md docs/SPEC.md CHANGELOG.md
  git commit -m "fix(web): make addApplication transactional (close dedupe TOCTOU)"
  ```

### Task 4.9: Misc low-arch one-liners (UID/GID, seed-DB path, cron scope, removeAllInView)  [Phase 4]
**Files:** `apps/web/Dockerfile` (UID/GID ARG), `.claude/skills/onboard-board/scripts/add_watched.py` (DEFAULT_DB), `.github/workflows/ci.yml` (cron scope), `apps/web/src/lib/actions.ts` (`removeAllInView` where). Each is a 1-line change; verified by the existing suites + a config sanity check. *(This task closes the remaining low-value arch findings not owned by 4.1–4.8. `requirements-dev.txt` base-pin duplication is accepted as-is — no include mechanism — see cross-phase notes.)*
- [ ] Step 1: read each site to get the exact current line:
  ```bash
  grep -n "ARG UID\|ARG GID" apps/web/Dockerfile
  grep -n "DEFAULT_DB" .claude/skills/onboard-board/scripts/add_watched.py
  grep -n "schedule:" .github/workflows/ci.yml
  grep -n "removeAllInView" apps/web/src/lib/actions.ts
  ```
- [ ] Step 2: implement (each a 1-liner):
  - **UID/GID mismatch:** in `apps/web/Dockerfile` change the `ARG UID=1001`/`ARG GID=1001` defaults to `1000`/`1000` (match compose's `${UID:-1000}`/`${GID:-1000}` and the current host user). Add a comment: `# match docker-compose default; host user is 1000`.
  - **add_watched DEFAULT_DB:** point it at the real shared DB `db/applications.db` (repo-root-relative) instead of the gitignored `apps/web/prisma/applications.db` symlink, so the default works without a local symlink.
  - **removeAllInView (`actions.ts`):** align the rebuilt bucket `where` with `getJobPostings`' low-context exclusion so it matches "the view" for any bucket (defensive — latent today because the UI only shows the button on Discarded). Apply the same `id NOT IN (lowIds)` exclusion `getJobPostings` uses.
  - **nightly cron (`ci.yml`):** *optional* — if the `schedule` cron is meant only for the gated e2e job, add an `if: github.event_name != 'schedule'` guard to the `test`/`worker` jobs (or accept the extra runs — low value; leave a note either way).
- [ ] Step 3: verify — `cd apps/web && npx jest src/__tests__/unresolved.int.test.ts && make test-web` (removeAllInView path); `docker compose config >/dev/null` (compose still parses); `git status --short`.
- [ ] Step 4: docs — remove the four bullets from `docs/PROGRESS.md` (UID/GID mismatch, add_watched DEFAULT_DB, nightly cron, removeAllInView latent) and mark `requirements-dev.txt` dup as accepted; CHANGELOG `### Changed`: "Misc low-arch cleanups: align web Dockerfile UID/GID to the compose default, point add_watched DEFAULT_DB at db/applications.db, scope the CI cron, align removeAllInView's where with the visible bucket."
- [ ] Step 5: commit
  ```bash
  git add apps/web/Dockerfile .claude/skills/onboard-board/scripts/add_watched.py .github/workflows/ci.yml apps/web/src/lib/actions.ts docs/PROGRESS.md CHANGELOG.md
  git commit -m "chore: misc low-arch cleanups (uid/gid, seed db path, cron, removeAllInView)"
  ```

## Phase 5 — Large refactors

*Behavior-preserving splits of working files. The existing suite is the safety net — each task moves ONE concern, runs the full suite, commits green. Never big-bang. Reconcile against the cross-phase notes: `score_posting` is gone (Phase 3), `requests` is no longer imported in `score.py` (Phase 4).*

### Refactor 1 — Split `ats_worker/score.py` (1089 lines → `ats_worker/score/` package)

**Facts that shape the whole split (verified):**
- Public-API importers: `run.py` (`from .score import make_claude_scorer, make_codex_scorer, screen_posting`), `pipeline.py` (uses `score._normalize_score` + `score.ScoreError`), `tools/score_eval.py` (`score.make_codex_scorer`/`make_claude_scorer`/`ScoreError`), `tests/test_score.py` (`from ats_worker import score`).
- **Two monkeypatch constraints** (the only patched score symbols in `test_score.py`):
  1. `monkeypatch.setattr(score.subprocess, "run", …)` (13×) works after the split **only if `score/__init__.py` keeps `import subprocess`** (so `score.subprocess` resolves the same module object `backends_codex.py` uses). Keep `import subprocess` in `__init__.py` with a comment saying why.
  2. `monkeypatch.setattr(score, "_sessions_dir", …)` (1×, in `_fake_sessions`) — the sole internal-symbol patch. Moving telemetry to `usage.py` makes this ONE line become `monkeypatch.setattr(score.usage, "_sessions_dir", …)`. The only test-body edit in the whole split.
- **Re-export surface `score/__init__.py` must expose** (public + test/pipeline-accessed privates): `ScoreError`, `screen_posting`, `make_claude_scorer`, `make_codex_scorer`, `_normalize_score`, `_score_schema`, `_SCORE_SCHEMA`, `_scorer_system_sections`, `_scorer_system_blocks`, `_job_block`, `_truncate`, `resolve_location`, `_token_country`, `_is_internship`, `_needs_sponsorship`, `_degree_rank`, `_flag`, `_capture_usage`, `_sessions_dir`, `_rollout_mtime_ceiling`, `_usage_snapshot`, `_find_key`, and `subprocess`. **Drop `score_posting`** — Phase 3 removed it. (Grep the test's `score.<name>` set against `__init__` to confirm the final list.)

Worker suite command for every task below: `rtk proxy python3 -m pytest apps/worker/tests -q` (runs the `fail_under = 85` gate).

#### Task 5.1: score package skeleton — module → package, zero code change  [Phase 5]
**Files:** Rename `apps/worker/ats_worker/score.py` → `apps/worker/ats_worker/score/__init__.py` (no content edit)
- [ ] Step 1: baseline — `rtk proxy python3 -m pytest apps/worker/tests -q` (all green).
- [ ] Step 2: `cd apps/worker/ats_worker && mkdir score && git mv score.py score/__init__.py` (result is `score/__init__.py` byte-identical to the old module).
- [ ] Step 3: `rtk proxy python3 -m pytest apps/worker/tests -q` — PASS unchanged, coverage ≥85 (nothing moved yet).
- [ ] Step 4: `git add -A && git commit -m "refactor(worker): make score a package (no behavior change)"`

#### Task 5.2: extract codex quota telemetry → `score/usage.py`  [Phase 5]
**Files:** Create `apps/worker/ats_worker/score/usage.py`; Modify `score/__init__.py`; Modify `apps/worker/tests/test_score.py` (ONE line: `_fake_sessions`, `score` → `score.usage`).
**Interfaces:** `usage.py` carries `_find_key`, `_usage_snapshot`, `_sessions_dir`, `_rollout_mtime_ceiling`, `_capture_usage` (+ `_rollouts_after` if Task 2.12 added it). Imports: `import json, os`. Re-export line in `__init__.py`.
- [ ] Step 1: baseline green.
- [ ] Step 2: move the functions to `usage.py`; add `from .usage import _find_key, _usage_snapshot, _sessions_dir, _rollout_mtime_ceiling, _capture_usage`; in `tests/test_score.py` `_fake_sessions`, change `monkeypatch.setattr(score, "_sessions_dir", …)` → `monkeypatch.setattr(score.usage, "_sessions_dir", …)`.
- [ ] Step 3: `rtk proxy python3 -m pytest apps/worker/tests -q` — PASS, coverage ≥85 (watch the `test_capture_usage_*` + `test_codex..usage` cases).
- [ ] Step 4: `git add -A && git commit -m "refactor(worker): move codex quota telemetry to score/usage.py"`

#### Task 5.3: extract location gazetteer → `score/location.py`  [Phase 5]
**Files:** Create `apps/worker/ats_worker/score/location.py`; Modify `score/__init__.py`. No test edits (nothing here is patched).
**Interfaces:** carries `_REMOTE_HINTS`, `_COUNTRY_ALIASES`, `_US_STATE_NAMES`, `_US_STATE_CODES`, `_CITY_INDEX`, and `_mentions`, `_norm_loc`, `_is_us_state`, `_country_code`, `_city_index`, `_token_country`, `_country_name`, `resolve_location`. Imports: `import re`, `import pycountry` (moves wholesale off `__init__`); `geonamescache` stays lazily imported inside `_city_index`. Re-export line in `__init__.py`.
- [ ] Step 1: baseline green.
- [ ] Step 2: move constants + functions; add the re-export; delete `import pycountry` from `__init__` (verify no other `__init__` use first).
- [ ] Step 3: `rtk proxy python3 -m pytest apps/worker/tests -q` — PASS, coverage ≥85 (`test_resolve_location*`, `test_..._token_country*`).
- [ ] Step 4: `git add -A && git commit -m "refactor(worker): move location gazetteer to score/location.py"`

#### Task 5.4: extract `ScoreError` → `score/errors.py` (leaf, breaks import cycles)  [Phase 5]
**Files:** Create `apps/worker/ats_worker/score/errors.py`; Modify `score/__init__.py`
**Interfaces:** `errors.py` = `class ScoreError(RuntimeError)`, no imports. `__init__.py`: `from .errors import ScoreError`. A leaf so backends/screen can `from .errors import ScoreError` without a circular `__init__` import.
- [ ] Step 1: baseline green.
- [ ] Step 2: move `ScoreError`; add re-export; `pipeline.py`'s `score.ScoreError` unaffected.
- [ ] Step 3: `rtk proxy python3 -m pytest apps/worker/tests -q` — PASS, coverage ≥85.
- [ ] Step 4: `git add -A && git commit -m "refactor(worker): move ScoreError to score/errors.py"`

#### Task 5.5: extract prompt + schema assembly → `score/prompts.py`  [Phase 5]
**Files:** Create `apps/worker/ats_worker/score/prompts.py`; Modify `score/__init__.py`
**Interfaces:** carries `_ASSESSMENT_SCHEMA`, `_SCORE_SCHEMA`, `_score_schema`, `_scorer_system_sections`, `_scorer_system_blocks`, `_truncate`, `_job_block`, `_candidate_block`. Imports: `import json`; `from ats_worker.prompts import (…)` (absolute import of the top-level text bank — unambiguous even though this module is also named `prompts`; no `from . import prompts` exists). Re-export the test-accessed names (`_SCORE_SCHEMA`, `_score_schema`, `_scorer_system_sections`, `_scorer_system_blocks`, `_truncate`, `_job_block`, `_candidate_block`).
- [ ] Step 1: baseline green.
- [ ] Step 2: move the block; add re-export.
- [ ] Step 3: `rtk proxy python3 -m pytest apps/worker/tests -q` — PASS, coverage ≥85 (`test_*_score_schema*`, `test_*_scorer_system_blocks*`, `test_*_job_block*`).
- [ ] Step 4: `git add -A && git commit -m "refactor(worker): move prompt/schema assembly to score/prompts.py"`

#### Task 5.6: extract Claude backend → `score/backends_claude.py`  [Phase 5]
**Files:** Create `apps/worker/ats_worker/score/backends_claude.py`; Modify `score/__init__.py`
**Interfaces:** carries `make_claude_scorer(api_key, model, *, profile="", max_tokens=4096)`. Imports: `import json`; `from .errors import ScoreError`; `from .prompts import _job_block, _scorer_system_blocks, _score_schema`; `anthropic` stays lazily imported inside. Re-export `make_claude_scorer`.
- [ ] Step 1: baseline green.
- [ ] Step 2: move the factory; add re-export.
- [ ] Step 3: `rtk proxy python3 -m pytest apps/worker/tests -q` — PASS, ≥85 (`test_*claude*`).
- [ ] Step 4: `git add -A && git commit -m "refactor(worker): move Claude fit backend to score/backends_claude.py"`

#### Task 5.7: extract codex backend → `score/backends_codex.py`  [Phase 5]
**Files:** Create `apps/worker/ats_worker/score/backends_codex.py`; Modify `score/__init__.py`
**Interfaces:** carries `make_codex_scorer(model, *, profile="", reasoning_effort="low", verbosity="low", timeout=600, codex_bin="codex", usage_path=None)` incl. inner `_batch_schema`/`fit`. Imports: `import json, os, subprocess, tempfile`; `from .errors import ScoreError`; `from .prompts import _job_block, _scorer_system_sections, _score_schema`; `from .usage import _rollout_mtime_ceiling, _capture_usage`. Re-export `make_codex_scorer`. **Keep `import subprocess` in `__init__.py` too** (comment: `# re-exported so tests can monkeypatch score.subprocess.run`).
- [ ] Step 1: baseline green.
- [ ] Step 2: move the factory; add re-export; confirm `import subprocess` stays in `__init__.py`.
- [ ] Step 3: `rtk proxy python3 -m pytest apps/worker/tests -q` — PASS, ≥85 (all `test_codex_*`, incl. batch realignment + usage capture).
- [ ] Step 4: `git add -A && git commit -m "refactor(worker): move codex fit backend to score/backends_codex.py"`

#### Task 5.8: extract screen rules + normalization → `score/screen.py`; __init__ is a thin shim  [Phase 5]
**Files:** Create `apps/worker/ats_worker/score/screen.py`; Modify `score/__init__.py` (thin re-export shim + `import subprocess`)
**Interfaces:** carries everything left: `DEGREE_RANK`, `NO_SPONSOR_PHRASES`, `_INTERN_TITLE`, `_SENIORITY_VERDICTS`, `_DOMAIN_VERDICTS`; Ollama transport `_post`; `_normalize_score`, `_normalize_assessment`, `_coerce_score`, `_as_str_list`; screen rules `_screen_verdict`, `_check_degree`, `_check_authorization`, `_check_clearance`, `_is_internship`, `_norm_simple`, `_degree_rank`, `_needs_sponsorship`, `_flag`; composition `screen_posting(...)`. Imports: `import json, re` (**NOT `requests`** — Phase 4 removed it; `_post` uses the injected `http`); `from .errors import ScoreError`; `from .location import resolve_location`; `from .prompts import _job_block, _candidate_block`. Final `__init__.py` = the `from .X import …` lines + `import subprocess` + a module docstring (~40 lines).
- [ ] Step 1: baseline green.
- [ ] Step 2: move the residual; reduce `__init__.py` to the shim. Grep the test's `score.<name>` set against `__init__` to confirm the full re-export surface (minus `score_posting`, gone in Phase 3).
- [ ] Step 3: `rtk proxy python3 -m pytest apps/worker/tests -q` — PASS, ≥85 (whole `test_score.py` + `test_pipeline.py` `score._normalize_score`/`ScoreError` paths).
- [ ] Step 4: `git add -A && git commit -m "refactor(worker): move screen rules + normalization to score/screen.py; __init__ is a thin shim"`

### Refactor 2 — Split `apps/web/src/components/Dashboard.tsx` (720 lines)

**Facts:** `Dashboard.test.tsx` mocks all server actions + charts and asserts tab buttons, the KPI `Applied` tile, and per-tab placeholders. The safe behavior-preserving split is **presentational extraction**: move each tab's JSX into its own component receiving exactly the state slice + handlers it renders; keep ALL state, all `handle*`, `refresh*`, the mount `useEffect`, the `KPIGrid` header, the tab-button bar, and the three always-mounted modals in the shell. Render tree stays identical → tests pass unchanged. (Moving state INTO tabs adds behavior risk via cross-tab `refreshData`; skip it, per Ponytail.)

Web suite command for every task below: `cd apps/web && make test-web`.

#### Task 5.9: extract `UnresolvedTab.tsx` (smallest — establishes the pattern)  [Phase 5]
**Files:** Create `apps/web/src/components/UnresolvedTab.tsx`; Modify `Dashboard.tsx` (`activeTab === 'unresolved'` branch → `<UnresolvedTab data={unresolved} />`)
**Interfaces:** `interface UnresolvedTabProps { data: any[] }` — renders the Card + `<UnresolvedFeedsTable data={data} />`.
- [ ] Step 1: baseline `cd apps/web && make test-web` green.
- [ ] Step 2: move the `Card`/`CardHeader`/`UnresolvedFeedsTable` JSX into `UnresolvedTab`; import `Card*` + `UnresolvedFeedsTable` there; Dashboard's branch becomes `<UnresolvedTab data={unresolved} />`.
- [ ] Step 3: `cd apps/web && make test-web` — PASS unchanged.
- [ ] Step 4: `git add -A && git commit -m "refactor(web): extract UnresolvedTab from Dashboard"`

#### Task 5.10: extract `WatchlistTab.tsx`  [Phase 5]
**Files:** Create `apps/web/src/components/WatchlistTab.tsx`; Modify `Dashboard.tsx`
**Interfaces:**
  ```ts
  interface WatchlistTabProps {
    promotions: any[]
    watchlist: any[]
    onApprove: (c: { source: string; slug: string; name: string }) => void
    onDismiss: (source: string, slug: string) => void
    onAdd: (c: { source: string; slug: string; name: string; recipe?: string }) => void
    onRemove: (id: number) => void
  }
  ```
  Wire `<WatchlistTab promotions={promotions} watchlist={watchlist} onApprove={handleApproveSuggestion} onDismiss={handleDismissSuggestion} onAdd={handleAddWatched} onRemove={handleRemoveWatched} />` (renders the Suggested-companies `Card`+`PromotionSuggestions` and the Watchlist `Card`+`WatchlistTable`).
- [ ] Step 1: baseline green.
- [ ] Step 2: move JSX + the `Card*`/`PromotionSuggestions`/`WatchlistTable` imports; handlers stay in Dashboard, passed as props.
- [ ] Step 3: `cd apps/web && make test-web` — PASS (esp. `switching to the Watchlist tab`).
- [ ] Step 4: `git add -A && git commit -m "refactor(web): extract WatchlistTab from Dashboard"`

#### Task 5.11: extract `DiscoveredJobsTab.tsx`  [Phase 5]
**Files:** Create `apps/web/src/components/DiscoveredJobsTab.tsx`; Modify `Dashboard.tsx`. Keep `JobDetailModal`/`ApplyCategoryDialog` + `selectedJob`/`applyJob` state in the shell (always-mounted, touch `refreshData`).
**Interfaces:** (mirror the props Dashboard already threads into `DiscoveredJobsTable`, plus `CodexUsageBar`)
  ```ts
  import type { JobBucket, DisqualifyCause, JobSort } from '@/lib/actions'
  import type { JobPosting } from './DiscoveredJobsTable'
  interface DiscoveredJobsTabProps {
    data: JobPosting[]; total: number; page: number; size: number
    onPageChange: (page: number) => void
    onFilterChange: (f: { bucket: JobBucket; search: string; minScore?: number; cause?: DisqualifyCause; sort: JobSort }) => void
    onMarkApplied: (id: number) => void; onDiscard: (id: number) => void; onReopen: (id: number) => void
    onViewJD: (id: number) => void
    onBulkRemove: (ids: number[]) => void; onBulkReopen: (ids: number[]) => void
    onRemoveAllInView: (f: { bucket: JobBucket; search: string; minScore?: number; cause?: DisqualifyCause }) => void
  }
  ```
  Renders `<Card><CardHeader>Discovered Jobs</CardHeader><CardContent><CodexUsageBar /><DiscoveredJobsTable {...} /></CardContent></Card>`.
- [ ] Step 1: baseline green.
- [ ] Step 2: move the discovered `Card` JSX + `CodexUsageBar`/`DiscoveredJobsTable` imports; Dashboard passes the props from its existing state/handlers; the two modals stay at Dashboard bottom.
- [ ] Step 3: `cd apps/web && make test-web` — PASS (esp. `switching to the Discovered Jobs tab` + `/job titles/`).
- [ ] Step 4: `git add -A && git commit -m "refactor(web): extract DiscoveredJobsTab from Dashboard"`

#### Task 5.12: extract `ApplicationsTab.tsx` (default tab; Dashboard becomes a thin shell)  [Phase 5]
**Files:** Create `apps/web/src/components/ApplicationsTab.tsx`; Modify `Dashboard.tsx`. `KPIGrid` (header) and `StatusHistoryModal` (bottom) stay in the shell.
**Interfaces:**
  ```ts
  interface ApplicationsTabProps {
    apps: any[]; total: number; page: number
    timeline: any[]; categories: any[]; statusFlow: any[]
    onAddApplication: (data: any) => void
    onPageChange: (page: number) => void
    onFilterChange: (filters: any) => void
    onStatusChange: (id: number, newStatus: string) => void
    onDelete: (id: number) => void
    onHistory: (id: number) => void
  }
  ```
  Renders the Add-form + `ApplicationTable` grid and the four chart Cards. `size={10}` moves into the tab.
- [ ] Step 1: baseline green.
- [ ] Step 2: move JSX + imports (`AddApplicationForm`, `ApplicationTable`, `TimelineHeatmap`, `CategoryDonut`, `StatusFunnel`, `SankeyChart`, `Card*`); Dashboard's default branch becomes `<ApplicationsTab apps={apps} total={total} page={page} timeline={timeline} categories={categories} statusFlow={statusFlow} onAddApplication={handleAddApplication} onPageChange={handlePageChange} onFilterChange={handleFilterChange} onStatusChange={handleStatusChange} onDelete={handleDeleteApplication} onHistory={handleViewHistory} />`. Prune now-unused imports from `Dashboard.tsx`.
- [ ] Step 3: `cd apps/web && make test-web` — PASS (esp. `renders both tabs and the KPI grid`).
- [ ] Step 4: `git add -A && git commit -m "refactor(web): extract ApplicationsTab; Dashboard is a thin tab shell"`

#### Task 5.13: dedup verdict/score-detail parsing → `lib/score-detail.ts`  [Phase 5]
**Files:** Create `apps/web/src/lib/score-detail.ts`; Modify `JobDetailModal.tsx` and `DiscoveredJobsTable.tsx`
**Interfaces:** the genuinely-duplicated surface (not a forced unification of the two different view-models):
  ```ts
  export function verdictClass(v: string): string {   // byte-identical in both files today
    if (v === 'match') return 'bg-emerald-500/15 text-emerald-700 border-transparent'
    if (v === 'mismatch') return 'bg-red-500/15 text-red-700 border-transparent'
    return 'bg-amber-500/15 text-amber-700 border-transparent'
  }
  export function verdictLabel(v: string): string {   // from DiscoveredJobsTable
    if (v === 'too_junior') return 'Too junior'
    if (v === 'too_senior') return 'Too senior'
    return v ? v.charAt(0).toUpperCase() + v.slice(1) : v
  }
  export function safeParseDetail(raw?: string | null): any | null {
    if (!raw) return null
    try { const p = JSON.parse(raw); return p && typeof p === 'object' ? p : null }
    catch { return null }
  }
  ```
  Both components keep their own `parseScoreDetail`/`parseDetail` view-model shaping (they differ), but start with `const p = safeParseDetail(raw); if (!p) return null` and import `verdictClass` (+ `verdictLabel` in the table) — deleting the duplicated `verdictClass` and inline `try/JSON.parse/catch`.
- [ ] Step 1: baseline `cd apps/web && make test-web` green (covers both component tests).
- [ ] Step 2: add `lib/score-detail.ts`; replace the local `verdictClass` (+ `verdictLabel` in the table) with imports; route the JSON parse through `safeParseDetail`. No output shape changes.
- [ ] Step 3: `cd apps/web && make test-web` — PASS unchanged.
- [ ] Step 4: `git add -A && git commit -m "refactor(web): share verdictClass + score_detail parsing via lib/score-detail.ts"`

### Refactor 3 — Dedup the adapter list→detail loops

**Facts:** `workday.fetch`, `smartrecruiters.fetch`, `phenom.fetch` share a paged-list→per-item-detail skeleton but differ in list verb (Workday POST-json vs SR/Phenom GET-params), total key (`total`/`totalFound`/`count`), and detail-failure policy (Workday+SR **skip** the row; Phenom **keeps** it with an empty description). All advance offset by items-on-page. Tests drive the public `fetch`/`fetch_one`/`parse_*` with injected `session=`; behavior-preservation = recorded request URLs/params + returned postings stay identical. The differences map cleanly onto two per-adapter callables.

**Helper (add beside `_recipe.py`):**
  ```python
  # apps/worker/ats_worker/fetch/_paged.py
  import requests
  def paged_details(session, *, fetch_page, build_row) -> list[dict]:
      """Drive a paged list endpoint -> per-item detail into canonical postings.
      Owns `http = session or requests`, the page loop, the empty-id skip, len-based
      offset advance, and termination on an empty page OR a reached honest total.
      `fetch_page(http, offset) -> (items, total|None)`; `build_row(http, item) ->
      posting dict | None` (None or empty external_id is skipped)."""
      http = session or requests
      out: list[dict] = []
      offset = 0
      while True:
          items, total = fetch_page(http, offset)
          for item in items:
              row = build_row(http, item)
              if row and row["external_id"]:
                  out.append(row)
          offset += len(items)
          if not items or (isinstance(total, int) and offset >= total):
              break
      return out
  ```

#### Task 5.14: add `_paged.py` helper + migrate `workday.fetch` (first consumer)  [Phase 5]
**Files:** Create `apps/worker/ats_worker/fetch/_paged.py`; Modify `apps/worker/ats_worker/fetch/workday.py` (`fetch`)
**Interfaces:** `paged_details(session, *, fetch_page, build_row)` as above. Workday `fetch` becomes:
  ```python
  from ats_worker.fetch._paged import paged_details
  def fetch(slug, company_name, session=None, timeout=20):
      tenant, dc, site = _parts(slug)
      cxs = _CXS.format(tenant=tenant, dc=dc, site=site)
      def _page(http, offset):
          resp = http.post(cxs + "/jobs",
                           json={"appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": ""},
                           headers=_JSON, timeout=timeout)
          resp.raise_for_status()
          data = resp.json()
          return parse_listing(data), data.get("total")
      def _row(http, stub):
          try:
              detail = http.get(cxs + stub["externalPath"], headers=_JSON, timeout=timeout)
              detail.raise_for_status()
              return parse_job(detail.json(), company_name)
          except Exception:
              return None            # skip one bad posting
      return paged_details(session, fetch_page=_page, build_row=_row)
  ```
  (Ship the helper with its first real caller so no commit carries dead code. Confirm `_CXS`/`_JSON`/`PAGE`/`parse_listing`/`parse_job` names against source.)
- [ ] Step 1: baseline green.
- [ ] Step 2: add `_paged.py`; rewrite `workday.fetch`; `_parts`/`parse_listing`/`parse_job`/`fetch_one` untouched.
- [ ] Step 3: `rtk proxy python3 -m pytest apps/worker/tests -q` — PASS, ≥85 (esp. `test_workday_fetch_pages_and_enriches_via_detail`, `..._isolates_a_bad_detail`, `..._skips_*`, `..._terminates_*`).
- [ ] Step 4: `git add -A && git commit -m "refactor(worker): add fetch/_paged helper; migrate workday adapter"`

#### Task 5.15: migrate `smartrecruiters.fetch` to `paged_details`  [Phase 5]
**Files:** Modify `apps/worker/ats_worker/fetch/smartrecruiters.py` (`fetch`)
**Interfaces:**
  ```python
  from ats_worker.fetch._paged import paged_details
  def fetch(slug, company_name, session=None, timeout=20):
      base = API.format(slug=slug)
      def _page(http, offset):
          resp = http.get(base, params={"limit": PAGE, "offset": offset}, timeout=timeout)
          resp.raise_for_status()
          data = resp.json()
          return parse_listing(data), data.get("totalFound")
      def _row(http, stub):
          pid = stub.get("id")
          if not pid:
              return None                        # id-less stub: no detail GET
          try:
              detail = http.get(f"{base}/{pid}", timeout=timeout)
              detail.raise_for_status()
              return parse_job(detail.json(), slug, company_name)
          except Exception:
              return None
      return paged_details(session, fetch_page=_page, build_row=_row)
  ```
  (`+= len(items)` in the helper is behavior-identical to the old `+= PAGE` for every SR fixture — verified against the offset assertions.)
- [ ] Step 1: baseline green.
- [ ] Step 2: rewrite `fetch`; `parse_listing`/`_location`/`_description`/`parse_job`/`fetch_one` untouched.
- [ ] Step 3: `rtk proxy python3 -m pytest apps/worker/tests -q` — PASS, ≥85 (all `test_smartrecruiters.py` fetch cases).
- [ ] Step 4: `git add -A && git commit -m "refactor(worker): migrate smartrecruiters adapter to fetch/_paged"`

#### Task 5.16: migrate `phenom.fetch` to `paged_details`  [Phase 5]
**Files:** Modify `apps/worker/ats_worker/fetch/phenom.py` (`fetch`)
**Interfaces:**
  ```python
  from ats_worker.fetch._paged import paged_details
  def fetch(slug, company_name, session=None, timeout=20):
      host, domain = _parts(slug)
      search_url = f"https://{host}/api/pcsx/search"
      detail_url = f"https://{host}/api/pcsx/position_details"
      def _page(http, start):
          resp = http.get(search_url, params={"domain": domain, "start": start}, timeout=timeout)
          resp.raise_for_status()
          data = _require_ok(resp.json())
          return data.get("positions") or [], data.get("count")
      def _row(http, pos):
          pid = str(pos.get("id") or "")
          if not pid:
              return None
          description = ""
          try:
              detail = http.get(detail_url, params={"domain": domain, "position_id": pid}, timeout=timeout)
              detail.raise_for_status()
              description = _require_ok(detail.json()).get("jobDescription") or ""
          except Exception:
              pass                                # KEEP the posting with empty desc (phenom policy)
          return parse_position(pos, company_name, description)
      return paged_details(session, fetch_page=_page, build_row=_row)
  ```
  (Phenom's keep-on-detail-error is preserved inside `_row`; `_require_ok`/`parse_position`/`_parts` untouched.)
- [ ] Step 1: baseline green.
- [ ] Step 2: rewrite `fetch`.
- [ ] Step 3: `rtk proxy python3 -m pytest apps/worker/tests -q` — PASS, ≥85 (all `test_phenom.py` `fetch` cases, incl. bad-tenant `_require_ok`, keep-on-bad-detail, count-based termination).
- [ ] Step 4: `git add -A && git commit -m "refactor(worker): migrate phenom adapter to fetch/_paged"`

---

## Self-review record (writing-plans checklist)

- **Spec coverage:** every finding in `docs/PROGRESS.md` (Defects, Unverified, both Enhancement sub-sections) maps to a task. The five low-value arch items not dispatched to a phase agent are covered by **Task 4.9**. Items with **no task** are the four documented-accepted ones (autoheal socket, `requirements-dev.txt` dup, DNS-rebinding residual, phenom/workday IP-host slug) and the three pre-existing standing items (JD prompt-injection, stale-mount drill, no-migration-path) — all listed under *Accepted / no task* above.
- **Placeholder scan:** code steps carry real, source-verified code. A few refactor/large-function tasks use `# ... unchanged ...` markers to mark *existing* surrounding code the executor keeps in place (CSV import loop body, codex `fit()` try-block) — these are bounded "keep what's there" markers, not unwritten logic. Every *new* line is spelled out.
- **Type consistency:** shared symbols are consistent across tasks — `is_safe_public_url` (Tasks 2.9/2.10), `safeHref` (2.4), `paged_details` (5.14–5.16), `score.usage._sessions_dir` (5.2/2.12), the `score/__init__.py` re-export surface (5.1–5.8). Cross-phase reconciliations (score_posting gone before 5.8; `requests` not re-imported in 5.8; `addApplication` transaction vs status/category gating) are called out inline and in the cross-phase notes.
- **Line-number caveat:** all cited line numbers are pre-remediation; trust the quoted before-code and grep, since earlier commits shift them.

## Definition of done

The plan is complete when `docs/PROGRESS.md`'s **Defects** and **Unverified** buckets are empty and both audit sub-sections under **Enhancements** (Dead-code, Architecture) are cleared — except the explicitly-deferred `applications @@unique` item and the documented-accepted residuals, which remain by design. At that point `docs/PROGRESS.md` reads clean, `CHANGELOG.md`'s `[Unreleased]` captures the whole remediation, and CI is green on `dev`.
