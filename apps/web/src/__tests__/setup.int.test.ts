import { getMcpTemplates, getSetupStatus } from '@/lib/setup-actions'
import { getNewJobsCount } from '@/lib/job-actions'
import { confirmCandidateProfile } from '@/lib/profile-actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeJobPosting, makeWatchedCompany } from '@/test-utils/factories'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

test('setup is complete once requirements, a board, a posting and the confirmation exist; AI client and triage are optional', async () => {
    expect(await getSetupStatus()).toEqual({ complete: false, intake: null,
        steps: { aiClient: false, requirements: false, sources: false, triage: false, first_fetch: false, confirmed: false } })
    expect(await confirmCandidateProfile()).toEqual({ success: false, error: 'Fill in the candidate profile first' })

    // A profile with only scope and preferences has no requirement to screen on (same rule
    // as MCP get_setup_status); target roles alone configure triage.
    await prisma.candidate_profile.create({ data: { id: 1, title_include: '["eng"]', target_roles: '["Backend"]', actor: 'web', updated_at: 'x' } })
    expect((await getSetupStatus()).steps).toMatchObject({ requirements: false, triage: true })
    // Confirming without a requirement would send every title-filter survivor to triage.
    expect(await confirmCandidateProfile()).toEqual({ success: false, error: 'Set at least one hard requirement first' })
    expect((await prisma.candidate_profile.findUnique({ where: { id: 1 } }))!.confirmed_at).toBeNull()
    await prisma.candidate_profile.update({ where: { id: 1 }, data: { education: '[{"degree":"phd","field":""}]', target_roles: '[]' } })
    expect((await getSetupStatus()).steps).toMatchObject({ requirements: true, triage: false })
    await prisma.candidate_profile.update({ where: { id: 1 }, data: { education: '[]', locations: '["Canada"]' } })
    await prisma.watched_companies.create({ data: makeWatchedCompany() })
    await prisma.job_postings.create({ data: makeJobPosting() })
    // Fetched but not confirmed (#227): the intake summary rides along for the review.
    const review = await getSetupStatus()
    expect(review).toMatchObject({ complete: false, steps: { first_fetch: true, confirmed: false } })
    expect(review.intake).toHaveProperty('last_7_days')

    expect(await confirmCandidateProfile()).toEqual({ success: true })
    const confirmedAt = (await prisma.candidate_profile.findUnique({ where: { id: 1 } }))!.confirmed_at
    expect(confirmedAt).toBeTruthy()
    expect(await confirmCandidateProfile()).toEqual({ success: true }) // a second click changes nothing
    expect((await prisma.candidate_profile.findUnique({ where: { id: 1 } }))!.confirmed_at).toBe(confirmedAt)
    expect(await prisma.audit_log.findMany({ where: { entity: 'candidate_profile', action: 'confirm' },
        select: { actor: true } })).toEqual([{ actor: 'web' }])
    expect(await getSetupStatus()).toEqual({ complete: true, intake: null,
        steps: { aiClient: false, requirements: true, sources: true, triage: false, first_fetch: true, confirmed: true } })

    // An mcp application row counts as a connected client even with no audit row.
    await prisma.applications.create({ data: makeApplication({ actor: 'mcp' }) })
    expect((await getSetupStatus()).steps.aiClient).toBe(true)
})

test('the Jobs badge counts only postings for you first fetched in the last 24h (JEV mode)', async () => {
    const now = Date.now()
    const keep = async (external_id: string, created_at: string) => {
        const p = await prisma.job_postings.create({ data: makeJobPosting({ external_id, created_at, pipeline_status: 'new', verdict: 'keep', source_content_revision: 1 }) })
        await prisma.job_jev_assessments.create({ data: { job_posting_id: p.id, state: 'complete', verdict: 'keep',
            reasons_json: '[]', source_content_revision: 1, last_attempted_at: 'x', created_at: 'x' } })
    }
    await prisma.candidate_profile.create({ data: { id: 1, target_roles: '["Engineer"]', actor: 'config', updated_at: 'x' } })
    await keep('fresh', new Date(now - 3_600_000).toISOString())
    await keep('old', new Date(now - 2 * 86_400_000).toISOString())
    await prisma.job_postings.create({ data: makeJobPosting({ external_id: 'unassessed', pipeline_status: 'new', created_at: new Date(now).toISOString() }) })
    expect(await getNewJobsCount()).toBe(1)
})

test('the MCP templates load from the repo and carry no real key', async () => {
    const t = await getMcpTemplates()
    expect(t['claude-code.txt']).toContain('~/.config/ats-mcp/api-key')
    expect(JSON.parse(t['claude-desktop.json']).mcpServers.ats.env.ATS_API_KEY).toMatch(/^<paste/)
    for (const text of Object.values(t)) expect(text).not.toMatch(/ATS_API_KEY=[A-Za-z0-9]{16,}/)
})
