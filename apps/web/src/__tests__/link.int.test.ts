/**
 * #241: link applications to postings, against a real throwaway SQLite. Suggestions never
 * write; a link is one explicit call, the same from web and /api/v1.
 */
import { POST as createApplication } from '@/app/api/v1/applications/route'
import { POST as postLink } from '@/app/api/v1/applications/[id]/link/route'
import { POST as postApplied } from '@/app/api/v1/jobs/[id]/applied/route'
import { GET as getSuggestions } from '@/app/api/v1/link-suggestions/route'
import { addApplication, deleteApplication, getApplications } from '@/lib/application-actions'
import { getActivityTimeline } from '@/lib/activity-actions'
import { getJobPostings, markJobApplied } from '@/lib/job-actions'
import { getLinkSuggestions, linkApplication } from '@/lib/link-actions'
import { todayISO } from '@/lib/utils'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeJobPosting } from '@/test-utils/factories'

const RW = 'rw-key-0123456789'
const READ = 'read-key-0123456789'
const req = (body?: unknown, key = RW, url = 'http://127.0.0.1:3000/api/v1/x') => new Request(url, body === undefined
    ? { headers: { authorization: `Bearer ${key}` } }
    : { method: 'POST', headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` }, body: JSON.stringify(body) })
const params = (id: number) => ({ params: { id: String(id) } })
const suggest = (query = '', key = READ) => getSuggestions(req(undefined, key, `http://127.0.0.1:3000/api/v1/link-suggestions${query}`))

let n = 0
const job = (over: Record<string, unknown> = {}) => prisma.job_postings.create({ data: makeJobPosting({
    external_id: `e${++n}`, job_url: `https://example.com/jobs/${n}`, pipeline_status: 'new', verdict: 'keep', ...over }) })
const application = (over: Record<string, unknown> = {}) => prisma.applications.create({ data: makeApplication(over) })
const posting = (id: number) => prisma.job_postings.findUniqueOrThrow({ where: { id } })

beforeEach(async () => {
    await resetDb()
    process.env.ATS_API_KEY_READ_WRITE = RW
    process.env.ATS_API_KEY_READ = READ
})
afterAll(() => prisma.$disconnect())

test('suggestions for one application: tiers 1-3, best first, writing nothing', async () => {
    const app = await application({ job_title: 'Backend Engineer', application_url: 'https://example.com/jobs/same?utm_source=1' })
    const t1 = await job({ job_title: 'Renamed', job_url: 'https://example.com/jobs/same' })
    const t2 = await job({ company_name: 'ACME, Inc.', job_title: 'backend engineer' })
    const t3 = await job({ job_title: 'Frontend Engineer' })
    await job({ company_name: 'Globex' })
    await job({ job_title: 'Backend Engineer', pipeline_status: 'removed' })
    const other = await application({ company_name: 'Other' })
    await job({ job_title: 'Backend Engineer', application_id: other.id, pipeline_status: 'applied' })
    const before = await prisma.job_postings.findMany()

    const res: any = await getLinkSuggestions({ applicationId: app.id })
    expect(res.data).toHaveLength(1)
    expect(res.data[0].application.id).toBe(app.id)
    expect(res.data[0].suggestions.map((s: any) => [s.job_id, s.tier])).toEqual([[t1.id, 1], [t2.id, 2], [t3.id, 3]])
    expect(await prisma.job_postings.findMany()).toEqual(before)
    expect(await prisma.audit_log.count()).toBe(0)
    // The same answer over the API, with the read key.
    const api = await suggest(`?application_id=${app.id}`)
    expect([api.status, (await api.json()).data]).toEqual([200, res.data])
})

test('the whole list: applications with a candidate only, tier 1-2 first, pickers capped', async () => {
    const picker = await application({ company_name: 'Globex', job_title: 'Analyst' })
    for (let i = 0; i < 7; i++) await job({ company_name: 'Globex', job_title: `Role ${i}` })
    const settled = await application({ company_name: 'Acme', job_title: 'Engineer' })
    for (let i = 0; i < 7; i++) await job()               // seven same-title postings: tier 2 is never cut
    await application({ company_name: 'Nowhere' })
    const linked = await application({ company_name: 'Acme', job_title: 'Linked' })
    await job({ application_id: linked.id, pipeline_status: 'applied' })

    const res: any = await getLinkSuggestions()
    expect(res.data.map((d: any) => [d.application.id, d.suggestions.length, d.more])).toEqual([[settled.id, 7, 0], [picker.id, 5, 2]])
    const one: any = await getLinkSuggestions({ applicationId: picker.id })
    expect([one.data[0].suggestions.length, one.data[0].more]).toEqual([7, 0])
})

test('suggestions for one posting name the applications it may be', async () => {
    const app = await application()
    await application({ company_name: 'Globex' })
    const p = await job()
    await job()
    const res: any = await (await suggest(`?job_id=${p.id}`)).json()
    expect(res.data.map((d: any) => [d.application.id, d.suggestions.map((s: any) => s.job_id)])).toEqual([[app.id, [p.id]]])
})

test('suggest route: auth and bad ids', async () => {
    expect((await suggest('', 'nope')).status).toBe(401)
    expect((await suggest('?application_id=x')).status).toBe(400)
    for (const q of ['?application_id=999', '?job_id=999']) expect((await suggest(q)).status).toBe(400)
    const app = await application()
    const p = await job({ application_id: app.id, pipeline_status: 'applied' })
    expect((await (await suggest(`?application_id=${app.id}`)).json()).error).toMatch(`already linked to job ${p.id}`)
    expect((await (await suggest(`?job_id=${p.id}`)).json()).error).toMatch(`already linked to application ${app.id}`)
})

test('linking from web and from /api/v1 produces the same rows but the actor', async () => {
    const rows: any[] = []
    for (const via of ['web', 'mcp'] as const) {
        const app = await application({ company_name: `Co ${via}` })
        const p = await job({ company_name: 'Posting Co' })
        if (via === 'web') expect((await linkApplication(app.id, p.id)).success).toBe(true)
        else expect((await postLink(req({ job_id: p.id }), params(app.id))).status).toBe(200)
        const after = await posting(p.id)
        const log = await prisma.audit_log.findFirstOrThrow({ orderBy: { id: 'desc' } })
        const payload = JSON.parse(log.payload)
        expect([after.application_id, log.entity_id, log.actor]).toEqual([app.id, app.id, via])
        rows.push({ pipeline_status: after.pipeline_status, verdict: after.verdict, touched: after.updated_at !== null,
            audit: [log.entity, log.action], before: [payload.job_posting.id === p.id, payload.job_posting.pipeline_status, payload.job_posting.application_id],
            application: (await prisma.applications.findUniqueOrThrow({ where: { id: app.id } })).last_updated })
    }
    expect(rows[0]).toEqual(rows[1])
    expect(rows[0]).toMatchObject({ pipeline_status: 'applied', touched: true, audit: ['applications', 'link'], before: [true, 'new', null] })
    expect((await getActivityTimeline()).items.map((i) => i.text)).toContain('Linked Co web - Engineer to its posting')
})

test('a link is refused, not re-pointed, and the same pair twice changes nothing', async () => {
    const [a, b] = [await application({ company_name: 'A' }), await application({ company_name: 'B' })]
    const [p, q, gone] = [await job(), await job(), await job({ pipeline_status: 'removed' })]
    expect((await linkApplication(a.id, p.id)).success).toBe(true)
    const audits = await prisma.audit_log.count()
    expect((await linkApplication(a.id, p.id)).success).toBe(true)
    expect(await linkApplication(b.id, p.id)).toEqual({ success: false, error: `Job ${p.id} is already linked to application ${a.id}` })
    expect(await linkApplication(a.id, q.id)).toEqual({ success: false, error: `Application ${a.id} is already linked to job ${p.id}` })
    expect((await linkApplication(b.id, gone.id)).success).toBe(false)
    expect(await linkApplication(999, q.id)).toEqual({ success: false, error: 'Application not found' })
    expect(await linkApplication(b.id, 999)).toEqual({ success: false, error: 'Job posting not found' })
    expect((await linkApplication(b.id, q.id, 'root' as any)).success).toBe(false)
    expect((await postLink(req({}), params(b.id))).status).toBe(400)
    expect((await postLink(req({ job_id: q.id }, READ), params(b.id))).status).toBe(403)
    expect(await prisma.audit_log.count()).toBe(audits)
    expect((await posting(q.id)).application_id).toBeNull()
    // Deleting the application frees the posting again (#242).
    await deleteApplication(a.id)
    expect((await linkApplication(b.id, p.id)).success).toBe(true)
})

test('mark applied offers the matching application instead of failing, and writes nothing', async () => {
    const app = await application({ company_name: 'ACME', job_title: 'engineer' })
    const p = await job({ company_name: 'Acme Inc', job_title: 'Engineer' })
    const res: any = await markJobApplied(p.id, 'SWE', { stage: 'all' })
    expect(res).toMatchObject({ success: false, match: { id: app.id, tier: 2 } })
    expect(res.error).toContain(`application #${app.id}`)
    const api = await postApplied(req({}), params(p.id))
    expect([api.status, (await api.json()).error]).toEqual([400, res.error])
    expect([(await posting(p.id)).pipeline_status, await prisma.applications.count(), await prisma.audit_log.count()]).toEqual(['new', 1, 0])
    // The operator says it is another application.
    expect((await postApplied(req({ create_new: true }), params(p.id))).status).toBe(200)
    expect((await posting(p.id)).application_id).not.toBe(app.id)
})

test('mark applied: a tier-3 application is no match, and one linked to another posting is another application', async () => {
    const other = await application({ job_title: 'Accountant' })
    const linked = await application({ job_title: 'Engineer' })
    await job({ job_title: 'Engineer', application_id: linked.id, pipeline_status: 'applied' })
    const p = await job({ job_title: 'Engineer' })
    expect((await markJobApplied(p.id, undefined, { stage: 'all' })).success).toBe(true)
    expect(await prisma.applications.count({ where: { job_title: 'Engineer' } })).toBe(2)
    const q = await job({ job_title: 'Analyst' })
    expect((await markJobApplied(q.id, undefined, { stage: 'all' })).success).toBe(true)
    expect(other.job_title).toBe('Accountant')
})

test('mark applied takes a date, default today, and rejects one that is not a date', async () => {
    const [p, q, r] = [await job({ job_title: 'A' }), await job({ job_title: 'B' }), await job({ job_title: 'C' })]
    expect(((await markJobApplied(p.id, undefined, { stage: 'all' })) as any).data.date_applied).toBe(todayISO())
    expect((await postApplied(req({ date: '2026-11-02' }), params(q.id))).status).toBe(200)
    const app = await prisma.applications.findFirstOrThrow({ where: { job_title: 'B' }, include: { status_history: true } })
    expect([app.date_applied, app.status_history[0].timestamp]).toEqual(['2026-11-02', '2026-11-02T00:00:00.000Z'])
    for (const date of ['2026-02-30', '11/02/2026', '']) expect((await postApplied(req({ date }), params(r.id))).status).toBe(400)
    expect((await postApplied(req({ create_new: 'yes' }), params(r.id))).status).toBe(400)
    expect((await posting(r.id)).pipeline_status).toBe('new')
})

test('an application recorded with a job_id is linked in the same write, or not recorded at all', async () => {
    const p = await job()
    const body = { company_name: 'Acme', job_title: 'Engineer', date_applied: '2026-11-17', job_id: p.id }
    expect((await createApplication(req(body))).status).toBe(200)
    const app = await prisma.applications.findFirstOrThrow()
    expect(await posting(p.id)).toMatchObject({ application_id: app.id, pipeline_status: 'applied' })
    expect((await prisma.audit_log.findMany({ orderBy: { id: 'asc' } })).map((a) => [a.action, a.actor])).toEqual([['add', 'mcp'], ['link', 'mcp']])
    expect((await createApplication(req({ ...body, job_title: 'Other' }))).status).toBe(400)          // posting taken
    expect((await addApplication({ ...body, job_title: 'Third', job_id: 999 })).success).toBe(false)
    expect((await createApplication(req({ ...body, job_title: 'Fourth', job_id: 'x' }))).status).toBe(400)
    expect(await prisma.applications.count()).toBe(1)
})

test('a fetched posting shows the unlinked application it may be; linked ones and tier 3 do not', async () => {
    const app = await application()
    await application({ company_name: 'Globex', job_title: 'Accountant' })
    const p = await job()
    const tier3 = await job({ company_name: 'Globex', job_title: 'Engineer' })
    const rows = async () => new Map((await getJobPostings({ stage: 'all' })).data.map((r: any) => [r.id, r.applied_match]))
    expect((await rows()).get(p.id)).toMatchObject({ id: app.id, tier: 2, date_applied: '2026-01-01' })
    expect((await rows()).get(tier3.id)).toBeNull()
    expect((await getApplications({ search: 'Acme' })).data[0].job_postings).toEqual([])
    await linkApplication(app.id, p.id)
    expect((await rows()).get(p.id)).toBeNull()
    expect((await getApplications({ search: 'Acme' })).data[0].job_postings).toEqual([{ id: p.id }])
})
