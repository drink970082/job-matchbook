/**
 * Integration tests: server actions against a REAL throwaway SQLite (via the
 * shared PrismaClient pointed at the temp DB). These cover what the Prisma-mocked
 * unit tests can't — transaction atomicity/rollback, aggregation correctness,
 * pagination/ordering, the unique constraint, and FK cascade/SetNull.
 */
import { addApplication, deleteApplication, deleteHistoryItem, getApplications, updateApplicationStatus } from '@/lib/application-actions'
import { getKPIs } from '@/lib/analytics-actions'
import { exportApplicationsCSV, importApplicationsCSV } from '@/lib/csv-actions'
import { getJobPostings, markJobApplied } from '@/lib/job-actions'
import { getCandidateProfile } from '@/lib/profile-actions'
import { getCategories, setCategories } from '@/lib/category-actions'
import { todayISO } from '@/lib/utils'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeJobPosting, makeStatusHistory } from '@/test-utils/factories'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

// --- categories: the user-configurable vocabulary (app_settings) ----------

test('getCategories returns defaults and configured=false before anything is set', async () => {
    const { categories, configured } = await getCategories()
    expect(configured).toBe(false)
    expect(categories).toContain('Others')
    expect(categories.length).toBeGreaterThan(1)
})

test('setCategories persists a de-duplicated list that getCategories reads back', async () => {
    const res = await setCategories(['Investment Banking', 'Private Equity', 'investment banking', '  '])
    expect(res.success).toBe(true)
    const { categories, configured } = await getCategories()
    expect(configured).toBe(true)
    // trimmed, blanks dropped, case-insensitive dedupe (first spelling wins)
    expect(categories).toEqual(['Investment Banking', 'Private Equity'])
})

test('setCategories rejects an empty list and leaves the stored value untouched', async () => {
    await setCategories(['Product'])
    const res = await setCategories([])
    expect(res.success).toBe(false)
    const { categories } = await getCategories()
    expect(categories).toEqual(['Product'])
})


// --- markJobApplied: transaction atomicity --------------------------------

test('markJobApplied creates the application and links the posting', async () => {
    const jp = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'm1', company_name: 'Acme', job_title: 'Eng' }),
    })
    const res = await markJobApplied(jp.id, 'MLE', { stage: 'all' })
    expect(res.success).toBe(true)

    const apps = await prisma.applications.findMany()
    expect(apps).toHaveLength(1)
    expect(apps[0].category).toBe('MLE')                          // chosen category, not 'Others'
    const updated = await prisma.job_postings.findUnique({ where: { id: jp.id } })
    expect(updated!.pipeline_status).toBe('applied')
    expect(updated!.application_id).toBe(apps[0].id)
})

test('markJobApplied rolls back when a matching application already exists', async () => {
    const jp = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'm2', company_name: 'Dup', job_title: 'Eng' }),
    })
    await prisma.applications.create({ data: makeApplication({ company_name: 'Dup', job_title: 'Eng' }) })
    const before = await prisma.applications.count()

    const res = await markJobApplied(jp.id, undefined, { stage: 'all' })
    expect(res.success).toBe(false)
    expect(await prisma.applications.count()).toBe(before)        // no new app (rolled back)
    const after = await prisma.job_postings.findUnique({ where: { id: jp.id } })
    expect(after!.pipeline_status).toBe('scored')                 // posting untouched
    expect(after!.application_id).toBeNull()
})

test('markJobApplied returns not-found for a missing id', async () => {
    expect(await markJobApplied(99999, undefined, { stage: 'all' })).toEqual({ success: false, error: 'Job posting not found' })
})


// --- addApplication: transaction atomicity ---------------------------------

test('addApplication rejects a duplicate (company,title) atomically', async () => {
    const first = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-01-01' })
    expect(first.success).toBe(true)
    const dup = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-02-01' })
    expect(dup.success).toBe(false)
    expect(dup.error).toContain('already exists')
    expect(await prisma.applications.count()).toBe(1)
})


// --- #243: status = latest history row by timestamp (ties by id) ----------

