/**
 * The web's intake funnel (lib/intake-funnel.ts) against the case the worker's MCP test
 * reads too (apps/worker/tests/fixtures/intake-funnel-cases.json): a change to either
 * side's rule fails one of the suites.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { getActivityStatus } from '@/lib/activity-actions'
import type { FunnelWindow, IntakeFunnel } from '@/lib/intake-funnel'
import { prisma, resetDb } from '@/test-utils/db'
import { makeJobPosting } from '@/test-utils/factories'

interface Case {
    now: string
    runs: { started_at: string; status: string; counts: unknown }[]
    postings: { created_at: string; verdict: string; source_state: string; pipeline_status: string
        override: string | null; screen: string | null }[]
    expected: IntakeFunnel
}
const CASE: Case = JSON.parse(readFileSync(
    path.join(__dirname, '../../../worker/tests/fixtures/intake-funnel-cases.json'), 'utf8'))

beforeEach(resetDb)
afterEach(() => jest.restoreAllMocks())
afterAll(() => prisma.$disconnect())

function expectReconciled(w: FunnelWindow) {
    let left = w.stages[0].input
    for (const s of w.stages) {
        expect([s.stage, s.input, s.output]).toEqual([s.stage, left, left - s.removed])
        left = s.output
    }
    expect(left).toBe(w.open)
}

test('the funnel matches the shared case and every stage takes the previous stage\'s output', async () => {
    for (const r of CASE.runs) {
        await prisma.worker_runs.create({ data: { started_at: r.started_at, status: r.status, config_json: '{}',
            counts_json: typeof r.counts === 'string' ? r.counts : JSON.stringify(r.counts) } })
    }
    for (const [i, p] of Array.from(CASE.postings.entries())) {
        const row = await prisma.job_postings.create({ data: makeJobPosting({ external_id: `f${i}`, created_at: p.created_at,
            verdict: p.verdict, source_state: p.source_state, pipeline_status: p.pipeline_status }) })
        if (p.screen !== null) {
            await prisma.job_screenings.create({ data: { job_posting_id: row.id, state: 'complete', result_json: p.screen,
                backend: 'ollama', evaluator_version: 'v', last_attempted_at: 'x', created_at: 'x' } })
        }
        if (p.override) {
            await prisma.job_triage_overrides.create({ data: { job_posting_id: row.id, decision: p.override,
                actor: 'mcp', source_content_revision: 1, created_at: 'x' } })
        }
    }
    jest.spyOn(Date, 'now').mockReturnValue(Date.parse(CASE.now))
    const { funnel } = await getActivityStatus()
    expect(funnel).toEqual(CASE.expected)
    expectReconciled(funnel.latest_pass!)
    expectReconciled(funnel.last_7_days)
})

test('no pass recorded: no latest pass, an empty window', async () => {
    const { funnel } = await getActivityStatus()
    expect(funnel.latest_pass).toBeNull()
    expect([funnel.last_7_days.passes, funnel.last_7_days.open]).toEqual([0, 0])
})
