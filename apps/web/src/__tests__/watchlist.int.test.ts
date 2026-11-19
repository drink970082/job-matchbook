/**
 * Integration tests: watchlist server actions against a REAL throwaway SQLite.
 * Covers what the mocked unit tests can't — the (source, slug) unique constraint
 * and round-tripping list/add/remove through Prisma.
 */
import { addWatchedCompany, getWatchedCompanies, removeWatchedCompany } from '@/lib/watchlist-actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeJobPosting, makeWatchedCompany } from '@/test-utils/factories'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())


test('add then list round-trips, ordered by name', async () => {
    await addWatchedCompany({ source: 'lever', slug: 'globex', name: 'Globex' })
    await addWatchedCompany({ source: 'greenhouse', slug: 'acme', name: 'Acme' })

    const { data, total } = await getWatchedCompanies()
    expect(total).toBe(2)
    expect(data.map((c) => c.name)).toEqual(['Acme', 'Globex']) // name asc
})


test('rejects a duplicate (source, slug)', async () => {
    const first = await addWatchedCompany({ source: 'ashby', slug: 'acme', name: 'Acme' })
    expect(first.success).toBe(true)

    const second = await addWatchedCompany({ source: 'ashby', slug: 'acme', name: 'Acme Again' })
    expect(second.success).toBe(false)

    expect((await getWatchedCompanies()).total).toBe(1)
})


test('the same slug on a different source is allowed', async () => {
    await addWatchedCompany({ source: 'greenhouse', slug: 'acme', name: 'Acme GH' })
    const other = await addWatchedCompany({ source: 'lever', slug: 'acme', name: 'Acme Lever' })
    expect(other.success).toBe(true)
    expect((await getWatchedCompanies()).total).toBe(2)
})


test('remove deletes the row', async () => {
    const created = await prisma.watched_companies.create({ data: makeWatchedCompany() })
    const res = await removeWatchedCompany(created.id)
    expect(res.success).toBe(true)
    expect((await getWatchedCompanies()).total).toBe(0)
})


test('unknown source is rejected and nothing is written', async () => {
    const res = await addWatchedCompany({ source: 'indeed', slug: 'x', name: 'X' })
    expect(res.success).toBe(false)
    expect((await getWatchedCompanies()).total).toBe(0)
})

test('getWatchedCompanies counts each board\'s postings fetched in the last 30 days', async () => {
    await prisma.watched_companies.create({ data: { source: 'greenhouse', slug: 'acme', name: 'Acme', created_at: 'x' } })
    await prisma.watched_companies.create({ data: { source: 'lever', slug: 'quiet', name: 'Quiet', created_at: 'x' } })
    const ago = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString()
    for (const [i, slug, src, at] of [[1, 'acme', 'greenhouse', ago(1)], [2, 'acme', 'greenhouse', ago(29)],
        [3, 'acme', 'greenhouse', ago(31)], [4, 'acme', 'lever', ago(1)]] as const) {
        await prisma.job_postings.create({ data: makeJobPosting({ external_id: `w${i}`, source: src, company_slug: slug, created_at: at }) })
    }
    const { data } = await getWatchedCompanies()
    expect(data.map((c) => [c.slug, c.postings_30d])).toEqual([['acme', 2], ['quiet', 0]])
})
