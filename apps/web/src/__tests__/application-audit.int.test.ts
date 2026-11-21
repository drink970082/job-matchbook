/**
 * #242: deleting an application resets its postings to `new`, and every application
 * write (create, edit, status change, history-item delete, delete) leaves one audit_log
 * row with the actor and the row before/after - from the UI action and from /api/v1.
 */
import { POST as createApplication } from '@/app/api/v1/applications/route'
import { PATCH as patchApplication } from '@/app/api/v1/applications/[id]/route'
import { POST as postStatus } from '@/app/api/v1/applications/[id]/status/route'
import { POST as postApplied } from '@/app/api/v1/jobs/[id]/applied/route'
import {
    addApplication, deleteApplication, deleteHistoryItem, updateApplicationDetails, updateApplicationStatus,
} from '@/lib/application-actions'
import { markJobApplied } from '@/lib/job-actions'
import { importApplicationsCSV } from '@/lib/csv-actions'
import { getActivityTimeline } from '@/lib/activity-actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeJobPosting, makeStatusHistory } from '@/test-utils/factories'

const RW = 'rw-key-0123456789'
const req = (body: unknown, method = 'POST') => new Request('http://127.0.0.1:3000/api/v1/x', {
    method, headers: { 'content-type': 'application/json', authorization: `Bearer ${RW}` }, body: JSON.stringify(body),
})
const params = (id: number) => ({ params: { id: String(id) } })
const audits = () => prisma.audit_log.findMany({ orderBy: { id: 'asc' } })
const payload = (row: { payload: string }) => JSON.parse(row.payload)

beforeEach(async () => {
    await resetDb()
    process.env.ATS_API_KEY_READ_WRITE = RW
})
afterAll(() => prisma.$disconnect())

test('deleting an application resets its postings to new, so markJobApplied succeeds again', async () => {
    const jp = await prisma.job_postings.create({ data: makeJobPosting() })
    const marked = await markJobApplied(jp.id, 'SWE', { stage: 'all' })
    expect(marked.success).toBe(true)
    const appId = (marked as any).data.id

    const res = await deleteApplication(appId)
    expect(res.success).toBe(true)
    const after = await prisma.job_postings.findUniqueOrThrow({ where: { id: jp.id } })
    expect([after.pipeline_status, after.application_id]).toEqual(['new', null])

    expect((await markJobApplied(jp.id, 'SWE', { stage: 'all' })).success).toBe(true)
})

test('a delete that fails leaves the posting applied (reset and cascade are one transaction)', async () => {
    const jp = await prisma.job_postings.create({ data: makeJobPosting({ pipeline_status: 'applied' }) })
    expect((await deleteApplication(999)).success).toBe(false)
    expect((await prisma.job_postings.findUniqueOrThrow({ where: { id: jp.id } })).pipeline_status).toBe('applied')
    expect(await prisma.audit_log.count()).toBe(0)
})

test('UI writes: each of the five leaves one audit row, actor=web, with before/after', async () => {
    const created = await addApplication({ company_name: 'Acme', job_title: 'Engineer', date_applied: '2026-11-17' })
    const id = (created as any).data.id
    await updateApplicationDetails(id, { notes: 'recruiter called' })
    await updateApplicationStatus(id, 'Screening', '2026-11-18')
    const hist = await prisma.status_history.findFirstOrThrow({ where: { application_id: id, status: 'Screening' } })
    await deleteHistoryItem(hist.id)
    const jp = await prisma.job_postings.create({ data: makeJobPosting({ application_id: id, pipeline_status: 'applied' }) })
    await deleteApplication(id)

    const log = await audits()
    expect(log.map((r) => [r.entity, r.action, r.entity_id, r.actor])).toEqual([
        ['applications', 'add', id, 'web'],
        ['applications', 'update', id, 'web'],
        ['applications', 'status', id, 'web'],
        ['applications', 'remove_history', id, 'web'],
        ['applications', 'remove', id, 'web'],
    ])
    const [add, edit, status, unhist, remove] = log.map(payload)
    expect(add.company_name).toBe('Acme')
    expect([edit.before.notes, edit.after.notes]).toEqual(['', 'recruiter called'])
    expect([status.before.status, status.after.status, status.history.status]).toEqual(['Applied', 'Screening', 'Screening'])
    expect([unhist.before.status, unhist.after.status, unhist.removed.id]).toEqual(['Screening', 'Applied', hist.id])
    expect(remove.company_name).toBe('Acme')
    expect(remove.job_posting_ids).toEqual([jp.id])
})

