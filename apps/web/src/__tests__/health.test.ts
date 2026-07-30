/**
 * @jest-environment node
 */
// node env so the Web Request/Response globals next/server needs are present.
// Unit test for the /api/health liveness probe: it must report 200 only when the
// DB is actually reachable and 503 when Prisma throws (the stale-bind-mount case
// the autoheal sidecar restarts on). See docs/SPEC.md §6.
jest.mock('@/lib/db', () => ({
    __esModule: true,
    prisma: { $queryRaw: jest.fn() },
}))

import { prisma } from '@/lib/db'
import { GET } from '@/app/api/health/route'

const mockQueryRaw = (prisma as unknown as { $queryRaw: jest.Mock }).$queryRaw

beforeEach(() => mockQueryRaw.mockReset())

test('GET returns 200 ok when the DB query succeeds', async () => {
    mockQueryRaw.mockResolvedValue([{ '1': 1 }])
    const res = await GET()
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ status: 'ok' })
})

test('the probe reads a table, not a constant expression', async () => {
    // `SELECT 1` is a constant SQLite answers from the query planner without touching a
    // page, so it returns 200 with the database file GONE -- the exact failure this probe
    // exists to catch. Reading sqlite_master forces a real page read and, under WAL, the
    // -wal/-shm sidecars. Pinned here because the regression is invisible: both existing
    // tests pass either way, since they mock $queryRaw and never look at the SQL.
    mockQueryRaw.mockResolvedValue([{ name: 'applications' }])
    await GET()
    const sql = (mockQueryRaw.mock.calls[0][0] as unknown as string[]).join('?')
    expect(sql).toMatch(/from\s+sqlite_master/i)
    expect(sql).not.toMatch(/^\s*select\s+1\s*$/i)
})

test('GET returns 503 with a generic error when the DB query throws', async () => {
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {})
    try {
        mockQueryRaw.mockRejectedValue(new Error('SQLITE_CANTOPEN'))
        const res = await GET()
        expect(res.status).toBe(503)
        expect(await res.json()).toEqual({ status: 'error', error: 'database unreachable' })
    } finally {
        spy.mockRestore()
    }
})