const historyOf = (id: number) => prisma.status_history.findMany({
    where: { application_id: id }, orderBy: [{ timestamp: 'asc' }, { id: 'asc' }] })
const statusOf = async (id: number) => (await prisma.applications.findUnique({ where: { id } }))!.status

test('addApplication writes the initial Applied row dated date_applied', async () => {
    const res = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-01-05' }, 'mcp')
    const hist = await historyOf(res.data!.id)
    expect(hist.map((h) => [h.status, h.timestamp, h.actor])).toEqual([['Applied', '2026-01-05T00:00:00.000Z', 'mcp']])
})

test('addApplication with a non-Applied status writes Applied then that status, which is current', async () => {
    const res = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-01-05', status: 'Screening' })
    expect((await historyOf(res.data!.id)).map((h) => h.status)).toEqual(['Applied', 'Screening'])
    expect(await statusOf(res.data!.id)).toBe('Screening')
})

test('the initial Applied row is never dated after now, so a same-day change stays current', async () => {
    // A date_applied ahead of UTC (a user east of UTC applying just after local midnight).
    const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10)
    const res = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: tomorrow })
    await updateApplicationStatus(res.data!.id, 'Screening')
    expect(await statusOf(res.data!.id)).toBe('Screening')
})

test('markJobApplied and CSV import write the initial Applied row', async () => {
    const jp = await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'h1' }) })
    expect((await markJobApplied(jp.id, undefined, { stage: 'all' })).success).toBe(true)
    const marked = await prisma.applications.findFirstOrThrow()
    expect((await historyOf(marked.id)).map((h) => h.status)).toEqual(['Applied'])

    await importApplicationsCSV('company_name,job_title,date_applied,status\nBeta,DS,2026-01-02,Rejected\n')
    const beta = await prisma.applications.findFirst({ where: { company_name: 'Beta' } })
    expect((await historyOf(beta!.id)).map((h) => [h.status, h.timestamp])).toEqual([
        ['Applied', '2026-01-02T00:00:00.000Z'], ['Rejected', '2026-01-02T00:00:00.000Z']])
    expect(beta!.status).toBe('Rejected')
})

test('a backdated status change does not become current; deleting either row recomputes', async () => {
    const res = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-10-20' })
    const id = res.data!.id
    expect((await updateApplicationStatus(id, 'Interviewing', '2026-11-10')).success).toBe(true)
    expect((await updateApplicationStatus(id, 'Rejected', '2026-11-01')).success).toBe(true)
    expect(await statusOf(id)).toBe('Interviewing')

    const hist = await historyOf(id)
    const interviewing = hist.find((h) => h.status === 'Interviewing')!
    const rejected = hist.find((h) => h.status === 'Rejected')!
    await deleteHistoryItem(interviewing.id)
    expect(await statusOf(id)).toBe('Rejected')
    await deleteHistoryItem(rejected.id)
    expect(await statusOf(id)).toBe('Applied')
})

test('a date-only write for today is stamped now, so it sorts after an earlier now write', async () => {
    const res = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-01-05' })
    const id = res.data!.id
    await updateApplicationStatus(id, 'Screening')                    // dropdown / MCP: no date -> now
    await updateApplicationStatus(id, 'Interviewing', todayISO())     // modal default: today's date
    expect(await statusOf(id)).toBe('Interviewing')
    const hist = await historyOf(id)
    expect(hist.at(-1)!.status).toBe('Interviewing')
    expect(hist.at(-1)!.timestamp).not.toBe(`${todayISO()}T12:00:00.000Z`) // not the noon stamp
    expect(hist.at(-1)!.timestamp >= hist.at(-2)!.timestamp).toBe(true)
})

test('updateApplicationStatus returns the recomputed current status and the recorded one', async () => {
    const res = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-10-20' })
    const id = res.data!.id
    expect(await updateApplicationStatus(id, 'Interviewing', '2026-11-10'))
        .toEqual({ success: true, data: { status: 'Interviewing', recorded: 'Interviewing' } })
    expect(await updateApplicationStatus(id, 'Rejected', '2026-11-01'))
        .toEqual({ success: true, data: { status: 'Interviewing', recorded: 'Rejected' } })
})

