import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeStatusHistory } from '@/test-utils/factories'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

const backfill = () => JSON.parse(execFileSync('node',
    [path.join(__dirname, '../../prisma/backfill-applied-history-243.mjs'), process.env.DATABASE_URL!], { encoding: 'utf8' }))
const historyOf = (id: number) => prisma.status_history.findMany({
    where: { application_id: id }, orderBy: [{ timestamp: 'asc' }, { id: 'asc' }] })
const statusOf = async (id: number) => (await prisma.applications.findUnique({ where: { id } }))!.status

test('the #243 backfill gives every application an initial Applied row and recomputes status', async () => {
    // No history, Applied.
    const a = await prisma.applications.create({ data: makeApplication({ company_name: 'A', date_applied: '2026-01-05' }) })
    // No history, non-Applied status (created with a status, or CSV-imported).
    const b = await prisma.applications.create({ data: makeApplication({ company_name: 'B', status: 'Screening', date_applied: '2026-01-05' }) })
    // History without an Applied row; a backdated change wrote status Rejected last.
    const c = await prisma.applications.create({ data: makeApplication({ company_name: 'C', status: 'Rejected', date_applied: '2026-10-20' }) })
    await prisma.status_history.create({ data: makeStatusHistory({ application_id: c.id, status: 'Interviewing', timestamp: '2026-11-10T12:00:00.000Z' }) })
    await prisma.status_history.create({ data: makeStatusHistory({ application_id: c.id, status: 'Rejected', timestamp: '2026-11-01T12:00:00.000Z' }) })
    // A history row dated before date_applied: the Applied row still goes first.
    const d = await prisma.applications.create({ data: makeApplication({ company_name: 'D', status: 'Screening', date_applied: '2026-03-01' }) })
    await prisma.status_history.create({ data: makeStatusHistory({ application_id: d.id, status: 'Screening', timestamp: '2026-02-01T12:00:00.000Z' }) })
    // Already has its Applied row: untouched.
    const e = await prisma.applications.create({ data: makeApplication({ company_name: 'E', date_applied: '2026-01-05' }) })
    await prisma.status_history.create({ data: makeStatusHistory({ application_id: e.id, status: 'Applied', timestamp: '2026-01-05T00:00:00.000Z' }) })

    expect(backfill()).toEqual({ applied_rows_added: 4, status_rows_added: 1, statuses_recomputed: 1 })

    expect((await historyOf(a.id)).map((h) => [h.status, h.timestamp])).toEqual([['Applied', '2026-01-05T00:00:00.000Z']])
    expect((await historyOf(b.id)).map((h) => h.status)).toEqual(['Applied', 'Screening'])
    expect(await statusOf(b.id)).toBe('Screening')
    expect((await historyOf(c.id)).map((h) => h.status)).toEqual(['Applied', 'Rejected', 'Interviewing'])
    expect(await statusOf(c.id)).toBe('Interviewing')
    expect((await historyOf(d.id)).map((h) => [h.status, h.timestamp])).toEqual([
        ['Applied', '2026-02-01T11:59:59.999Z'], ['Screening', '2026-02-01T12:00:00.000Z']])
    expect(await statusOf(d.id)).toBe('Screening')
    expect(await historyOf(e.id)).toHaveLength(1)

    for (const app of await prisma.applications.findMany()) expect((await historyOf(app.id)).length).toBeGreaterThan(0)

    expect(backfill()).toEqual({ applied_rows_added: 0, status_rows_added: 0, statuses_recomputed: 0 }) // idempotent
})
