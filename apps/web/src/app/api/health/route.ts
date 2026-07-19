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
        await prisma.$queryRaw`SELECT 1`
        return NextResponse.json({ status: 'ok' }, { status: 200 })
    } catch (err) {
        // Detail stays server-side only; the 503 body must not leak internals (paths,
        // driver strings). The autoheal sidecar keys on the status code, not the body.
        console.error('[health] DB probe failed:', err)
        return NextResponse.json({ status: 'error', error: 'database unreachable' }, { status: 503 })
    }
}