test('a future-dated change is stamped now, so a later no-date change still becomes current', async () => {
    const res = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-01-05' })
    const id = res.data!.id
    const tomorrow = new Date(Date.now() + 2 * 86_400_000).toISOString().slice(0, 10)
    const before = new Date().toISOString()
    await updateApplicationStatus(id, 'Screening', tomorrow)
    expect((await historyOf(id)).at(-1)!.timestamp <= new Date().toISOString()).toBe(true)
    expect((await historyOf(id)).at(-1)!.timestamp >= before).toBe(true)
    await updateApplicationStatus(id, 'Interviewing')
    expect(await statusOf(id)).toBe('Interviewing')
})

test('an initial Applied row for a non-ISO date_applied is stamped now', async () => {
    const before = new Date().toISOString()
    const res = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '1/5/2026' })
    const [row] = await historyOf(res.data!.id)
    expect(row.status).toBe('Applied')
    expect(row.timestamp >= before && row.timestamp <= new Date().toISOString()).toBe(true)

    await importApplicationsCSV('company_name,job_title,date_applied\nBeta,DS,Jan 5 2026\n')
    const beta = await prisma.applications.findFirstOrThrow({ where: { company_name: 'Beta' } })
    expect((await historyOf(beta.id))[0].timestamp >= before).toBe(true)
})

test('the status audit row snapshots the recomputed status, not the requested one', async () => {
    const res = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-10-20' })
    const id = res.data!.id
    await updateApplicationStatus(id, 'Interviewing', '2026-11-10')
    await updateApplicationStatus(id, 'Rejected', '2026-11-01')
    const audit = await prisma.audit_log.findFirstOrThrow({ where: { action: 'status' }, orderBy: { id: 'desc' } })
    const payload = JSON.parse(audit.payload!)
    expect(payload.after.status).toBe('Interviewing')
    expect(payload.history.status).toBe('Rejected')

    await deleteHistoryItem(payload.history.id)
    const removed = await prisma.audit_log.findFirstOrThrow({ where: { action: 'remove_history' } })
    expect(JSON.parse(removed.payload!).after.status).toBe('Interviewing')
})

test('deleting the backdated row leaves the later one current', async () => {
    const res = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-10-20' })
    const id = res.data!.id
    await updateApplicationStatus(id, 'Interviewing', '2026-11-10')
    await updateApplicationStatus(id, 'Rejected', '2026-11-01')
    const rejected = (await historyOf(id)).find((h) => h.status === 'Rejected')!
    await deleteHistoryItem(rejected.id)
    expect(await statusOf(id)).toBe('Interviewing')
})

test('history rows on the same timestamp resolve by id', async () => {
    const app = await prisma.applications.create({ data: makeApplication({ status: 'Screening' }) })
    const ts = '2026-01-02T12:00:00.000Z'
    await prisma.status_history.create({ data: makeStatusHistory({ application_id: app.id, status: 'Screening', timestamp: ts }) })
    const last = await prisma.status_history.create({ data: makeStatusHistory({ application_id: app.id, status: 'Rejected', timestamp: ts }) })
    const extra = await prisma.status_history.create({ data: makeStatusHistory({ application_id: app.id, status: 'Offer', timestamp: '2026-01-01T00:00:00.000Z' }) })
    await deleteHistoryItem(extra.id)
    expect(await statusOf(app.id)).toBe('Rejected')
    await deleteHistoryItem(last.id)
    expect(await statusOf(app.id)).toBe('Screening')
})


// --- updateApplicationStatus: guards + timezone-safe timestamp ------------

test('updateApplicationStatus transitions and records a noon-UTC history row', async () => {
    const app = await prisma.applications.create({ data: makeApplication({ status: 'Applied' }) })
    const res = await updateApplicationStatus(app.id, 'Screening', '2026-05-10')
    expect(res.success).toBe(true)

    const updated = await prisma.applications.findUnique({ where: { id: app.id } })
    expect(updated!.status).toBe('Screening')
    const hist = await prisma.status_history.findMany({ where: { application_id: app.id } })
    expect(hist).toHaveLength(1)
    expect(hist[0].timestamp).toBe('2026-05-10T12:00:00.000Z')   // noon-UTC avoids day-shift
})

