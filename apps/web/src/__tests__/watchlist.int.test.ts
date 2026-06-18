/**
 * Integration tests: watchlist server actions against a REAL throwaway SQLite.
 * Covers what the mocked unit tests can't — the (source, slug) unique constraint
 * and round-tripping list/add/remove through Prisma.
 */
import {
    addWatchedCompany,
    getWatchedCompanies,
    removeWatchedCompany,
} from '@/lib/actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeWatchedCompany } from '@/test-utils/factories'

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
