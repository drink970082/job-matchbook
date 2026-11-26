/**
 * #244: the duplicate check compares normalized company and title; when both sides have a
 * posting, the posting is the identity. Real throwaway SQLite.
 */
import { addApplication, updateApplicationDetails } from '@/lib/application-actions'
import { importApplicationsCSV } from '@/lib/csv-actions'
import { markJobApplied } from '@/lib/job-actions'
import { linkApplication } from '@/lib/link-actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeJobPosting } from '@/test-utils/factories'

let n = 0
const job = (over: Record<string, unknown> = {}) => prisma.job_postings.create({ data: makeJobPosting({
    external_id: `e${++n}`, job_url: `https://example.com/jobs/${n}`, pipeline_status: 'new', ...over }) })
const add = (company_name: string, job_title: string, job_id?: number) => addApplication({ company_name, job_title, date_applied: '2026-11-17', job_id })

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

test('"Acme Inc" / "software engineer" duplicates "ACME" / "Software Engineer"; another title does not', async () => {
    const first: any = await add('ACME', 'Software Engineer')
    expect(await add('Acme Inc', 'software engineer')).toEqual({ success: false, error: `Application for ACME - Software Engineer already exists (#${first.data.id})` })
    expect((await add('Acme & Co.', 'Software Engineer')).success).toBe(false)
    expect((await add('Acme', 'Software Engineer (C++)')).success).toBe(true)
    expect((await add('Acme Robotics', 'Software Engineer')).success).toBe(true) // containment is a link suggestion, not a duplicate
    expect(await prisma.applications.count()).toBe(3)
})

test('same company and title, linked to two different postings, is allowed; the same posting twice is not', async () => {
    const [p, q, r] = [await job(), await job(), await job()]
    expect((await add('Acme', 'Engineer', p.id)).success).toBe(true)
    expect((await add('Acme Inc', 'engineer', q.id)).success).toBe(true)
    expect(((await add('Acme', 'Engineer', p.id)) as any).error).toMatch(/already linked/)
    expect((await markJobApplied(r.id, undefined, { stage: 'all' })).success).toBe(true)
    expect(await prisma.applications.count()).toBe(3)
})

test('one side without a posting is still a duplicate, both ways', async () => {
    const p = await job()
    const unlinked: any = await add('Acme', 'Engineer')
    expect((await add('Acme', 'Engineer', p.id)).success).toBe(false) // link #unlinked instead
    expect((await linkApplication(unlinked.data.id, p.id)).success).toBe(true)
    expect((await add('ACME', 'engineer')).success).toBe(false)
    expect(await prisma.applications.count()).toBe(1)
})

test('editing company or title runs the same check, and only then', async () => {
    const a: any = await add('Acme', 'Engineer')
    const b: any = await add('Acme', 'Analyst')
    expect(await updateApplicationDetails(b.data.id, { job_title: 'ENGINEER' })).toEqual({ success: false, error: `Application for Acme - Engineer already exists (#${a.data.id})` })
    expect((await prisma.applications.findUniqueOrThrow({ where: { id: b.data.id } })).job_title).toBe('Analyst')
    const c: any = await add('Globex', 'Engineer')
    expect((await updateApplicationDetails(c.data.id, { company_name: 'acme' })).success).toBe(false)
    expect((await updateApplicationDetails(a.data.id, { company_name: 'ACME, Inc.', job_title: 'engineer' })).success).toBe(true) // itself
    const [p, q] = [await job(), await job()]
    await linkApplication(a.data.id, p.id)
    expect((await updateApplicationDetails(b.data.id, { job_title: 'Engineer' })).success).toBe(false) // b has no posting
    await linkApplication(b.data.id, q.id)
    expect((await updateApplicationDetails(b.data.id, { job_title: 'Engineer' })).success).toBe(true)  // both have one
    // A pair stored before the check: other edits still work.
    const [x] = [await prisma.applications.create({ data: makeApplication({ company_name: 'Old', job_title: 'Role' }) }),
        await prisma.applications.create({ data: makeApplication({ company_name: 'old', job_title: 'role' }) })]
    expect((await updateApplicationDetails(x.id, { company_name: 'OLD', job_title: 'Role', notes: 'x' })).success).toBe(true)
})

test('CSV import skips a normalized duplicate of a stored row and of an earlier row', async () => {
    await add('Acme', 'Engineer')
    const res: any = await importApplicationsCSV('company_name,job_title,date_applied\nACME Inc,engineer,2026-01-01\nGlobex,Analyst,2026-01-01\nGlobex LLC,analyst,2026-01-02\n')
    expect([res.added, res.skipped]).toEqual([1, 2])
})

test('a company or title with no letters or digits is compared as written', async () => {
    expect((await add('Acme', '???')).success).toBe(true)
    expect((await add('Acme', '!!!')).success).toBe(true)
    expect((await add('Acme', '???')).success).toBe(false)
    expect((await add('???', 'Engineer')).success).toBe(true)
    expect((await add('!!!', 'Engineer')).success).toBe(true)
    expect((await add('!!! ', 'Engineer')).success).toBe(false)
    expect((await add('Acme', '---')).success).toBe(true)
    expect((await add('Acme', '--- ')).success).toBe(false)
    const p = await job({ job_title: '???' })
    expect((await markJobApplied(p.id, undefined, { stage: 'all' })).success).toBe(false)
    expect((await markJobApplied(p.id, undefined, { stage: 'all' }, 'web', { createNew: true })).success).toBe(true)
})
