import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
    bulkRemove,
    discardJobPosting,
    getJobPostings,
    markJobApplied,
    reopenJobPosting,
    removeAllInView,
} from '@/lib/actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeJobPosting } from '@/test-utils/factories'

const sharedFixture = JSON.parse(readFileSync(
    resolve(__dirname, '../../../worker/tests/fixtures/standalone_screen_contract.json'),
    'utf8',
))
const triageFixture = JSON.parse(readFileSync(
    resolve(__dirname, '../../../worker/tests/fixtures/job_triage_contract.json'),
    'utf8',
))

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

async function createScreenedPosting(name: string, state: string | null, resultJson: string | null, extra: Record<string, unknown> = {}) {
    const posting = await prisma.job_postings.create({
        data: makeJobPosting({
            external_id: name,
            job_title: name,
            pipeline_status: 'new',
            score: null,
            score_detail: null,
            ...extra,
        }),
    })
    if (state !== null) {
        await prisma.job_screenings.create({
            data: {
                job_posting_id: posting.id,
                state,
                result_json: resultJson,
                error_category: null,
                error_message: null,
                backend: 'synthetic',
                model: 'fixture-model',
                effort: 'medium',
                evaluator_version: 'fixture-v1',
                last_attempted_at: '2026-10-22T10:00:00Z',
                completed_at: '2026-10-22T10:00:01Z',
                created_at: '2026-10-22T10:00:00Z',
                updated_at: '2026-10-22T10:00:01Z',
            },
        })
    }
    return posting
}

test('All jobs puts a recent unscored row ahead of more than one page of older scored rows', async () => {
    for (let index = 0; index < 30; index += 1) {
        await prisma.job_postings.create({
            data: makeJobPosting({
                external_id: `old-${index}`,
                job_title: `Older scored ${index}`,
                pipeline_status: 'scored',
                score: 99,
                score_detail: index === 0 ? '{malformed legacy JSON' : null,
                created_at: '2026-01-01T00:00:00.000Z',
            }),
        })
    }
    const recent = await prisma.job_postings.create({
        data: makeJobPosting({
            external_id: 'recent-new',
            job_title: 'Recent unscored role',
            pipeline_status: 'new',
            score: null,
            score_detail: '{malformed legacy JSON',
            created_at: '2026-10-22T12:00:00.000Z',
        }),
    })

    const firstPage = await getJobPostings({ size: 25 })

    expect(firstPage.total).toBe(31)
    expect(firstPage.data[0].id).toBe(recent.id)
    expect(firstPage.data[0].screen_summary.outcome).toBe('not_screened')
    expect(firstPage.data[0].legacy_screen_evidence.available).toBe(false)
    expect(firstPage.data).toHaveLength(25)
})

test('All jobs includes every non-removed status and uses id as a stable recency tie-breaker', async () => {
    const states = ['new', 'scored', 'notified', 'discarded', 'failed', 'applied', 'expired', 'future_state', 'removed']
    const ids: number[] = []
    for (const [index, status] of states.entries()) {
        const posting = await prisma.job_postings.create({
            data: makeJobPosting({
                external_id: `state-${status}`,
                pipeline_status: status,
                created_at: '2026-10-22T12:00:00.000Z',
                score_detail: status === 'future_state' ? '{bad json' : null,
            }),
        })
        ids.push(posting.id)
    }

    const result = await getJobPostings({})

    expect(result.data.map((row) => row.pipeline_status)).toEqual([
        'future_state', 'expired', 'applied', 'failed', 'discarded', 'notified', 'scored', 'new',
    ])
    expect(result.data.map((row) => row.id)).toEqual(ids.slice(0, -1).reverse())
    expect(result.total).toBe(8)
})

test('standalone filters keep large matches in SQL without binding one ID per posting', async () => {
    const postings = Array.from({ length: 1_050 }, (_, index) => makeJobPosting({
        external_id: `large-unscored-${index}`,
        pipeline_status: 'new',
        score: null,
        score_detail: null,
    }))
    await prisma.job_postings.createMany({ data: postings })

    const result = await getJobPostings({ bucket: 'all', screenOutcome: 'not_screened', size: 25 })

    expect(result.total).toBe(1_050)
    expect(result.data).toHaveLength(25)
})

