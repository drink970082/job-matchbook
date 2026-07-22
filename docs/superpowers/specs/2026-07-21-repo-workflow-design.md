# Repo & release workflow overhaul — design

**Date:** 2026-07-21
**Status:** executed 2026-07-22 (Phase 3 amended mid-flight — see below)
**Closes:** PROGRESS "Adjust dev/release workflow" + "Rename the GitHub repo"

## Problem

Two complaints, one root cause — the repo's *outside* doesn't match the work inside it.

1. **Workflow.** Every commit is pushed straight to `dev`. `master` is the GitHub
   default branch and sits 274 commits behind at a v0.2.0-era tip. No pull requests
   have ever been opened. There is no release history: one stale `v0.2.0` tag, zero
   GitHub Releases, and a `CHANGELOG.md` whose `[1.0.0] — 2026-07-20` section was
   never tagged.
2. **Presentation.** The repo is `drink970082/personal-ats`, private, with an empty
   description and no topics. "personal" contradicts the general-purpose pivot.

Both are metadata and process, not code. `LICENSE`, `CONTRIBUTING.md`,
`CODE_OF_CONDUCT.md`, `SECURITY.md`, issue templates, a PR template and green CI
already exist.

## Decisions

| Fork | Decision | Why |
| --- | --- | --- |
| Branch model | Single `main` + short-lived PR branches | Two long-lived branches for one person is overhead that already produced a 274-commit lag. |
| Merge strategy | Squash-merge only, auto-delete head branch | Linear, readable history; the branch name survives in the squash subject. |
| Protection | **Pragmatic**: required status checks + no force-push/delete, but direct pushes allowed | Required-PR on a solo repo taxes every typo fix for a benefit that is mostly theater. Operator's call, 2026-07-21. |
| Name | `job-matchbook` (brand **Job Matchbook**, short form **Matchbook**) | *match* = the worker (screen + fit score); *book* = the tracker (the kept record). "job" stays in the URL so the repo self-identifies in search. |
| Code identifiers | Unchanged (`ats_worker`, `apps/`, local `ats/` dir) | Renaming them is a large mechanical diff with no outside-visible payoff. |
| Visibility | Public, at the very end | Outstanding v1.0.0 step; the metadata work only pays off publicly. |

## Target state

```
main ──o──o──o──o──o──▶     tags: v1.0.0
        \    /  \    /
      feat/a      fix/b     short-lived, squash-merged, auto-deleted
```

- **Ruleset on `main`:** require status checks `Web (Next.js / Jest)` and
  `Worker (Python / pytest)`; block force-push and branch deletion; require linear
  history. No required-PR rule.
- **Repo settings:** squash-merge only (disable merge commits + rebase-merge);
  auto-delete head branches.
- **Releases:** every release is a tag on `main` plus a `gh release create` whose
  notes are the matching `CHANGELOG.md` section. SemVer, Keep-a-Changelog — both
  already in use.

## Work

### Phase 1 — identity and presentation (safe, reversible)

1. `gh repo rename job-matchbook`. GitHub redirects the old URL (until someone
   creates a new `personal-ats`), so existing clones keep working; still update
   the local remote.
2. Fill About: description + topics
   (`job-search`, `applicant-tracking-system`, `nextjs`, `prisma`, `python`, `llm`,
   `self-hosted`, `telegram-bot`).
3. README: title → **Job Matchbook**, add the one-line tagline, fix the CI badge URL.
4. Update tracked references to the old URL: `README.md` (badge ×2), `SECURITY.md`
   (advisory + issue links), `docs/SPEC.md` §1 (project name + repo URL).
   `docs/pipeline-design.md` is explicitly historical — leave it.

### Phase 2 — branch surgery (destructive; gated)

**Gate:** the concurrent stub-gate session's work must be committed and pushed to
`origin/dev` first. Deleting `dev` with unpushed work on it strands that work.

5. `git push origin dev:master` — a fast-forward (`dev..master` is 0, so `master`
   is a strict ancestor). No merge commit; all 274 commits preserved as-is.
6. Rename the branch `master` → `main` on GitHub (retargets the default branch and
   any open PRs, and installs a redirect).
7. `git push origin --delete dev`.
8. Locally: `git branch -m dev main && git branch -u origin/main`, then
   `git remote set-url origin` to the new repo name and `git fetch --prune`.
9. Apply the merge-strategy settings from **Target state**. **The ruleset must wait
   until after the visibility flip (step 15)** — GitHub rulesets are a paid feature on
   private repos and the API returns 403.

### Phase 3 — releases

**Amended 2026-07-22 (operator call).** The original plan — retro-tag `v1.0.0` at
`bf453b5`, then cut `v1.1.0` at HEAD — was dropped once it turned out the `[1.0.0]`
CHANGELOG section had kept *growing* after that commit (it now carries entries written
days later). Retro-tagging would have published release notes describing code the
tagged commit doesn't contain. Since v1.0.0 was never tagged or published, there is no
history to preserve, so:

10. Fold `[Unreleased]` into `[1.0.0]` per subsection (newest first), re-date it the
    day it ships, and open a fresh empty `[Unreleased]`.
11. Tag one **v1.0.0** at `main` HEAD and `gh release create v1.0.0` — the honest
    first public release. Version strings already read `1.0.0`, so no bump. Release
    notes are curated highlights linking to the full CHANGELOG section, which runs
    ~1,200 lines.

### Phase 4 — docs and go-public

12. `docs/DEVELOPMENT.md` §6 "Branch discipline" and the session-kickoff template
    both instruct working on `dev` and leaving `master` alone — rewrite for the
    `main` + PR-branch flow.
13. `CONTRIBUTING.md`: add the branch/PR/release conventions (it currently documents
    tests and code style only). `CLAUDE.md` mentions no branches — no change.
14. `docs/PROGRESS.md`: close "Rename the GitHub repo" and "Adjust dev/release
    workflow"; `CHANGELOG.md` gets a **Repository** section recording the rename and
    the branch collapse.
15. `make check-privacy` must pass on the final tree, then
    `gh repo edit --visibility public`, then apply the `main` ruleset (step 9).

## Verification

| Claim | Evidence |
| --- | --- |
| No history lost in the branch collapse | record `dev`'s tip sha before step 5; afterwards `git rev-list --count <that sha>..origin/main` = 0 |
| `main` is the default branch, `dev`/`master` gone | `gh repo view --json defaultBranchRef` + `git branch -r` |
| Protection is live | `gh api repos/:owner/:repo/rulesets` shows the required checks; a force-push attempt is rejected |
| Releases render | `gh release list` shows v1.0.0 |
| Nothing private went public | `make check-privacy` green immediately before the visibility flip |
| No stale URLs | `git grep personal-ats` returns only `docs/pipeline-design.md` and historical plan docs |

## Explicitly not doing

- Renaming `ats_worker`, `apps/`, or the local checkout directory.
- A required-PR rule, required reviewers, or CODEOWNERS.
- A `develop`/`release/*` branch, GitFlow, or any release-automation bot
  (release-please, semantic-release).
- Squashing or rewriting the existing 274 commits.
