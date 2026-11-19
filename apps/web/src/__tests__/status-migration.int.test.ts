import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication } from '@/test-utils/factories'
import { STATUSES } from '@/lib/constants'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

const migrate = () => JSON.parse(execFileSync('node',
    [path.join(__dirname, '../../prisma/migrate-statuses-205.mjs'), process.env.DATABASE_URL!], { encoding: 'utf8' }))

test('the #205 migration maps old statuses and drops repeated history transitions', async () => {
    const a = await prisma.applications.create({ data: makeApplication({ status: 'Final Round' }) })
    const g = await prisma.applications.create({ data: makeApplication({ company_name: 'G', status: 'Ghosted' }) })
    const h = (id: number, status: string, timestamp: string) =>
        prisma.status_history.create({ data: { application_id: id, status, timestamp } })
    await h(a.id, 'Phone Screen', '2026-01-02')
    await h(a.id, 'Interviewing: 1st round', '2026-01-03')
    await h(a.id, 'Interviewing: 2nd round', '2026-01-04')
    await h(a.id, 'Final Round', '2026-01-05')
    await h(g.id, 'Ghosted', '2026-01-02')

    expect(migrate()).toEqual({ applications: 2, status_history: 5, duplicates_dropped: 2 })
    const history = await prisma.status_history.findMany({ where: { application_id: a.id }, orderBy: { timestamp: 'asc' } })
    expect(history.map((r) => r.status)).toEqual(['Screening', 'Interviewing'])
    const apps = await prisma.applications.findMany({ orderBy: { id: 'asc' } })
    expect(apps.map((r) => r.status)).toEqual(['Interviewing', 'Rejected'])
    for (const r of apps) expect(STATUSES).toContain(r.status)

    expect(migrate()).toEqual({ applications: 0, status_history: 0, duplicates_dropped: 0 }) // idempotent
})
