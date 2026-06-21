/**
 * Integration tests: server actions against a REAL throwaway SQLite (via the
 * shared PrismaClient pointed at the temp DB). These cover what the Prisma-mocked
 * unit tests can't — transaction atomicity/rollback, aggregation correctness,
 * pagination/ordering, the unique constraint, and FK cascade/SetNull.
 */
import {
    addApplication,
    deleteApplication,
    deleteHistoryItem,
    exportApplicationsCSV,
    getApplications,
    getJobPostings,
    getKPIs,
    importApplicationsCSV,
    markJobApplied,
    updateApplicationStatus,
} from '@/lib/actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeJobPosting, makeStatusHistory } from '@/test-utils/factories'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())


// --- markJobApplied: transaction atomicity --------------------------------

test('markJobApplied creates the application and links the posting', async () => {
    const jp = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'm1', company_name: 'Acme', job_title: 'Eng' }),
    })
    const res = await markJobApplied(jp.id, 'MLE')
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

    const res = await markJobApplied(jp.id)
    expect(res.success).toBe(false)
    expect(await prisma.applications.count()).toBe(before)        // no new app (rolled back)
    const after = await prisma.job_postings.findUnique({ where: { id: jp.id } })
    expect(after!.pipeline_status).toBe('scored')                 // posting untouched
    expect(after!.application_id).toBeNull()
})

test('markJobApplied returns not-found for a missing id', async () => {
    expect(await markJobApplied(99999)).toEqual({ success: false, error: 'Job posting not found' })
})


// --- updateApplicationStatus: guards + timezone-safe timestamp ------------

test('updateApplicationStatus transitions and records a noon-UTC history row', async () => {
    const app = await prisma.applications.create({ data: makeApplication({ status: 'Applied' }) })
    const res = await updateApplicationStatus(app.id, 'Phone Screen', '2026-05-10')
    expect(res.success).toBe(true)

    const updated = await prisma.applications.findUnique({ where: { id: app.id } })
    expect(updated!.status).toBe('Phone Screen')
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

test('getKPIs aggregates all status buckets and the active formula', async () => {
    const statuses = [
        'Applied', 'Applied', 'Online Assessment', 'Phone Screen',
        'Interviewing: 2nd round', 'Final Round', 'Offer', 'Accepted',
        'Rejected', 'Withdrew', 'Ghosted',
    ]
    for (const s of statuses) await prisma.applications.create({ data: makeApplication({ status: s }) })

    const k = await getKPIs()
    expect(k.applied).toBe(11)            // total
    expect(k.assessment).toBe(1)          // Online Assessment
    expect(k.interviewing).toBe(3)        // Phone Screen + Interviewing:2nd + Final Round
    expect(k.rejected).toBe(1)
    expect(k.offer).toBe(2)               // Offer + Accepted
    // active = total - rejected - offer - withdrew - ghosted = 11 - 1 - 2 - 1 - 1
    expect(k.active).toBe(6)
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


// --- getJobPostings: score-aware buckets + ordering + unique constraint ----

test('getJobPostings buckets postings by score and status', async () => {
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'm1', score: 90, pipeline_status: 'scored' }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'm2', score: 80, pipeline_status: 'notified' }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'lo', score: 60, pipeline_status: 'scored' }) })    // below threshold
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'dx', score: 95, pipeline_status: 'discarded' }) }) // explicit discard
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'fx', score: 88, pipeline_status: 'failed' }) })

    const matched = await getJobPostings({ bucket: 'matched' })
    expect(matched.data.map((d) => d.external_id)).toEqual(['m1', 'm2'])  // >=75, score desc

    // discarded = explicitly discarded OR live-but-below-threshold, score desc
    const discarded = await getJobPostings({ bucket: 'discarded' })
    expect(discarded.data.map((d) => d.external_id)).toEqual(['dx', 'lo'])

    const failed = await getJobPostings({ bucket: 'failed' })
    expect(failed.data.map((d) => d.external_id)).toEqual(['fx'])
})

test('getJobPostings paginates', async () => {
    for (let i = 0; i < 7; i++) {
        await prisma.job_postings.create({ data: makeJobPosting({ external_id: `p${i}`, score: 90 - i, pipeline_status: 'scored' }) })
    }
    const p0 = await getJobPostings({ bucket: 'matched', page: 0, size: 5 })
    expect(p0.data).toHaveLength(5)
    expect(p0.total).toBe(7)
    const p1 = await getJobPostings({ bucket: 'matched', page: 1, size: 5 })
    expect(p1.data).toHaveLength(2)                       // skip 5 -> 2 remain
})

test('getJobPostings discardType narrows the discarded bucket', async () => {
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'dq', score: 90, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'on-site' }) }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'lo', score: 50, pipeline_status: 'scored' }) })             // below threshold
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'man', score: 88, pipeline_status: 'discarded', score_detail: null }) }) // manual discard (not disqualified)

    const dq = await getJobPostings({ bucket: 'discarded', discardType: 'disqualified' })
    expect(dq.data.map((d) => d.external_id)).toEqual(['dq'])

    const lo = await getJobPostings({ bucket: 'discarded', discardType: 'lowscore' })
    expect(lo.data.map((d) => d.external_id)).toEqual(['lo'])

    const all = await getJobPostings({ bucket: 'discarded' })
    expect(all.data.map((d) => d.external_id).sort()).toEqual(['dq', 'lo', 'man'])
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
    const app = await prisma.applications.create({ data: makeApplication({ status: 'Phone Screen' }) })
    const h1 = await prisma.status_history.create({
        data: makeStatusHistory({ application_id: app.id, status: 'Online Assessment', timestamp: '2026-01-02T12:00:00.000Z' }),
    })
    const h2 = await prisma.status_history.create({
        data: makeStatusHistory({ application_id: app.id, status: 'Phone Screen', timestamp: '2026-01-03T12:00:00.000Z' }),
    })

    await deleteHistoryItem(h2.id)   // remove the latest -> revert to h1's status
    expect((await prisma.applications.findUnique({ where: { id: app.id } }))!.status).toBe('Online Assessment')
    await deleteHistoryItem(h1.id)   // none left -> fall back to 'Applied'
    expect((await prisma.applications.findUnique({ where: { id: app.id } }))!.status).toBe('Applied')
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

    const exp = await exportApplicationsCSV()
    expect(exp.success).toBe(true)
    expect(exp.csv).toContain('"Engineer, Senior"')   // comma-bearing field re-quoted
    expect(exp.csv).toContain('"line1\nline2"')        // embedded newline preserved
})