test('updateApplicationStatus rejects an invalid status', async () => {
    const app = await prisma.applications.create({ data: makeApplication() })
    expect((await updateApplicationStatus(app.id, 'Nonsense')).error).toBe('Invalid status')
    expect(await prisma.status_history.count()).toBe(0)
})

test('updateApplicationStatus returns not-found for a missing id', async () => {
    expect((await updateApplicationStatus(99999, 'Offer')).error).toBe('Application not found')
})

test('updateApplicationStatus refuses a no-op same-status transition', async () => {
    const app = await prisma.applications.create({ data: makeApplication({ status: 'Applied' }) })
    const res = await updateApplicationStatus(app.id, 'Applied')
    expect(res.success).toBe(false)
    expect(res.error).toMatch(/already in/)
    expect(await prisma.status_history.count()).toBe(0)           // no spurious history row
})


// --- getKPIs: every status arm + the active arithmetic --------------------

test('getKPIs aggregates all status buckets and the 60-day active window', async () => {
    const today = new Date().toISOString().slice(0, 10)
    const statuses = ['Applied', 'Applied', 'Screening', 'Interviewing', 'Interviewing', 'Offer', 'Accepted', 'Rejected', 'Withdrew']
    for (const s of statuses) await prisma.applications.create({ data: makeApplication({ status: s, date_applied: today }) })
    // Applied long ago and silent since (an import stamps last_updated=now): not Active.
    await prisma.applications.create({ data: makeApplication({ status: 'Applied', date_applied: '2020-01-01', last_updated: new Date().toISOString() }) })
    // Applied long ago, but a recent status change: Active.
    const moved = await prisma.applications.create({ data: makeApplication({ status: 'Screening', date_applied: '2020-01-01' }) })
    await prisma.status_history.create({ data: { application_id: moved.id, status: 'Screening', timestamp: new Date().toISOString() } })

    const k = await getKPIs()
    expect(k.total).toBe(11)
    expect(k.screening).toBe(2)
    expect(k.interviewing).toBe(2)
    expect(k.rejected).toBe(1)
    expect(k.offer).toBe(2)               // Offer + Accepted
    expect(k.active).toBe(6)              // 2 Applied + 2 Screening + 2 Interviewing
})


// --- getApplications: pagination skip-math + ordering ----------------------

test('getApplications paginates (skip = page*size) and orders by date desc', async () => {
    for (let i = 0; i < 25; i++) {
        await prisma.applications.create({
            data: makeApplication({
                company_name: `C${i}`,
                date_applied: `2026-01-${String(i + 1).padStart(2, '0')}`,
            }),
        })
    }
    const p0 = await getApplications({ page: 0, size: 10 })
    expect(p0.total).toBe(25)
    expect(p0.data).toHaveLength(10)
    expect(p0.data[0].date_applied).toBe('2026-01-25')   // newest first
    const p2 = await getApplications({ page: 2, size: 10 })
    expect(p2.data).toHaveLength(5)                       // skip 20 -> 5 remain
    expect(p2.data[0].date_applied).toBe('2026-01-05')
})

test('getApplications sorts by company or status on request, and ignores an unknown key', async () => {
    for (const [c, st] of [['Beta', 'Rejected'], ['Acme', 'Screening'], ['Cora', 'Applied']]) {
        await prisma.applications.create({ data: makeApplication({ company_name: c, status: st }) })
    }
    const names = async (q: any) => (await getApplications({ page: 0, size: 10, ...q })).data.map((a) => a.company_name)
    expect(await names({ sort: 'company', dir: 'asc' })).toEqual(['Acme', 'Beta', 'Cora'])
    expect(await names({ sort: 'status', dir: 'desc' })).toEqual(['Acme', 'Beta', 'Cora'])
    expect(await names({ sort: 'id; DROP', dir: 'asc' })).toHaveLength(3)
})


