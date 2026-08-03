/**
 * Integration tests: server actions against a REAL throwaway SQLite (via the
 * shared PrismaClient pointed at the temp DB). These cover what the Prisma-mocked
 * unit tests can't — transaction atomicity/rollback, aggregation correctness,
 * pagination/ordering, the unique constraint, and FK cascade/SetNull.
 */
import {
    addApplication,
    bulkRemove,
    bulkReopen,
    deleteApplication,
    deleteHistoryItem,
    exportApplicationsCSV,
    getApplications,
    getJobPostings,
    getCategories,
    getKPIs,
    importApplicationsCSV,
    markJobApplied,
    removeAllInView,
    setCategories,
    updateApplicationStatus,
} from '@/lib/actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeJobPosting, makeStatusHistory } from '@/test-utils/factories'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

// The `matched` bucket keys on the fit verdicts (seniority=match AND domain=match),
// the SAME predicate the worker's notify gate uses — NOT on score. Seed this into
// score_detail for any row a test expects to land in `matched`.
const MATCH_VERDICT = JSON.stringify({
    assessment: { seniority: { verdict: 'match' }, domain: { verdict: 'match' } },
})

// `belowbar` is the NEAR MISS — seniority=match with domain=adjacent. Anything else
// scored (a seniority miss, or domain=mismatch) is a fit-verdict reject and belongs in
// the Discarded audit view alongside the hard-constraint screen failures.
const ADJACENT_VERDICT = JSON.stringify({
    assessment: { seniority: { verdict: 'match' }, domain: { verdict: 'adjacent' } },
})
const TOO_JUNIOR_VERDICT = JSON.stringify({
    assessment: { seniority: { verdict: 'too_junior' }, domain: { verdict: 'match' } },
})


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


// --- addApplication: transaction atomicity ---------------------------------

test('addApplication rejects a duplicate (company,title) atomically', async () => {
    const first = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-01-01' })
    expect(first.success).toBe(true)
    const dup = await addApplication({ company_name: 'Acme', job_title: 'Eng', date_applied: '2026-02-01' })
    expect(dup.success).toBe(false)
    expect(dup.error).toContain('already exists')
    expect(await prisma.applications.count()).toBe(1)
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
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'm1', score: 90, pipeline_status: 'scored', score_detail: MATCH_VERDICT }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'm2', score: 80, pipeline_status: 'notified', score_detail: MATCH_VERDICT }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'adj', score: 60, pipeline_status: 'scored', score_detail: ADJACENT_VERDICT }) })   // near miss
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'jr', score: 70, pipeline_status: 'scored', score_detail: TOO_JUNIOR_VERDICT }) })  // seniority reject
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'lo', score: 65, pipeline_status: 'scored' }) })    // no verdicts at all -> reject
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'dq', score: 95, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'location: onsite London, UK' }) }) }) // disqualified
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'fx', score: 88, pipeline_status: 'failed' }) })

    const matched = await getJobPostings({ bucket: 'matched' })
    expect(matched.data.map((d) => d.external_id)).toEqual(['m1', 'm2'])  // match/match verdicts, score desc

    // belowbar = the near miss ONLY: seniority=match AND domain=adjacent
    const belowbar = await getJobPostings({ bucket: 'belowbar' })
    expect(belowbar.data.map((d) => d.external_id)).toEqual(['adj'])

    // discarded = hard-constraint failures AND fit-verdict rejects (score desc)
    const discarded = await getJobPostings({ bucket: 'discarded' })
    expect(discarded.data.map((d) => d.external_id)).toEqual(['dq', 'jr', 'lo'])

    const failed = await getJobPostings({ bucket: 'failed' })
    expect(failed.data.map((d) => d.external_id)).toEqual(['fx'])
})

