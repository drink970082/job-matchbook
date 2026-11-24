/**
 * The web's effective status and funnel stage (lib/job-actions.ts) against the cases the
 * worker's MCP test reads too (apps/worker/tests/fixtures/effective-status-cases.json):
 * a change to either side's rule fails one of the suites.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { getJobPostings, getJobsMode, getNewJobsCount, markJobApplied, setTriageOverride } from '@/lib/job-actions'
import { JOB_STAGES } from '@/lib/job-stages'
import { prisma, resetDb } from '@/test-utils/db'
import { makeJobPosting } from '@/test-utils/factories'

type Case = {
    name: string; pipeline_status: string; source_state: string; verdict: string
    override: string | null; status: string; stage: string; listed: boolean
}
const CASES: Case[] = JSON.parse(readFileSync(
    path.join(__dirname, '../../../worker/tests/fixtures/effective-status-cases.json'), 'utf8')).cases

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

async function posting(over: Record<string, unknown>) {
    return prisma.job_postings.create({ data: makeJobPosting({ pipeline_status: 'new', source_content_revision: 2, ...over }) })
}

async function seedCases() {
    for (const c of CASES) {
        const p = await posting({ external_id: c.name, pipeline_status: c.pipeline_status, source_state: c.source_state, verdict: c.verdict })
        if (c.override) {
            await prisma.job_triage_overrides.create({ data: { job_posting_id: p.id, decision: c.override,
                actor: 'mcp', source_content_revision: 1, created_at: 'x' } })
        }
    }
}

const names = (cases: Case[]) => cases.map((c) => c.name).sort()
const ids = (rows: any[]) => rows.map((j) => j.external_id).sort()

test('every row reports the shared effective status and stage', async () => {
    await seedCases()
    const { data, total } = await getJobPostings({ stage: 'all', size: 100 })
    expect(total).toBe(CASES.length)
    const byName = Object.fromEntries(data.map((j: any) => [j.external_id, j]))
    for (const c of CASES) {
        expect([c.name, byName[c.name].status, byName[c.name].stage, byName[c.name].verdict])
            .toEqual([c.name, c.status, c.stage, c.verdict])
    }
})

test('each stage lists exactly its shared cases; postings for you is the keep stage', async () => {
    await seedCases()
    for (const stage of JOB_STAGES) {
        const { data, total } = await getJobPostings({ stage, size: 100 })
        const expected = names(CASES.filter((c) => c.stage === stage))
        expect([stage, ids(data)]).toEqual([stage, expected])
        expect(total).toBe(expected.length)
    }
    const forYou = (await getJobPostings({ size: 100 })).data
    expect(ids(forYou)).toEqual(names(CASES.filter((c) => c.stage === 'keep')))
    expect(ids(forYou)).toContain('discarded rescued by keep')
})

test('a requirements discard rescued by keep enters postings for you and the badge', async () => {
    const today = new Date().toISOString()
    const p = await posting({ external_id: 'gone', verdict: 'discarded', created_at: today })
    expect((await getJobPostings({})).data).toEqual([])
    expect(await getNewJobsCount()).toBe(0)
    expect((await setTriageOverride(p.id, 'keep', 'wrong discard')).success).toBe(true)
    // Content changes after the override do not void it.
    await prisma.job_postings.update({ where: { id: p.id }, data: { source_content_revision: 3 } })
    const { data } = await getJobPostings({})
    expect(ids(data)).toEqual(['gone'])
    expect(data[0].jev.override).toMatchObject({ decision: 'keep', reason: 'wrong discard', actor: 'web' })
    expect(await getNewJobsCount()).toBe(1)
    // Not interested hides it again.
    await setTriageOverride(p.id, 'skip', 'Not interested (web)')
    expect((await getJobPostings({})).data).toEqual([])
})

test('each row shows the profile version its verdict was judged under', async () => {
    const triaged = await posting({ external_id: 'triaged', verdict: 'keep' })
    const discarded = await posting({ external_id: 'discarded', verdict: 'discarded' })
    await posting({ external_id: 'waiting' })
    for (const id of [triaged.id, discarded.id]) {
        await prisma.job_screenings.create({ data: { job_posting_id: id, state: 'complete', result_json: '{}',
            backend: 'ollama', evaluator_version: 'v', last_attempted_at: 'x', created_at: 'x', profile_version: 2 } })
    }
    await prisma.job_jev_assessments.create({ data: { job_posting_id: triaged.id, state: 'complete', verdict: 'keep',
        reasons_json: '["role_match"]', profile_version: 3, last_attempted_at: 'x', created_at: 'x' } })
    const { data } = await getJobPostings({ stage: 'all' })
    const byName = Object.fromEntries(data.map((j: any) => [j.external_id, j]))
    expect([byName.triaged.profile_version, byName.discarded.profile_version, byName.waiting.profile_version])
        .toEqual([3, 2, null])
    expect(byName.triaged.jev.reasons).toEqual(['role_match'])
})

test('mark applied is limited to the view that offered it', async () => {
    const p = await posting({ external_id: 'waiting' })
    expect(await markJobApplied(p.id, 'SWE', { stage: 'keep' })).toEqual({ success: false, error: 'Job is outside the requested view and filters' })
    const ok = await markJobApplied(p.id, 'SWE', { stage: 'pending' })
    expect(ok.success).toBe(true)
    expect((await prisma.job_postings.findUniqueOrThrow({ where: { id: p.id } })).pipeline_status).toBe('applied')
})

test('the filter rejects retired stages and keys', async () => {
    await expect(getJobPostings({ bucket: 'matched' } as any)).rejects.toThrow('Unsupported job filter: bucket')
    await expect(getJobPostings({ sort: 'score' } as any)).rejects.toThrow('Unsupported job sort')
    for (const stage of ['matched', 'jev_skip', 'unassessed', 'screen_rejected', 'rule_rejected']) {
        await expect(getJobPostings({ stage } as any)).rejects.toThrow('Unsupported job stage')
    }
})

test('the mode line follows whether triage is configured in the profile', async () => {
    expect(await getJobsMode()).toBe('screen')
    await prisma.candidate_profile.create({ data: { id: 1, actor: 'config', updated_at: 'x' } })
    expect(await getJobsMode()).toBe('screen')
    await prisma.candidate_profile.update({ where: { id: 1 }, data: { custom_triage_context: '{"profile_text":"{}","yoe_context":""}' } })
    expect(await getJobsMode()).toBe('jev')
    await prisma.candidate_profile.update({ where: { id: 1 }, data: { custom_triage_context: null, target_roles: '["Engineer"]' } })
    expect(await getJobsMode()).toBe('jev')
})
