import { NextResponse } from 'next/server'
import { promises as fs } from 'node:fs'
import path from 'node:path'

// Serves the fit-backend quota snapshot the worker writes after each scoring pass
// (used_percent / resets_at per window, read from the provider's own usage endpoint —
// codex's /backend-api/codex/usage or Claude Code's /api/oauth/usage). The snapshot
// records WHICH backend it describes so the bar can label itself. The Discovered
// Jobs tab renders it as a usage bar (components/DiscoveredJobsTab.tsx). See
// docs/SPEC.md §7.2.
export const dynamic = 'force-dynamic' // never cache; read the file every request

// The snapshot lives next to the shared SQLite file (both in the db/ bind mount,
// /data in the container). Derived from DATABASE_URL so it tracks the DB location;
// SCORER_USAGE_FILE overrides for local dev where the worker writes elsewhere.
function usageFilePath(): string {
    if (process.env.SCORER_USAGE_FILE) return process.env.SCORER_USAGE_FILE
    const dbFile = (process.env.DATABASE_URL ?? '').replace(/^file:/, '')
    return path.join(dbFile ? path.dirname(dbFile) : '/data', 'scorer_usage.json')
}

export async function GET() {
    const file = usageFilePath()
    try {
        const [raw, stat] = await Promise.all([fs.readFile(file, 'utf-8'), fs.stat(file)])
        const snap = JSON.parse(raw)
        // File mtime is the "as of" time. The worker also stamps its own `as_of` at
        // write time (score/usage.py), and this overrides it deliberately: the two are
        // the same instant, and mtime is the only one a pre-stamp snapshot carries.
        return NextResponse.json({ ...snap, as_of: stat.mtime.toISOString() })
    } catch {
        // Missing or unparseable → empty state, not an error: the worker may not
        // have run a scoring pass yet. The bar shows "no usage recorded yet".
        return NextResponse.json({ backend: null, plan_type: null, limits: [], as_of: null })
    }
}