test('getJobPostings returns created_at and posted_at for each row', async () => {
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'dt', score: 90, pipeline_status: 'scored', score_detail: MATCH_VERDICT, created_at: '2026-06-03T00:00:00.000Z', posted_at: '2026-06-01' }) })
    const { data } = await getJobPostings({ bucket: 'matched' })
    expect(data[0].created_at).toBe('2026-06-03T00:00:00.000Z')
    expect(data[0].posted_at).toBe('2026-06-01')
})

test('getJobPostings paginates', async () => {
    for (let i = 0; i < 7; i++) {
        await prisma.job_postings.create({ data: makeJobPosting({ external_id: `p${i}`, score: 90 - i, pipeline_status: 'scored', score_detail: MATCH_VERDICT }) })
    }
    const p0 = await getJobPostings({ bucket: 'matched', page: 0, size: 5 })
    expect(p0.data).toHaveLength(5)
    expect(p0.total).toBe(7)
    const p1 = await getJobPostings({ bucket: 'matched', page: 1, size: 5 })
    expect(p1.data).toHaveLength(2)                       // skip 5 -> 2 remain
})

test('getJobPostings cause sub-filter narrows the discarded bucket by disqualification reason', async () => {
    // The worker keys disqualification_reason like "degree: …" / "internship/co-op role"
    // (multiple joined by "; "); the cause filter matches those via json_extract + LIKE.
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'auth', score: 90, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'authorization: no visa sponsorship offered' }) }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'loc', score: 90, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'location: onsite London, UK' }) }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'deg', score: 90, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'degree: requires phd' }) }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'clr', score: 90, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'clearance: requires security clearance' }) }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'int', score: 90, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'internship/co-op role' }) }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'multi', score: 90, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'degree: requires phd; internship/co-op role' }) }) })
    // The prefilter cause covers BOTH strings the worker writes — run_score's phase-0
    // sweep and the operator's 2026-07-29 bulk sweep — which differ after the prefix.
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'pre1', score: 90, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'prefilter: title refused by the current filters' }) }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'pre2', score: 90, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'prefilter: refused by the current title/age filters' }) }) })

    const auth = await getJobPostings({ bucket: 'discarded', cause: 'authorization' })
    expect(auth.data.map((d) => d.external_id)).toEqual(['auth'])

    const loc = await getJobPostings({ bucket: 'discarded', cause: 'location' })
    expect(loc.data.map((d) => d.external_id)).toEqual(['loc'])

    const clr = await getJobPostings({ bucket: 'discarded', cause: 'clearance' })
    expect(clr.data.map((d) => d.external_id)).toEqual(['clr'])

    // A cause matches even inside a "; "-joined multi-cause reason.
    const deg = await getJobPostings({ bucket: 'discarded', cause: 'degree' })
    expect(deg.data.map((d) => d.external_id).sort()).toEqual(['deg', 'multi'])

    const int = await getJobPostings({ bucket: 'discarded', cause: 'internship' })
    expect(int.data.map((d) => d.external_id).sort()).toEqual(['int', 'multi'])

    // One pattern, both prefilter spellings — this is what makes the ~1,300-row sweep
    // population selectable, and so bulk-removable, in the Discarded bucket.
    const pre = await getJobPostings({ bucket: 'discarded', cause: 'prefilter' })
    expect(pre.data.map((d) => d.external_id).sort()).toEqual(['pre1', 'pre2'])

    // ...and it does NOT bleed into the hard-constraint causes.
    expect(deg.data.map((d) => d.external_id)).not.toContain('pre1')

    // No cause = every disqualified row.
    const all = await getJobPostings({ bucket: 'discarded' })
    expect(all.data.map((d) => d.external_id).sort()).toEqual(['auth', 'clr', 'deg', 'int', 'loc', 'multi', 'pre1', 'pre2'])
})