test('web standalone summaries and filters match the shared worker contract fixture', async () => {
    const expectedIds = new Map<string, number>()
    for (const item of sharedFixture.cases) {
        const posting = await createScreenedPosting(item.name, item.state, item.result_json_raw)
        expectedIds.set(item.name, posting.id)
    }
    await createScreenedPosting(
        'legacy-only',
        null,
        null,
        { score_detail: sharedFixture.legacy_evidence.score_detail_raw },
    )

    const all = await getJobPostings({ bucket: 'all', size: 100 })
    const byName = new Map(all.data.map((item) => [item.job_title, item]))
    for (const item of sharedFixture.cases) {
        const row = byName.get(item.name)!
        expect(row.screen_summary.outcome).toBe(item.expected_outcome)
        expect(row.screen_summary.is_advisory).toBe(true)
        expect(row.screen_summary.origin).toBe(item.state === null ? 'none' : 'job_screenings')

        const filtered = await getJobPostings({ bucket: 'all', screenOutcome: item.expected_outcome, size: 100 })
        expect(filtered.data.map((match) => match.id)).toContain(expectedIds.get(item.name))
    }
    expect(byName.get('legacy-only')!.screen_summary.outcome).toBe('not_screened')
    expect(byName.get('legacy-only')!.legacy_screen_evidence).toEqual({
        available: true,
        origin: 'job_postings.score_detail.screen',
    })
})

test('web triage summaries, SQL filters, counts, and detail match the shared worker fixture', async () => {
    const expectedIds = new Map<string, number>()
    for (const item of triageFixture.cases) {
        const posting = await createScreenedPosting(
            item.name,
            item.screening?.state ?? null,
            item.screening?.result_json_raw ?? null,
            {
                pipeline_status: item.pipeline_status,
                score_detail: item.score_detail_raw,
                created_at: '2026-10-22T12:00:00.000Z',
            },
        )
        expectedIds.set(item.name, posting.id)
    }

    const all = await getJobPostings({ bucket: 'all', size: 100 })
    const byId = new Map(all.data.map((row) => [row.id, row]))
    expect(all.total).toBe(triageFixture.cases.length)
    for (const item of triageFixture.cases) {
        const row = byId.get(expectedIds.get(item.name)!)!
        expect(row.triage_summary.status).toBe(item.expected_status)
        expect(row.triage_summary.provenance).toBe(item.expected_provenance)
        expect(row.triage_summary.reason).not.toContain('Synthetic private error text')
    }
    expect(byId.get(expectedIds.get('standalone_unrecognized_check')!)?.screen_summary.outcome)
        .toBe('disqualified')
    expect(byId.get(expectedIds.get('no_assessment_evidence')!)?.screen_summary.outcome)
        .toBe('not_screened')

    const statuses = [...new Set<string>(triageFixture.cases.map((item: any) => item.expected_status))] as
        Array<'rule_disqualified' | 'screen_disqualified' | 'candidate' | 'needs_review'>
    for (const status of statuses) {
        const expected = triageFixture.cases
            .filter((item: any) => item.expected_status === status)
            .map((item: any) => expectedIds.get(item.name))
        const filtered = await getJobPostings({ bucket: 'all', triageStatus: status, size: 100 })
        expect(filtered.data.map((row) => row.id).sort((a, b) => a - b))
            .toEqual(expected.sort((a: number, b: number) => a - b))
        expect(filtered.total).toBe(expected.length)
    }

    const candidatePage = await getJobPostings({ bucket: 'all', triageStatus: 'candidate', size: 1 })
    expect(candidatePage.data[0].id).toBe(expectedIds.get('standalone_candidate_notified'))
    expect(candidatePage.total).toBe(3)
    await expect(getJobPostings({ bucket: 'matched', triageStatus: 'candidate' }))
        .rejects.toThrow(/only supported in all jobs/i)
})

test('All jobs all-text search treats LIKE metacharacters literally and scopes description explicitly', async () => {
    const literalPercent = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'literal-percent', pipeline_status: 'new', description: 'coverage 100% guarantee' }),
    })
    await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'wildcard-percent', pipeline_status: 'new', description: 'coverage 100x guarantee' }),
    })
    const literalUnderscore = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'literal-underscore', pipeline_status: 'new', description: 'role_id phrase' }),
    })
    await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'wildcard-underscore', pipeline_status: 'new', description: 'roleXid phrase' }),
    })
    const literalBang = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'literal-bang', pipeline_status: 'new', description: 'bang! marker' }),
    })

    expect((await getJobPostings({ bucket: 'all', search: '%', searchScope: 'all_text' })).data.map((row) => row.id))
        .toContain(literalPercent.id)
    expect((await getJobPostings({ bucket: 'all', search: '%', searchScope: 'all_text' })).data.map((row) => row.external_id))
        .toEqual(['literal-percent'])
    expect((await getJobPostings({ bucket: 'all', search: '_', searchScope: 'all_text' })).data.map((row) => row.external_id))
        .toEqual(['literal-underscore'])
    expect((await getJobPostings({ bucket: 'all', search: '!', searchScope: 'all_text' })).data.map((row) => row.external_id))
        .toContain('literal-bang')
    expect((await getJobPostings({ bucket: 'all', search: '100%', searchScope: 'metadata' })).data).toHaveLength(0)
    expect(literalUnderscore.id).toBeGreaterThan(0)
})

