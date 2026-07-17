import { NextResponse } from 'next/server'
import { promises as fs } from 'node:fs'
import path from 'node:path'

// Serves the codex quota snapshot the worker writes after each scoring call
// (used_percent / resets_at per limit — codex's own /status accounting). The
// DiscoveredJobsTable header renders it as a usage bar. See docs/SPEC.md §7.2.
export const dynamic = 'force-dynamic' // never cache; read the file every request

// The snapshot lives next to the shared SQLite file (both in the db/ bind mount,
// /data in the container). Derived from DATABASE_URL so it tracks the DB location;
// CODEX_USAGE_FILE overrides for local dev where the worker writes elsewhere.
function usageFilePath(): string {
    if (process.env.CODEX_USAGE_FILE) return process.env.CODEX_USAGE_FILE
    const dbFile = (process.env.DATABASE_URL ?? '').replace(/^file:/, '')
    return path.join(dbFile ? path.dirname(dbFile) : '/data', 'codex_usage.json')
}

export async function GET() {
    const file = usageFilePath()
    try {
        const [raw, stat] = await Promise.all([fs.readFile(file, 'utf-8'), fs.stat(file)])
        const snap = JSON.parse(raw)
        // File mtime is the "as of" time — no captured_at field to write worker-side.
        return NextResponse.json({ ...snap, as_of: stat.mtime.toISOString() })
    } catch {
        // Missing or unparseable → empty state, not an error: the worker may not
        // have run a scoring pass yet. The bar shows "no usage recorded yet".
        return NextResponse.json({ plan_type: null, limits: [], as_of: null })
    }
}
