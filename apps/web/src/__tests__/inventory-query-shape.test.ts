import { prisma } from '@/lib/db'
import { getJobPostings } from '@/lib/actions'
import { mockDeep, mockReset } from 'jest-mock-extended'
import { PrismaClient } from '@prisma/client'

jest.mock('@/lib/db', () => {
    const { mockDeep } = jest.requireActual('jest-mock-extended')
    return { __esModule: true, prisma: mockDeep() }
})

const mockPrisma = prisma as unknown as ReturnType<typeof mockDeep<PrismaClient>>

beforeEach(() => mockReset(mockPrisma))

describe('All jobs direct query', () => {
    it('uses one bounded SQL list/count predicate and bypasses every fit-derived ID scan', async () => {
        mockPrisma.$queryRaw
            .mockResolvedValueOnce([] as any)
            .mockResolvedValueOnce([{ total: 0 }] as any)

        await getJobPostings({})

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
            bucket: 'all',
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

    it('filters derived triage in SQL before pagination and count without fit ID scans', async () => {
        mockPrisma.$queryRaw
            .mockResolvedValueOnce([] as any)
            .mockResolvedValueOnce([{ total: 0 }] as any)

        await getJobPostings({ bucket: 'all', triageStatus: 'rule_disqualified', page: 1, size: 10 })

        const calls = mockPrisma.$queryRaw.mock.calls
        expect(calls).toHaveLength(2)
        for (const [query] of calls) {
            const sql = (query as any).sql as string
            const values = (query as any).values as unknown[]
            expect(sql).toContain("p.pipeline_status NOT IN")
            expect(sql).toContain('json_each')
            expect(sql).toContain('p.score_detail')
            expect(sql).toContain('s.result_json')
            expect(sql).toContain("'screen_disqualified'")
            expect(sql).toContain("'candidate'")
            expect(sql).toContain("'needs_review'")
            expect(sql).not.toContain('matchedIds')
            expect(sql).not.toContain('id IN (')
            expect(values).toContain('rule_disqualified')
        }
        expect(calls[0][0]).toMatchObject({ values: expect.arrayContaining([10, 10]) })
    })
})
