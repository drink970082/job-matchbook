/**
 * Integration tests: the unresolved-feeds viewer against a REAL throwaway
 * SQLite. Exercises the actual groupBy/count over seeded `feed_unresolved`
 * rows — what the mocked unit test can't reach.
 */
import { getUnresolvedFeeds } from '@/lib/unresolved-actions'
import { prisma, resetDb } from '@/test-utils/db'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

function makeUnresolved(overrides: {
    url: string
    host: string
    reason: string
    feed?: string
}) {
    return {
        feed: overrides.feed ?? 'simplify',
        url: overrides.url,
        company_name: 'Acme',
        job_title: 'Engineer',
        host: overrides.host,
        reason: overrides.reason,
        created_at: '2026-06-17T00:00:00Z',
    }
}

async function seed(rows: { url: string; host: string; reason: string }[]) {
    for (const r of rows) {
        await prisma.feed_unresolved.create({ data: makeUnresolved(r) })
    }
}

test('groups by (host, reason) with correct counts and total', async () => {
    await seed([
        { url: 'u1', host: 'myworkdayjobs.com', reason: 'workday_deferred' },
        { url: 'u2', host: 'myworkdayjobs.com', reason: 'workday_deferred' },
        { url: 'u3', host: 'myworkdayjobs.com', reason: 'workday_deferred' },
        { url: 'u4', host: 'boards.greenhouse.io', reason: 'embedded_greenhouse' },
        { url: 'u5', host: 'weird.example', reason: 'unsupported_host' },
    ])

    const { data, total } = await getUnresolvedFeeds()

    expect(total).toBe(5)
    expect(data).toHaveLength(3)

    const byKey = new Map(data.map((d) => [`${d.host}::${d.reason}`, d.count]))
    expect(byKey.get('myworkdayjobs.com::workday_deferred')).toBe(3)
    expect(byKey.get('boards.greenhouse.io::embedded_greenhouse')).toBe(1)
    expect(byKey.get('weird.example::unsupported_host')).toBe(1)
})

test('orders groups by count descending', async () => {
    await seed([
        { url: 'a1', host: 'one.com', reason: 'unsupported_host' },
        { url: 'b1', host: 'two.com', reason: 'workday_deferred' },
        { url: 'b2', host: 'two.com', reason: 'workday_deferred' },
        { url: 'b3', host: 'two.com', reason: 'workday_deferred' },
        { url: 'c1', host: 'three.com', reason: 'embedded_greenhouse' },
        { url: 'c2', host: 'three.com', reason: 'embedded_greenhouse' },
    ])

    const { data } = await getUnresolvedFeeds()

    expect(data.map((d) => d.count)).toEqual([3, 2, 1])
    expect(data[0].host).toBe('two.com')
})

test('same host with different reasons forms distinct groups', async () => {
    await seed([
        { url: 'd1', host: 'dup.com', reason: 'workday_deferred' },
        { url: 'd2', host: 'dup.com', reason: 'workday_deferred' },
        { url: 'd3', host: 'dup.com', reason: 'unsupported_host' },
    ])

    const { data, total } = await getUnresolvedFeeds()

    expect(total).toBe(3)
    expect(data).toHaveLength(2)
    const byKey = new Map(data.map((d) => [`${d.host}::${d.reason}`, d.count]))
    expect(byKey.get('dup.com::workday_deferred')).toBe(2)
    expect(byKey.get('dup.com::unsupported_host')).toBe(1)
})

test('returns empty data and zero total when nothing is unresolved', async () => {
    const { data, total } = await getUnresolvedFeeds()
    expect(data).toEqual([])
    expect(total).toBe(0)
})
