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
        // Reads an APPLICATION table, and the table is the load-bearing part — measured,
        // not reasoned (drill 2026-07-29, docs/SPEC.md §6):
        //
        //   failure mode               | SELECT 1 | sqlite_master | job_postings
        //   rename dir  AFTER connect  |   200    |      200      |     200
        //   delete file AFTER connect  |   200    |      200      |     200
        //   rename dir  BEFORE connect |   503    |      503      |     503
        //   delete file BEFORE connect |   200    |      200      |     503   <-- only this
        //
        // The last row is the one that matters: with the file absent SQLite silently
        // CREATES an empty database, so both weaker probes report healthy forever against
        // a tracker with no data in it. Naming a real table turns that into
        // `no such table: job_postings` -> 503 -> autoheal restarts the container.
        //
        // `SELECT 1` vs `sqlite_master` makes NO difference in any mode: once the
        // connection is open, reads go through the existing fd, so nothing on the
        // filesystem can invalidate them. The AFTER-connect column is not fixable by a
        // probe for the same reason, and is accepted (a restart re-opens).
        //
        // A row rather than `count(*)`: the SQLite connector returns counts as BigInt,
        // which throws on JSON.stringify. Nothing serializes this result today, and this
        // way nothing can start to.
        await prisma.$queryRaw`SELECT 1 FROM job_postings LIMIT 1`
        return NextResponse.json({ status: 'ok' }, { status: 200 })
    } catch (err) {
        // Detail stays server-side only; the 503 body must not leak internals (paths,
        // driver strings). The autoheal sidecar keys on the status code, not the body.
        console.error('[health] DB probe failed:', err)
        return NextResponse.json({ status: 'error', error: 'database unreachable' }, { status: 503 })
    }
}