test('All jobs per-row actions validate the exact view/filter scope; bulk actions reject inventory', async () => {
    const inScope = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'scope-hit', company_name: 'Acme Search', pipeline_status: 'new' }),
    })
    const outsideScope = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'scope-miss', company_name: 'Other Co', pipeline_status: 'new' }),
    })
    const scope = { bucket: 'all' as const, search: 'Acme Search', searchScope: 'metadata' as const }

    expect(await discardJobPosting(inScope.id, scope)).toEqual({ success: true })
    expect(await discardJobPosting(outsideScope.id, scope)).toMatchObject({ success: false })
    expect((await prisma.job_postings.findUnique({ where: { id: outsideScope.id } }))!.pipeline_status).toBe('new')
    expect(await bulkRemove([outsideScope.id], { bucket: 'all' })).toMatchObject({ success: false })
    expect(await removeAllInView({ bucket: 'all' })).toMatchObject({ success: false })
    expect((await prisma.job_postings.findUnique({ where: { id: outsideScope.id } }))!.pipeline_status).toBe('new')
})

test('All jobs Reopen works only for a scoped discarded row', async () => {
    const discarded = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'reopen-scope', pipeline_status: 'discarded' }),
    })
    const other = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'reopen-other', pipeline_status: 'new' }),
    })

    expect(await reopenJobPosting(discarded.id, { bucket: 'all' })).toEqual({ success: true })
    expect(await reopenJobPosting(other.id, { bucket: 'all' })).toMatchObject({ success: false })
    expect((await prisma.job_postings.findUnique({ where: { id: discarded.id } }))!.pipeline_status).toBe('scored')
})

test('All jobs Mark Applied keeps the application transaction and rejects an applied row', async () => {
    const posting = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'apply-scope', pipeline_status: 'new' }),
    })
    const scope = { bucket: 'all' as const }

    const result = await markJobApplied(posting.id, 'SWE', scope)
    expect(result.success).toBe(true)
    const after = await prisma.job_postings.findUnique({ where: { id: posting.id } })
    expect(after?.pipeline_status).toBe('applied')
    expect(after?.application_id).not.toBeNull()
    expect(await markJobApplied(posting.id, 'SWE', scope)).toMatchObject({ success: false })
    expect(await prisma.applications.count()).toBe(1)
})

test('server actions reject unknown inventory scopes instead of falling through to a fit bucket', async () => {
    await expect(getJobPostings({ bucket: 'future-bucket' as any })).rejects.toThrow(/bucket/i)
    await expect(getJobPostings({ bucket: 'all', searchScope: 'everything' as any })).rejects.toThrow(/search scope/i)
    await expect(getJobPostings({ bucket: 'all', screenOutcome: '' as any })).rejects.toThrow(/screen outcome/i)
    await expect(getJobPostings({ bucket: 'all', triageStatus: 'not_screened' as any })).rejects.toThrow(/triage status/i)
    await expect(getJobPostings({ bucket: 'matched', triageStatus: 'candidate' })).rejects.toThrow(/only supported in all jobs/i)
})

test('mutation entrypoints reject paging and unsupported filters before changing a row', async () => {
    const posting = await prisma.job_postings.create({
        data: makeJobPosting({ external_id: 'invalid-mutation-scope', pipeline_status: 'new' }),
    })

    expect(await bulkRemove([posting.id], { bucket: 'matched', page: 0 } as any)).toMatchObject({ success: false })
    expect(await bulkRemove([posting.id], { bucket: 'matched', screenOutcome: 'provider_error' } as any))
        .toMatchObject({ success: false })
    expect(await bulkRemove([posting.id], { bucket: 'matched', triageStatus: 'candidate' } as any))
        .toMatchObject({ success: false })
    expect((await prisma.job_postings.findUnique({ where: { id: posting.id } }))?.pipeline_status).toBe('new')
})
