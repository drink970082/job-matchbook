import { getMcpTemplates, getSetupStatus } from '@/lib/setup-actions'
import { getNewJobsCount } from '@/lib/job-actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeJobPosting, makeWatchedCompany } from '@/test-utils/factories'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

test('setup is complete once requirements, a board and a posting exist; AI client and JEV are optional', async () => {
    expect(await getSetupStatus()).toEqual({ complete: false,
        steps: { aiClient: false, requirements: false, sources: false, jev: false, firstFetch: false } })

    // An all-blank preferences row is not "configured" (same rule as MCP get_setup_status).
    await prisma.candidate_preferences.create({ data: { id: 1, actor: 'web', updated_at: 'x' } })
    expect((await getSetupStatus()).steps.requirements).toBe(false)
    await prisma.candidate_preferences.update({ where: { id: 1 }, data: { locations: '["Canada"]' } })
    await prisma.watched_companies.create({ data: makeWatchedCompany() })
    await prisma.job_postings.create({ data: makeJobPosting() })
    expect(await getSetupStatus()).toEqual({ complete: true,
        steps: { aiClient: false, requirements: true, sources: true, jev: false, firstFetch: true } })

    // An mcp application row counts as a connected client even with no audit row.
    await prisma.applications.create({ data: makeApplication({ actor: 'mcp' }) })
    expect((await getSetupStatus()).steps.aiClient).toBe(true)
})

test('the Jobs badge counts only postings for you first fetched in the last 24h (JEV mode)', async () => {
    const now = Date.now()
    const keep = async (external_id: string, created_at: string) => {
        const p = await prisma.job_postings.create({ data: makeJobPosting({ external_id, created_at, pipeline_status: 'new', source_content_revision: 1 }) })
        await prisma.job_jev_assessments.create({ data: { job_posting_id: p.id, state: 'complete', verdict: 'keep',
            reasons_json: '[]', policy_sha256: 'p', source_content_revision: 1, last_attempted_at: 'x', created_at: 'x' } })
    }
    await prisma.jev_profile.create({ data: { id: 1, profile_text: '{}', c_pack: '{}', yoe_pack: '{}', yoe_context: '',
        actor: 'config', updated_at: 'x' } })
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
