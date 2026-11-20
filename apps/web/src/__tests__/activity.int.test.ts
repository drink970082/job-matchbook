import { getActivityStatus, getActivityTimeline } from '@/lib/activity-actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeJobPosting } from '@/test-utils/factories'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

test('one timeline: applications, status changes and audited changes, newest first, in plain English', async () => {
    const a1 = await prisma.applications.create({ data: makeApplication({ company_name: 'Old', job_title: 'Eng', date_applied: '2026-11-01', actor: 'web' }) })
    await prisma.applications.create({ data: makeApplication({ company_name: 'New', job_title: 'Eng', date_applied: '2026-11-15', actor: 'mcp' }) })
    await prisma.status_history.create({ data: { application_id: a1.id, status: 'Applied', timestamp: '2026-11-01', actor: 'web' } })
    await prisma.status_history.create({ data: { application_id: a1.id, status: 'Interviewing', timestamp: '2026-11-10T12:00:00.000Z', actor: 'mcp' } })
    const job = await prisma.job_postings.create({ data: makeJobPosting({ company_name: 'Acme', job_title: 'Data Engineer' }) })
    const audit = (at: string, entity: string, action: string, entity_id: number, payload: unknown) => prisma.audit_log.create({ data: {
        at, actor: 'web', action, entity, entity_id, payload: typeof payload === 'string' ? payload : JSON.stringify(payload) } })
    await audit('2026-11-19T01:00:00Z', 'watched_companies', 'add', 1, { name: 'Stripe', source: 'greenhouse', slug: 'stripe' })
    await audit('2026-11-19T02:00:00Z', 'job_triage_overrides', 'add', job.id, { job_posting_id: job.id, decision: 'skip' })
    await audit('2026-11-19T03:00:00Z', 'candidate_preferences', 'update', 1, { before: {}, after: { version: 3 } })
    await audit('2026-11-19T04:00:00Z', 'odd', 'add', 1, 'not json')

    const { items, hasMore } = await getActivityTimeline()
    expect(items.map((i) => i.text)).toEqual([
        'add odd', 'Updated hard requirements', 'Hid Acme - Data Engineer', 'Added board Stripe',
        'Applied to New - Eng', 'Old - Eng -> Interviewing', 'Applied to Old - Eng',
    ])
    expect(hasMore).toBe(false)
    const page = await getActivityTimeline(2, 3)
    expect([page.items.map((i) => i.text), page.hasMore]).toEqual([['Hid Acme - Data Engineer', 'Added board Stripe', 'Applied to New - Eng'], true])
})

test('the status strip counts postings, JEV work, failures and spend', async () => {
    const now = new Date().toISOString()
    const p1 = await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'a', created_at: now }) })
    const p2 = await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'b', created_at: '2026-01-01T00:00:00.000Z' }) })
    const jev = (id: number, state: string, cost: string | null) => prisma.job_jev_assessments.create({ data: {
        job_posting_id: id, state, cost_usd: cost, policy_sha256: 'p', last_attempted_at: now, created_at: now } })
    await jev(p1.id, 'complete', '0.0003')
    await jev(p2.id, 'provider_error', '0.0001')
    expect(await getActivityStatus()).toEqual({ lastFetchedAt: now, new24h: 1, new7d: 1, assessed24h: 1, failures24h: 1, spend7dUsd: 0.0004 })
})