// --- getJobPostings: ordering and paging (the funnel stages: jev-status-parity.int) --

test('getJobPostings returns created_at and posted_at for each row', async () => {
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'dt', created_at: '2026-06-03T00:00:00.000Z', posted_at: '2026-06-01' }) })
    const { data } = await getJobPostings({ stage: 'all' })
    expect(data[0].created_at).toBe('2026-06-03T00:00:00.000Z')
    expect(data[0].posted_at).toBe('2026-06-01')
})

test('getJobPostings paginates', async () => {
    for (let i = 0; i < 7; i++) {
        await prisma.job_postings.create({ data: makeJobPosting({ external_id: `p${i}` }) })
    }
    const p0 = await getJobPostings({ stage: 'all', page: 0, size: 5 })
    expect(p0.data).toHaveLength(5)
    expect(p0.total).toBe(7)
    const p1 = await getJobPostings({ stage: 'all', page: 1, size: 5 })
    expect(p1.data).toHaveLength(2)                       // skip 5 -> 2 remain
})

test('getJobPostings sorts newest posted only', async () => {
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'old', posted_at: '2026-01-01', created_at: '2026-06-02T00:00:00.000Z' }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'new', posted_at: '2026-06-01', created_at: '2026-06-01T00:00:00.000Z' }) })
    expect((await getJobPostings({ stage: 'all' })).data.map((d) => d.external_id)).toEqual(['new', 'old'])
    await expect(getJobPostings({ stage: 'all', sort: 'created' } as any)).rejects.toThrow('Unsupported job sort')
})

test('the (source, external_id) unique constraint is enforced', async () => {
    await prisma.job_postings.create({ data: makeJobPosting({ source: 'greenhouse', external_id: 'u1' }) })
    await expect(
        prisma.job_postings.create({ data: makeJobPosting({ source: 'greenhouse', external_id: 'u1' }) })
    ).rejects.toThrow()
})


// --- deleteApplication: FK cascade + SetNull ------------------------------

test('deleteApplication cascades status_history and nulls the posting back-link', async () => {
    const app = await prisma.applications.create({ data: makeApplication() })
    await prisma.status_history.create({ data: makeStatusHistory({ application_id: app.id }) })
    const jp = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'd1', application_id: app.id, pipeline_status: 'applied' }),
    })

    await deleteApplication(app.id)
    expect(await prisma.status_history.count()).toBe(0)            // ON DELETE CASCADE
    const after = await prisma.job_postings.findUnique({ where: { id: jp.id } })
    expect(after!.application_id).toBeNull()                       // ON DELETE SET NULL
})


// --- deleteHistoryItem: status reverts to the most recent remaining -------

test('deleteHistoryItem reverts status to the latest remaining (or Applied)', async () => {
    const app = await prisma.applications.create({ data: makeApplication({ status: 'Interviewing' }) })
    const h1 = await prisma.status_history.create({
        data: makeStatusHistory({ application_id: app.id, status: 'Screening', timestamp: '2026-01-02T12:00:00.000Z' }),
    })
    const h2 = await prisma.status_history.create({
        data: makeStatusHistory({ application_id: app.id, status: 'Interviewing', timestamp: '2026-01-03T12:00:00.000Z' }),
    })

    await deleteHistoryItem(h2.id)   // remove the latest -> revert to h1's status
    expect((await prisma.applications.findUnique({ where: { id: app.id } }))!.status).toBe('Screening')
    await deleteHistoryItem(h1.id)   // none left -> fall back to 'Applied'
    expect((await prisma.applications.findUnique({ where: { id: app.id } }))!.status).toBe('Applied')
})

test('deleteHistoryItem atomically deletes and recomputes status', async () => {
    const app = await prisma.applications.create({ data: makeApplication({ status: 'Offer' }) })
    await prisma.status_history.create({ data: makeStatusHistory({ application_id: app.id, status: 'Interviewing', timestamp: '2026-01-01' }) })
    const h2 = await prisma.status_history.create({ data: makeStatusHistory({ application_id: app.id, status: 'Offer', timestamp: '2026-02-01' }) })
    const res = await deleteHistoryItem(h2.id)
    expect(res.success).toBe(true)
    const after = await prisma.applications.findUnique({ where: { id: app.id } })
    expect(after!.status).toBe('Interviewing') // recomputed from remaining latest
})


