#!/usr/bin/env node
// Fail if any private file is tracked by git. .gitignore already keeps these out,
// but it only guards the happy path: `git add -f`, a loosened ignore rule, or a
// file committed before its rule existed all slip through. This asserts the real
// invariant instead — the repo ships ONLY *.example templates (see .gitignore,
// SPEC §11). Mirrors check_schema_drift.mjs: parse-only, Node-only, no deps.
// Run: node tools/check_privacy.mjs [--self-test]
import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

// ponytail: path deny-list only — no content/entropy scan for stray API keys.
// Add one if a key ever lands in source; a path list has no false positives.
const RULES = [
    // `.env` followed by end-or-a-dot: catches every suffixed variant (.env.local,
    // .env.bak, .env.production) without matching `.environment` or `setEnv.ts`.
    // ALLOW exempts *.example, which is the only one the repo ships.
    [/(^|\/)\.env($|\.)/, 'secrets file (commit .env.example instead)'],
    [/(^|\/)config\.ya?ml$/, 'per-user worker config (commit config.yaml.example)'],
    [/\.db($|-wal$|-shm$)|^db\//, 'the SQLite database'],
    [/^apps\/worker\/resume\//, 'the real resume / personal profile'],
    [/^apps\/worker\/eval\//, 'eval data (real postings + resume context)'],
    [/^resumes\//, 'tailored resume PDFs'],
    [/^apps\/worker\/quant_job_boards\.txt$/, 'board research keyed to the operator\'s watchlist'],
]
const ALLOW = /\.example$|(^|\/)README\.md$/

const offenders = (paths) => paths.flatMap((p) => {
    if (ALLOW.test(p)) return []
    const hit = RULES.find(([re]) => re.test(p))
    return hit ? [[p, hit[1]]] : []
})

if (process.argv.includes('--self-test')) {
    const flagged = new Set(offenders([
        'apps/worker/resume/resume.txt',
        'apps/worker/resume/resume.txt.example',
        'apps/worker/resume/README.md',
        'apps/worker/.env',
        'apps/worker/.env.example',
        '.env.bak-tsserve',
        'apps/worker/.env.production',
        'apps/web/src/environment.ts',
        'apps/worker/config.yaml',
        'db/applications.db-wal',
        'apps/worker/quant_job_boards.txt',
        'apps/web/src/lib/actions.ts',
    ]).map(([p]) => p))
    // The .env.<suffix> rows are the 2026-07-29 gap: the rule used to be a literal
    // `.env`, so a backup was invisible here AND unignored by .gitignore.
    const want = ['apps/worker/resume/resume.txt', 'apps/worker/.env', '.env.bak-tsserve', 'apps/worker/.env.production', 'apps/worker/config.yaml', 'db/applications.db-wal', 'apps/worker/quant_job_boards.txt']
    const wantNot = ['apps/worker/resume/resume.txt.example', 'apps/worker/resume/README.md', 'apps/worker/.env.example', 'apps/web/src/environment.ts', 'apps/web/src/lib/actions.ts']
    const bad = [...want.filter((p) => !flagged.has(p)), ...wantNot.filter((p) => flagged.has(p))]
    if (bad.length) { console.error('SELF-TEST FAILED: ' + bad.join(', ')); process.exit(1) }
    console.log('self-test ok')
    process.exit(0)
}

const tracked = execFileSync('git', ['ls-files'], { cwd: root, encoding: 'utf8' }).split('\n').filter(Boolean)
const found = offenders(tracked)
for (const [path, why] of found) console.error(`PRIVATE FILE TRACKED: ${path} — ${why}`)
if (found.length) {
    console.error('\nThese must never be committed. `git rm --cached <path>`, then confirm .gitignore covers it.')
    process.exit(1)
}
console.log(`no private files tracked (${tracked.length} files checked)`)
