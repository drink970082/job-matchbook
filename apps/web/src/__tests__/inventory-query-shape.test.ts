import { prisma } from '@/lib/db'
import { getJobPostings } from '@/lib/job-actions'
import { mockDeep, mockReset } from 'jest-mock-extended'
import { PrismaClient } from '@prisma/client'

jest.mock('@/lib/db', () => {
    const { mockDeep } = jest.requireActual('jest-mock-extended')
    return { __esModule: true, prisma: mockDeep() }
})

const mockPrisma = prisma as unknown as ReturnType<typeof mockDeep<PrismaClient>>

beforeEach(() => mockReset(mockPrisma))

describe('Discovered Jobs query', () => {
    it('uses one bounded SQL list/count predicate and bypasses every fit-derived ID scan', async () => {
        mockPrisma.$queryRaw
            .mockResolvedValueOnce([] as any)
            .mockResolvedValueOnce([{ total: 0 }] as any)

        await getJobPostings({})

        expect((mockPrisma.$queryRaw.mock.calls[0][0] as any).sql).toContain("='keep'") // "for you" by default: the keep stage
        expect(mockPrisma.$queryRaw).toHaveBeenCalledTimes(2)
        expect(mockPrisma.job_postings.findMany).not.toHaveBeenCalled()
        expect(mockPrisma.job_postings.count).not.toHaveBeenCalled()
        for (const [query] of mockPrisma.$queryRaw.mock.calls) {
            const sql = (query as any).sql as string
            expect(sql).toContain("p.pipeline_status <> 'removed'")
            expect(sql).not.toContain('json_extract(score_detail')
            expect(sql).not.toContain('matchedIds')
            expect(sql).not.toContain('belowBarIds')
            expect(sql).not.toContain('lowContextIds')
        }
    })

    it('keeps search and screen outcome predicates in SQL instead of materializing ID lists', async () => {
        mockPrisma.$queryRaw
            .mockResolvedValueOnce([] as any)
            .mockResolvedValueOnce([{ total: 0 }] as any)

        await getJobPostings({
            stage: 'all',
            search: '100%_! complete',
            searchScope: 'all_text',
            screenOutcome: 'unknown',
            page: 2,
            size: 10,
        })

        const calls = mockPrisma.$queryRaw.mock.calls
        expect(calls).toHaveLength(2)
        for (const [query] of calls) {
            const sql = (query as any).sql as string
            const values = (query as any).values as unknown[]
            expect(sql).toContain("p.description LIKE ? ESCAPE '!'")
            expect(sql).toContain('json_each')
            expect(sql).toContain('json_valid(s.result_json)')
            expect(sql).not.toContain('id IN (')
            expect(values).toContain('%100!%!_!! complete%')
            expect(values).toContain('unknown')
        }
        expect(calls[0][0]).toMatchObject({ values: expect.arrayContaining([20, 10]) })
    })

    it('filters the funnel stage in SQL before pagination and count, on the stored verdict', async () => {
        mockPrisma.$queryRaw
            .mockResolvedValueOnce([] as any)
            .mockResolvedValueOnce([{ total: 0 }] as any)

        await getJobPostings({ stage: 'discarded', page: 1, size: 10 })

        const calls = mockPrisma.$queryRaw.mock.calls
        expect(calls).toHaveLength(2)
        for (const [query] of calls) {
            const sql = (query as any).sql as string
            const values = (query as any).values as unknown[]
            expect(sql).toContain("CASE WHEN o.decision IN ('keep','skip') THEN o.decision ELSE p.verdict END")
            expect(sql).not.toContain('p.score_detail')
            expect(sql).not.toContain('app_settings')
            expect(sql).toContain('LEFT JOIN job_jev_assessments j')
            expect(sql).toContain('LEFT JOIN job_triage_overrides o')
            expect(sql).not.toContain('id IN (')
            expect(values).toContain('discarded')
        }
        expect(calls[0][0]).toMatchObject({ values: expect.arrayContaining([10, 10]) })
    })
})