test('getJobPostings routes every fit-verdict reject into discarded, near misses into belowbar', async () => {
    // The KEEP half needs seniority=match; the split is then on domain. Everything else
    // is a reject, whatever its score — a high-scoring too_junior row is still a reject.
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'near', score: 55, pipeline_status: 'scored', score_detail: ADJACENT_VERDICT }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'junior', score: 92, pipeline_status: 'scored', score_detail: TOO_JUNIOR_VERDICT }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'senior', score: 80, pipeline_status: 'notified', score_detail: JSON.stringify({ assessment: { seniority: { verdict: 'too_senior' }, domain: { verdict: 'match' } } }) }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'wrongdomain', score: 70, pipeline_status: 'scored', score_detail: JSON.stringify({ assessment: { seniority: { verdict: 'match' }, domain: { verdict: 'mismatch' } } }) }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'noverdicts', score: 60, pipeline_status: 'scored', score_detail: null }) })

    const belowbar = await getJobPostings({ bucket: 'belowbar' })
    expect(belowbar.data.map((d) => d.external_id)).toEqual(['near'])   // seniority match + adjacent only

    const discarded = await getJobPostings({ bucket: 'discarded' })
    expect(discarded.data.map((d) => d.external_id)).toEqual(['junior', 'senior', 'wrongdomain', 'noverdicts'])

    // Nothing scored is orphaned: every seeded row is in exactly one of the two.
    expect(belowbar.total + discarded.total).toBe(5)
})

test('getJobPostings isolates low-context (thin-JD) rows into their own bucket', async () => {
    // Thin JD + match/match verdicts: would land in `matched` if not for its thinness —
    // it's excluded from matched by the notIn-lowIds layering, NOT by lacking verdicts.
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'thin-hi', score: 90, pipeline_status: 'scored', description: 'Thin JD.', score_detail: MATCH_VERDICT }) })
    // Thin JD + below-threshold score: would land in the `discarded` view otherwise.
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'thin-lo', score: 65, pipeline_status: 'notified', description: 'Too short.' }) })
    // Normal (full-length) JD, matched verdicts: stays in `matched`.
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'full-hi', score: 88, pipeline_status: 'scored', score_detail: MATCH_VERDICT }) })
    // Thin JD but disqualified/discarded (not scored|notified): keeps its own bucket.
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'thin-dq', score: 90, pipeline_status: 'discarded', description: 'Nope.', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'on-site' }) }) })

    const low = await getJobPostings({ bucket: 'lowcontext' })
    expect(low.data.map((d) => d.external_id)).toEqual(['thin-hi', 'thin-lo'])   // score desc

    // Mutual exclusivity: the thin scored rows are pulled OUT of matched/discarded.
    const matched = await getJobPostings({ bucket: 'matched' })
    expect(matched.data.map((d) => d.external_id)).toEqual(['full-hi'])          // thin-hi excluded

    const discarded = await getJobPostings({ bucket: 'discarded' })             // disqualified only
    expect(discarded.data.map((d) => d.external_id)).toEqual(['thin-dq'])        // disqualified (not thin) stays; the thin below-bar row moved to Low-context
})

test('getJobPostings routes the scorer insufficient_context flag into low-context (case #2)', async () => {
    // Full-length JD that would land in `matched`, but the fit scorer flagged it too
    // boilerplate/truncated to trust — the persisted flag alone routes it to Low-context.
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'insuf', score: 90, pipeline_status: 'scored', score_detail: JSON.stringify({ insufficient_context: true }) }) })
    // Full JD, no flag, matched verdicts: stays in matched.
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'full', score: 88, pipeline_status: 'scored', score_detail: MATCH_VERDICT }) })

    const low = await getJobPostings({ bucket: 'lowcontext' })
    expect(low.data.map((d) => d.external_id)).toEqual(['insuf'])

    const matched = await getJobPostings({ bucket: 'matched' })
    expect(matched.data.map((d) => d.external_id)).toEqual(['full'])   // flagged row pulled OUT of matched
})

