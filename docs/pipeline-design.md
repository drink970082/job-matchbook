# Pipeline design (historical)

This was the original design write-up for adding the semi-automated job-hunt
pipeline to personal-ats. The system has since shipped and evolved (e.g. Workday +
Pinpoint adapters and hard-constraint screening were added, paths moved to
`apps/web` / `apps/worker`), so this doc is no longer maintained.

For the **current** architecture and the rationale behind each design decision, see:

- ➡️ **[`SPEC.md` §6 — Architecture](./SPEC.md#6-architecture)**
- ➡️ **[`SPEC.md` §10 — Design decisions and rationale](./SPEC.md#10-design-decisions-and-rationale)**

The original write-up (Chinese, with the initial step-by-step plan) is preserved in
git history — `git log --follow docs/pipeline-design.md`.
