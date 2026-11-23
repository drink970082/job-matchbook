/**
 * Integration tests: watchlist server actions against a REAL throwaway SQLite.
 * Covers what the mocked unit tests can't — the (source, slug) unique constraint
 * and round-tripping list/add/remove through Prisma.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
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

// #231: each board's last-pass record, case by case from the fixture MCP list_sources
// reads too (apps/worker/tests/fixtures/board-health-cases.json).
type HealthCase = { name: string; health: string; row: Record<string, string | number | null> }
const HEALTH_CASES: HealthCase[] = JSON.parse(readFileSync(
    path.join(__dirname, '../../../worker/tests/fixtures/board-health-cases.json'), 'utf8')).cases

test('getWatchedCompanies returns each board\'s last-pass health, as MCP does', async () => {
    for (const [i, c] of HEALTH_CASES.entries()) {
        await prisma.watched_companies.create({ data: makeWatchedCompany({ slug: `b${i}`, name: `${i} ${c.name}`, ...c.row }) })
    }
    const cols = Object.keys(HEALTH_CASES[0].row)
    const { data } = await getWatchedCompanies()
    expect(data.map((r: any) => ({ ...Object.fromEntries(cols.map((k) => [k, r[k]])), health: r.health })))
        .toEqual(HEALTH_CASES.map((c) => ({ ...c.row, health: c.health })))
})

test('a board just added is never fetched until a worker pass records it', async () => {
    await addWatchedCompany({ source: 'greenhouse', slug: 'new', name: 'New' })
    const { data } = await getWatchedCompanies()
    expect([data[0].health, data[0].last_fetched_at]).toEqual(['never_fetched', null])
})

test('a dry run validates and resolves without adding', async () => {
    const res = await addWatchedCompany({ url: 'https://jobs.lever.co/acme', name: 'Acme', dryRun: true })
    expect(res).toEqual({ success: true, data: { source: 'lever', slug: 'acme', name: 'Acme', recipe: null } })
    expect(await prisma.watched_companies.count()).toBe(0)
    expect(await prisma.audit_log.count()).toBe(0)
    await addWatchedCompany({ source: 'lever', slug: 'acme', name: 'Acme' })
    const dup = await addWatchedCompany({ source: 'lever', slug: 'acme', name: 'Acme', dryRun: true })
    expect(dup).toEqual({ success: false, error: 'lever/acme is already on the watchlist' })
})