// --- CSV round-trip: escaping + dedup + invalid-status + missing-field -----

test('importApplicationsCSV handles escaping/dedup/invalid rows; export round-trips', async () => {
    const csv = [
        'company_name,job_title,date_applied,status,notes',
        'Acme,"Engineer, Senior",2026-01-01,Phone Screen,"line1\nline2"',
        'Acme,"Engineer, Senior",2026-01-01,Offer,dup',   // duplicate -> skipped
        'Beta,Dev,2026-01-02,Nonsense,ok',                // invalid status -> coerced to Applied
        ',NoCompany,2026-01-03,Applied,bad',              // missing company -> error
    ].join('\n')

    const imp = await importApplicationsCSV(csv)
    expect(imp.success).toBe(true)
    expect(imp.added).toBe(2)
    expect(imp.skipped).toBe(1)
    expect(imp.errors).toHaveLength(1)

    const beta = await prisma.applications.findFirst({ where: { company_name: 'Beta' } })
    expect(beta!.status).toBe('Applied')   // invalid status coerced
    const acme = await prisma.applications.findFirst({ where: { company_name: 'Acme' } })
    expect(acme!.status).toBe('Screening') // pre-#205 'Phone Screen' mapped

    const exp = await exportApplicationsCSV()
    expect(exp.success).toBe(true)
    expect(exp.csv).toContain('"Engineer, Senior"')   // comma-bearing field re-quoted
    expect(exp.csv).toContain('"line1\nline2"')        // embedded newline preserved
})

test('importApplicationsCSV is atomic and dedupes on (company,title)', async () => {
    await prisma.applications.create({ data: makeApplication({ company_name: 'Acme', job_title: 'Eng' }) })
    const csv = 'company_name,job_title,date_applied\nAcme,Eng,2026-01-01\nBeta,DS,2026-01-02\n'
    const res = await importApplicationsCSV(csv)
    expect(res.success).toBe(true)
    expect(res).toMatchObject({ added: 1, skipped: 1 })
    expect(await prisma.applications.count()).toBe(2)
})

test('importApplicationsCSV reverses the export formula-guard and dedupes', async () => {
    await prisma.applications.create({ data: makeApplication({
        company_name: '+Simple',
        job_title: 'Eng',
        date_applied: '2026-01-01',
    }) })

    const exp = await exportApplicationsCSV()
    expect(exp.success).toBe(true)
    expect(exp.csv).toContain(`'+Simple`)   // export applied the formula-guard

    const imp = await importApplicationsCSV(exp.csv!)
    expect(imp.success).toBe(true)
    expect(imp.added).toBe(0)
    expect(imp.skipped).toBe(1)   // dedupe matched the original row -> skipped, not duplicated

    const apps = await prisma.applications.findMany({ where: { company_name: '+Simple' } })
    expect(apps).toHaveLength(1)   // exactly one row; no `'+Simple` duplicate
})

test('importApplicationsCSV round-trips a value that itself starts with an apostrophe', async () => {
    await prisma.applications.create({ data: makeApplication({
        company_name: "'+1 Talent",
        job_title: 'Eng',
        date_applied: '2026-01-01',
    }) })

    const exp = await exportApplicationsCSV()
    expect(exp.success).toBe(true)
    expect(exp.csv).toContain(`''+1 Talent`)   // export doubled the guard: raw "'+1 Talent" -> "''+1 Talent"

    const imp = await importApplicationsCSV(exp.csv!)
    expect(imp.success).toBe(true)
    expect(imp.added).toBe(0)
    expect(imp.skipped).toBe(1)   // dedupe matched the original row -> not duplicated, apostrophe not dropped

    const apps = await prisma.applications.findMany({ where: { company_name: "'+1 Talent" } })
    expect(apps).toHaveLength(1)
    expect(apps[0].company_name).toBe("'+1 Talent")   // leading apostrophe preserved exactly
})