test('/api/v1 writes and an MCP mark-applied are audited with actor=mcp', async () => {
    expect((await createApplication(req({ company_name: 'Acme', job_title: 'Engineer', date_applied: '2026-11-17' }))).status).toBe(200)
    const app = await prisma.applications.findFirstOrThrow()
    expect((await patchApplication(req({ notes: 'n' }, 'PATCH'), params(app.id))).status).toBe(200)
    expect((await postStatus(req({ status: 'Offer' }), params(app.id))).status).toBe(200)
    const jp = await prisma.job_postings.create({ data: makeJobPosting({ company_name: 'Beta' }) })
    expect((await postApplied(req({ category: 'SWE' }), params(jp.id))).status).toBe(200)

    const log = await audits()
    expect(log.map((r) => [r.action, r.actor])).toEqual([['add', 'mcp'], ['update', 'mcp'], ['status', 'mcp'], ['add', 'mcp']])
    expect(payload(log[3]).company_name).toBe('Beta')
})

test('a rejected write is not audited', async () => {
    const app = await prisma.applications.create({ data: makeApplication() })
    await addApplication({ company_name: 'Acme', job_title: 'Engineer', date_applied: '2026-11-17' }) // duplicate
    await updateApplicationStatus(app.id, 'Applied')                                                   // no-op
    await updateApplicationDetails(999, { notes: 'x' })                                                // missing
    await deleteHistoryItem(999)
    expect(await prisma.audit_log.count()).toBe(0)
})

test('the activity timeline shows edits and deletes once, and creates/status changes are not duplicated', async () => {
    const created = await addApplication({ company_name: 'Acme', job_title: 'Engineer', date_applied: '2026-11-17' })
    const id = (created as any).data.id
    await updateApplicationStatus(id, 'Screening', '2026-11-18')
    await updateApplicationDetails(id, { notes: 'n' })
    const h = await prisma.status_history.create({ data: makeStatusHistory({ application_id: id, status: 'Rejected', timestamp: '2026-11-19T12:00:00.000Z' }) })
    await deleteHistoryItem(h.id)
    const kept = await addApplication({ company_name: 'Beta', job_title: 'Analyst', date_applied: '2026-11-16' })
    await deleteApplication(id)

    const texts = (await getActivityTimeline()).items.map((i) => i.text)
    expect(texts.slice(0, 3)).toEqual([
        'Deleted the application Acme - Engineer',
        'Removed Rejected from the history of Acme - Engineer',
        'Edited Acme - Engineer',
    ])
    expect(texts.slice(3)).toEqual(['Applied to Beta - Analyst'])
    expect((kept as any).success).toBe(true)
})

test('CSV import audits one add per imported application (actor=web), none for a skipped duplicate', async () => {
    await prisma.applications.create({ data: makeApplication() })
    const csv = 'company_name,job_title,date_applied\nAcme,Engineer,2026-11-01\nBeta,Analyst,2026-11-02\nGamma,Dev,2026-11-03\n'
    const res: any = await importApplicationsCSV(csv)
    expect(res.success).toBe(true)
    const log = await audits()
    expect(log.map((r) => [r.entity, r.action, r.actor, payload(r).company_name])).toEqual([
        ['applications', 'add', 'web', 'Beta'], ['applications', 'add', 'web', 'Gamma'],
    ])
})
