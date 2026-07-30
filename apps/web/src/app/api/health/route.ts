import { NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

// Liveness + DB-reachability probe used by the Docker healthcheck. It must
// actually open the SQLite file (not just confirm the HTTP server is up),
// because the failure we guard against is a stale bind mount on WSL2 where the
// HTTP server runs fine but Prisma can't open /data/applications.db
// (SQLITE_CANTOPEN). Returns 200 when the DB is reachable, 503 otherwise — the
// autoheal sidecar restarts the container on repeated 503s. See docs/SPEC.md §6.
export const dynamic = 'force-dynamic' // never cache; every probe hits the DB

export async function GET() {
    try {
        // Reads sqlite_master, NOT `SELECT 1`. `SELECT 1` is a constant expression SQLite
        // answers from the query planner without touching a page, so it returns 200 with
        // the database file gone — the exact failure this probe exists to catch. Reading a
        // table forces a real page read and, under WAL, the -wal/-shm sidecars too.
        // A row rather than `count(*)`: the SQLite connector returns counts as BigInt,
        // which throws on JSON.stringify. Nothing serializes this result today, and this
        // way nothing can start to.
        await prisma.$queryRaw`SELECT name FROM sqlite_master LIMIT 1`
        return NextResponse.json({ status: 'ok' }, { status: 200 })
    } catch (err) {
        // Detail stays server-side only; the 503 body must not leak internals (paths,
        // driver strings). The autoheal sidecar keys on the status code, not the body.
        console.error('[health] DB probe failed:', err)
        return NextResponse.json({ status: 'error', error: 'database unreachable' }, { status: 503 })
    }
}