test('getJobPostings sort=posted orders by posted_at desc', async () => {
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'old', score: 80, pipeline_status: 'scored', score_detail: MATCH_VERDICT, posted_at: '2026-01-01' }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'new', score: 80, pipeline_status: 'scored', score_detail: MATCH_VERDICT, posted_at: '2026-06-01' }) })

    const byScore = await getJobPostings({ bucket: 'matched' })                  // default: score desc, id asc
    expect(byScore.data.map((d) => d.external_id)).toEqual(['old', 'new'])       // tie score -> id asc

    const byPosted = await getJobPostings({ bucket: 'matched', sort: 'posted' })
    expect(byPosted.data.map((d) => d.external_id)).toEqual(['new', 'old'])      // newest posted first
})

test('matched bucket keys on verdicts, not score', async () => {
    // High score but only an adjacent-domain verdict: NOT matched under verdict routing.
    await prisma.job_postings.create({
        data: makeJobPosting({
            external_id: 'high-adjacent',
            score: 90,
            pipeline_status: 'scored',
            score_detail: JSON.stringify({ assessment: { seniority: { verdict: 'match' }, domain: { verdict: 'adjacent' } } }),
        }),
    })
    // Lower score but a clean match/match verdict: IS matched.
    await prisma.job_postings.create({
        data: makeJobPosting({
            external_id: 'low-match',
            score: 60,
            pipeline_status: 'scored',
            score_detail: JSON.stringify({ assessment: { seniority: { verdict: 'match' }, domain: { verdict: 'match' } } }),
        }),
    })

    const matched = await getJobPostings({ bucket: 'matched' })
    expect(matched.data.map((d) => d.external_id)).toEqual(['low-match'])

    const belowbar = await getJobPostings({ bucket: 'belowbar' })
    expect(belowbar.data.map((d) => d.external_id)).toContain('high-adjacent')
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

test('deleteHistoryItem atomically deletes and recomputes status', async () => {
    const app = await prisma.applications.create({ data: makeApplication({ status: 'Offer' }) })
    await prisma.status_history.create({ data: makeStatusHistory({ application_id: app.id, status: 'Phone Screen', timestamp: '2026-01-01' }) })
    const h2 = await prisma.status_history.create({ data: makeStatusHistory({ application_id: app.id, status: 'Offer', timestamp: '2026-02-01' }) })
    const res = await deleteHistoryItem(h2.id)
    expect(res.success).toBe(true)
    const after = await prisma.applications.findUnique({ where: { id: app.id } })
    expect(after!.status).toBe('Phone Screen') // recomputed from remaining latest
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

test('bulkRemove hides rows from every bucket', async () => {
    const a = await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'b1', score: 90, pipeline_status: 'scored' }) })
    const b = await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'b2', score: 85, pipeline_status: 'notified' }) })
    const res = await bulkRemove([a.id, b.id])
    expect(res).toEqual({ success: true, count: 2 })
    expect((await getJobPostings({ bucket: 'matched' })).data).toHaveLength(0)
    expect((await prisma.job_postings.findUnique({ where: { id: a.id } }))!.pipeline_status).toBe('removed')
})

test('bulkReopen sends discarded rows back to scored', async () => {
    const a = await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'r1', score: 90, pipeline_status: 'discarded' }) })
    const res = await bulkReopen([a.id])
    expect(res).toEqual({ success: true, count: 1 })
    expect((await prisma.job_postings.findUnique({ where: { id: a.id } }))!.pipeline_status).toBe('scored')
})

test('removeAllInView removes only rows matching the discarded bucket + cause filter', async () => {
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'keep', score: 90, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'location: onsite London, UK' }) }) })
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'gone', score: 88, pipeline_status: 'discarded', score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'degree: requires phd' }) }) })
    const res = await removeAllInView({ bucket: 'discarded', cause: 'degree' })
    expect(res).toEqual({ success: true, count: 1 })
    // Only the degree-disqualified row is removed; the location one remains in the view.
    expect((await getJobPostings({ bucket: 'discarded' })).data.map((d) => d.external_id)).toEqual(['keep'])
    expect((await getJobPostings({ bucket: 'discarded', cause: 'degree' })).data).toHaveLength(0)
})
