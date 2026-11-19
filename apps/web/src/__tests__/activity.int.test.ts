import { getRecentActivity } from '@/lib/activity-actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication } from '@/test-utils/factories'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

test('recent activity lists applications, status changes and audited changes newest first, with actors', async () => {
    const a1 = await prisma.applications.create({ data: makeApplication({ company_name: 'Old', actor: 'web' }) })
    const a2 = await prisma.applications.create({ data: makeApplication({ company_name: 'New', actor: 'mcp' }) })
    await prisma.status_history.create({ data: { application_id: a1.id, status: 'Screening', timestamp: '2026-11-10', actor: 'mcp' } })
    await prisma.status_history.create({ data: { application_id: a2.id, status: 'Rejected', timestamp: '2026-11-12', actor: 'web' } })
    const audit = (entity: string, action: string, payload: unknown) => prisma.audit_log.create({ data: {
        at: '2026-11-19T00:00:00Z', actor: 'mcp', action, entity, entity_id: 1, payload: JSON.stringify(payload) } })
    await audit('watched_companies', 'add', { name: 'Acme', source: 'greenhouse', slug: 'acme' })
    await audit('job_triage_overrides', 'update', { before: {}, after: { job_posting_id: 7, decision: 'keep' } })
    await audit('candidate_preferences', 'update', { before: {}, after: { version: 3 } })
    await audit('jev_profile', 'update', { before: {}, after: { version: 2 } })
    await prisma.audit_log.create({ data: { at: 'x', actor: 'web', action: 'add', entity: 'odd', entity_id: 1, payload: 'not json' } })

    const r = await getRecentActivity()
    expect(r.applications.map((a) => [a.company_name, a.actor])).toEqual([['New', 'mcp'], ['Old', 'web']])
    expect(r.statusChanges.map((h) => [h.company_name, h.status, h.actor])).toEqual([['New', 'Rejected', 'web'], ['Old', 'Screening', 'mcp']])
    expect(r.changes.map((c) => c.label)).toEqual(['odd', 'JEV profile v2', 'hard requirements v3', 'job 7: keep', 'Acme (greenhouse/acme)'])
    expect((await getRecentActivity(2)).changes).toHaveLength(2)
})