test('importApplicationsCSV handles a >100-row import spanning two chunk transactions', async () => {
    const total = 105
    const DUP_ROW_A = 99    // last row of chunk 1 (0-based data-row index) -> CSV row 101
    const DUP_ROW_B = 101   // second row of chunk 2 -> CSV row 103, shares company+title with A
    const INVALID_ROW = 103 // fourth row of chunk 2 -> CSV row 105, past the 100-row boundary

    const lines = ['company_name,job_title,date_applied,status,notes']
    for (let i = 0; i < total; i++) {
        if (i === DUP_ROW_A || i === DUP_ROW_B) {
            lines.push('DupCo,DupRole,2026-01-01,Applied,dup-pair')
        } else if (i === INVALID_ROW) {
            lines.push(',NoCompany,2026-01-03,Applied,bad')   // missing company -> error
        } else {
            lines.push(`Company${i},Role${i},2026-01-01,Applied,filler`)
        }
    }
    const csv = lines.join('\n')

    const imp = await importApplicationsCSV(csv)
    expect(imp.success).toBe(true)
    expect(imp.added).toBe(total - 2)      // everything except the dup (skipped) and the invalid row (error)
    expect(imp.skipped).toBe(1)            // DUP_ROW_B, matched against chunk 1's already-committed DUP_ROW_A
    expect(imp.errors).toEqual(['Row 105: missing required field'])   // original row number, not batch-relative

    const dups = await prisma.applications.findMany({ where: { company_name: 'DupCo', job_title: 'DupRole' } })
    expect(dups).toHaveLength(1)   // proves chunk 2's findFirst sees chunk 1's committed row, not a duplicate
})

test('exportApplicationsCSV neutralizes formula-injection cells', async () => {
    await prisma.applications.create({ data: makeApplication({
        company_name: '=1+2',
        job_title: 'x',
        date_applied: '2026-01-01',
        category: 'Others',
        status: 'Applied',
        application_url: '',
        notes: '@SUM(A1)',
        last_updated: '2026-01-01T00:00:00.000Z',
    }) })
    const exp = await exportApplicationsCSV()
    expect(exp.csv).toContain(`'=1+2`)
    expect(exp.csv).toContain(`'@SUM(A1)`)
})


// --- bulkRemove / bulkReopen / removeAllInView ----------------------------

test('getCandidateProfile returns the row and counts only eligible postings from the last 7 days', async () => {
    expect(await getCandidateProfile()).toEqual({ profile: null, reassessOnChange: 0 })
    await prisma.candidate_profile.create({ data: { id: 1, locations: '["remote"]', actor: 'config', updated_at: 'x',
        custom_packs: '{"preference_pack":"private","yoe_pack":"private"}' } })
    const day = (ago: number) => new Date(Date.now() - ago * 86_400_000).toISOString().slice(0, 10)
    const rows: [string, string, string][] = [
        [day(1), 'new', '{"disqualified":false}'],   // counted
        [day(9), 'new', '{"disqualified":false}'],   // too old
        [day(1), 'new', '{"disqualified":true}'],    // discarded by the screen
        [day(1), 'applied', '{"disqualified":false}'], // not new
    ]
    for (const [i, [posted_at, pipeline_status, result_json]] of rows.entries()) {
        const p = await prisma.job_postings.create({ data: makeJobPosting({ external_id: `set-${i}`, posted_at, pipeline_status }) })
        await prisma.job_screenings.create({ data: { job_posting_id: p.id, state: 'complete', result_json, backend: 'ollama',
            evaluator_version: 'screen-v1', last_attempted_at: 'x', created_at: 'x' } })
    }
    const s = await getCandidateProfile()
    expect(s.profile).toMatchObject({ locations: ['remote'], packs: 'custom', version: 1, actor: 'config', triage_configured: false })
    expect(JSON.stringify(s.profile)).not.toContain('private')   // pack texts stay out of the read
    expect(s.reassessOnChange).toBe(1)
})
