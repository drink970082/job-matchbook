/**
 * The web's effective JEV status (lib/job-actions.ts) against the cases the worker's MCP
 * test reads too (apps/worker/tests/fixtures/jev-status-cases.json), plus the funnel
 * stage each posting lands in. A change to either side's rule fails one of the suites.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { getJobPostings, markJobApplied } from '@/lib/job-actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeJobPosting } from '@/test-utils/factories'

type Case = {
    name: string
    posting_revision: number | null
    assessment: { state: string; verdict: string | null; policy_sha256: string; source_content_revision: number | null } | null
    override: { decision: string; source_content_revision: number | null } | null
    current_policy: string | null
    status: string
    model_status: string
}

const CASES: Case[] = JSON.parse(readFileSync(
    path.join(__dirname, '../../../worker/tests/fixtures/jev-status-cases.json'), 'utf8')).cases

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

const PASSED_SCREEN = '{"disqualified":false,"screen":{"location":{"pass":true}}}'

async function posting(over: Record<string, unknown>, screen: string | null = PASSED_SCREEN) {
    const p = await prisma.job_postings.create({ data: makeJobPosting({ pipeline_status: 'new', ...over }) })
    if (screen) {
        await prisma.job_screenings.create({ data: { job_posting_id: p.id, state: 'complete', result_json: screen,
            backend: 'ollama', evaluator_version: 'screen-v1', last_attempted_at: 'x', created_at: 'x' } })
    }
    return p
}

test.each(CASES.map((c) => [c.name, c] as const))('JEV status: %s', async (_name, c) => {
    const p = await posting({ source_content_revision: c.posting_revision })
    if (c.current_policy) await prisma.app_settings.create({ data: { key: 'jev_current_policy_sha256', value: c.current_policy } })
    if (c.assessment) {
        await prisma.job_jev_assessments.create({ data: { job_posting_id: p.id, ...c.assessment,
            last_attempted_at: 'x', created_at: 'x' } })
    }
    if (c.override) {
        await prisma.job_triage_overrides.create({ data: { job_posting_id: p.id, ...c.override, actor: 'mcp', created_at: 'x' } })
    }
    const { data } = await getJobPostings({ stage: 'all' })
    expect([data[0].jev.status, data[0].jev.model_status]).toEqual([c.status, c.model_status])
})

test('each posting lands in exactly one funnel stage', async () => {
    const verdict = (id: number, v: string) => prisma.job_jev_assessments.create({ data: {
        job_posting_id: id, state: 'complete', verdict: v, reasons_json: v === 'skip' ? '["preference_weak"]' : '[]',
        policy_sha256: 'p', source_content_revision: 1, last_attempted_at: 'x', created_at: 'x' } })
    const keep = await posting({ external_id: 'keep', source_content_revision: 1 })
    await verdict(keep.id, 'keep')
    const skip = await posting({ external_id: 'skip', source_content_revision: 1 })
    await verdict(skip.id, 'skip')
    await posting({ external_id: 'unassessed' })
    await posting({ external_id: 'screen', pipeline_status: 'discarded' },
        '{"disqualified":true,"screen":{"degree":{"pass":false,"note":"PhD"}}}')
    await posting({ external_id: 'applied', pipeline_status: 'applied' })
    await posting({ external_id: 'gone', pipeline_status: 'removed' })

    const ids = async (stage: any) => (await getJobPostings({ stage })).data.map((j: any) => j.external_id)
    expect(await ids('keep')).toEqual(['keep'])
    expect(await ids('jev_skip')).toEqual(['skip'])
    expect((await getJobPostings({ stage: 'jev_skip' })).data[0].jev.reasons).toEqual(['preference_weak'])
    expect(await ids('unassessed')).toEqual(['unassessed'])
    expect(await ids('screen_rejected')).toEqual(['screen'])
    expect(await ids('other')).toEqual(['applied'])
    expect((await ids('all')).sort()).toEqual(['applied', 'keep', 'screen', 'skip', 'unassessed'])
})

test('mark applied is limited to the view that offered it', async () => {
    const p = await posting({ external_id: 'unassessed' })
    expect(await markJobApplied(p.id, 'SWE', { stage: 'keep' })).toEqual({ success: false, error: 'Job is outside the requested view and filters' })
    const ok = await markJobApplied(p.id, 'SWE', { stage: 'unassessed' })
    expect(ok.success).toBe(true)
    expect((await prisma.job_postings.findUniqueOrThrow({ where: { id: p.id } })).pipeline_status).toBe('applied')
})

test('the filter rejects the retired bucket, score and cause keys', async () => {
    await expect(getJobPostings({ bucket: 'matched' } as any)).rejects.toThrow('Unsupported job filter: bucket')
    await expect(getJobPostings({ sort: 'score' } as any)).rejects.toThrow('Unsupported job sort')
    await expect(getJobPostings({ stage: 'matched' } as any)).rejects.toThrow('Unsupported job stage')
})

// #207: the default Discovered Jobs view, and the Jobs badge on the same predicate.
test('postings for you: hard-requirement passes without JEV, JEV keep with it', async () => {
    const { getJobsMode, getNewJobsCount, setTriageOverride } = await import('@/lib/job-actions')
    const today = new Date().toISOString()
    const passed = await posting({ external_id: 'passed', source_content_revision: 1, created_at: today, posted_at: today.slice(0, 10) })
    await posting({ external_id: 'old-passed', created_at: '2026-01-01T00:00:00Z', posted_at: '2026-01-01' })
    await posting({ external_id: 'unscreened' }, null)
    await posting({ external_id: 'closed', source_state: 'closed' })
    await posting({ external_id: 'rejected', pipeline_status: 'discarded' },
        '{"disqualified":true,"screen":{"location":{"pass":false}}}')
    const hidden = await posting({ external_id: 'hidden' })
    await setTriageOverride(hidden.id, 'skip', 'Not interested (web)')
    const forYou = async () => (await getJobPostings({})).data.map((j: any) => j.external_id).sort()

    expect(await getJobsMode()).toBe('screen')
    expect(await forYou()).toEqual(['old-passed', 'passed'])
    expect(await getNewJobsCount()).toBe(1)
    expect((await getJobPostings({ postedSince: new Date(Date.now() - 7 * 86_400_000).toISOString().slice(0, 10) })).data.map((j: any) => j.external_id)).toEqual(['passed'])

    await prisma.jev_profile.create({ data: { id: 1, profile_text: '{}', c_pack: '{}', yoe_pack: '{}', yoe_context: '',
        actor: 'config', updated_at: 'x' } })
    await prisma.job_jev_assessments.create({ data: { job_posting_id: passed.id, state: 'complete', verdict: 'skip',
        reasons_json: '[]', policy_sha256: 'p', source_content_revision: 1, last_attempted_at: 'x', created_at: 'x' } })
    expect(await getJobsMode()).toBe('jev')
    expect(await forYou()).toEqual([])
    await prisma.job_jev_assessments.update({ where: { job_posting_id: passed.id }, data: { verdict: 'keep' } })
    expect(await forYou()).toEqual(['passed'])
})
