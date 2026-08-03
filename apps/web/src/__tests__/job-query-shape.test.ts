import { prisma } from '@/lib/db'
import {
    getJobPostings,
    removeAllInView,
    bulkRemove,
    bulkReopen,
    discardJobPosting,
    reopenJobPosting,
} from '@/lib/actions'
import { mockDeep, mockReset } from 'jest-mock-extended'
import { PrismaClient } from '@prisma/client'

// LEVEL A DIFFERENTIAL for CLEAN-05.
//
// getJobPostings and removeAllInView build their Prisma `where` by hand, and the two
// blocks are near-identical. Before consolidating them, pin the EXACT query object
// every filter combination produces, so the refactor is provably a no-op rather than
// an assertion that it is one.
//
// These are deliberately spelled out in full rather than snapshotted: a snapshot
// records whatever the code does today and re-blesses a mistake on `-u`. A reviewer
// can read a literal and disagree with it.

jest.mock('@/lib/db', () => {
    const { mockDeep } = jest.requireActual('jest-mock-extended')
    return { __esModule: true, prisma: mockDeep() }
})

const mockPrisma = prisma as unknown as ReturnType<typeof mockDeep<PrismaClient>>

const LOW_IDS = [7, 8]
const MATCH_IDS = [1, 2]
const BELOW_IDS = [3, 4]
const CAUSE_IDS = [5, 6]

// actions.ts ACTIVE_PIPELINE_STATUSES — the live rows a bucket query can return.
const ACTIVE = ['scored', 'notified']

/**
 * The three id-set helpers each fire one $queryRaw, in the order Promise.all
 * evaluates them: lowContextIds, matchedIds, belowBarIds. disqualifyCauseIds is
 * awaited later, so its stub goes last.
 */
function primeIdSets({ lowIds = LOW_IDS }: { lowIds?: number[] } = {}) {
    const rows = (ids: number[]) => ids.map((id) => ({ id }))
    mockPrisma.$queryRaw
        .mockResolvedValueOnce(rows(lowIds) as any)
        .mockResolvedValueOnce(rows(MATCH_IDS) as any)
        .mockResolvedValueOnce(rows(BELOW_IDS) as any)
        .mockResolvedValueOnce(rows(CAUSE_IDS) as any)
}

/** The `where` getJobPostings actually handed Prisma. */
async function whereFor(params: Parameters<typeof getJobPostings>[0]) {
    primeIdSets()
    mockPrisma.job_postings.findMany.mockResolvedValue([] as any)
    mockPrisma.job_postings.count.mockResolvedValue(0)
    await getJobPostings(params)
    return (mockPrisma.job_postings.findMany.mock.calls[0][0] as any).where
}

const searchClause = (s: string) => ({
    OR: [{ company_name: { contains: s } }, { job_title: { contains: s } }],
})

beforeEach(() => {
    mockReset(mockPrisma)
})

describe('getJobPostings query shape', () => {
    it('matched: id IN matchIds, low-context excluded', async () => {
        expect(await whereFor({ bucket: 'matched' })).toEqual({
            AND: [
                { pipeline_status: { in: ACTIVE }, id: { in: MATCH_IDS } },
                {},
                {},
                { id: { notIn: LOW_IDS } },
            ],
        })
    })

    it('belowbar: id IN belowIds (NOT notIn)', async () => {
        expect(await whereFor({ bucket: 'belowbar' })).toEqual({
            AND: [
                { pipeline_status: { in: ACTIVE }, id: { in: BELOW_IDS } },
                {},
                {},
                { id: { notIn: LOW_IDS } },
            ],
        })
    })

    it('discarded: the two OR populations, no cause clause when no cause given', async () => {
        expect(await whereFor({ bucket: 'discarded' })).toEqual({
            AND: [
                {
                    OR: [
                        {
                            pipeline_status: 'discarded',
                            OR: [
                                { score_detail: { contains: '"disqualified": true' } },
                                { score_detail: { contains: '"disqualified":true' } },
                            ],
                        },
                        {
                            pipeline_status: { in: ACTIVE },
                            id: { notIn: [...MATCH_IDS, ...BELOW_IDS] },
                        },
                    ],
                },
                {},
                {},
                { id: { notIn: LOW_IDS } },
            ],
        })
    })

    // Slot order matters and is load-bearing: base.AND is [bucket, minScore, search],
    // so the cause clause lands at 3 and the low-context exclusion last at 4.
    it('discarded + cause: layers the cause id set after the base clauses', async () => {
        const where = await whereFor({ bucket: 'discarded', cause: 'degree' })
        expect(where.AND).toHaveLength(5)
        expect(where.AND[3]).toEqual({ id: { in: CAUSE_IDS } })
        expect(where.AND[4]).toEqual({ id: { notIn: LOW_IDS } })
    })

    it('lowcontext: its own shape, and does NOT exclude itself', async () => {
        expect(await whereFor({ bucket: 'lowcontext' })).toEqual({
            AND: [{ id: { in: LOW_IDS } }, {}, {}],
        })
    })

    it('failed: status only', async () => {
        expect(await whereFor({ bucket: 'failed' })).toEqual({
            AND: [{ pipeline_status: 'failed' }, {}, {}, { id: { notIn: LOW_IDS } }],
        })
    })

    it('search and minScore ride as peer clauses, in that slot order', async () => {
        expect(await whereFor({ bucket: 'matched', search: 'acme', minScore: 70 })).toEqual({
            AND: [
                { pipeline_status: { in: ACTIVE }, id: { in: MATCH_IDS } },
                { score: { gte: 70 } },
                searchClause('acme'),
                { id: { notIn: LOW_IDS } },
            ],
        })
    })

    it('search reaches the lowcontext branch too', async () => {
        expect(await whereFor({ bucket: 'lowcontext', search: 'acme' })).toEqual({
            AND: [{ id: { in: LOW_IDS } }, {}, searchClause('acme')],
        })
    })

    // The guard that stops an empty keep-set becoming `NOT IN ()`, which SQLite reads
    // as excluding nothing rather than everything.
    it('omits the low-context exclusion entirely when there are no low-context rows', async () => {
        primeIdSets({ lowIds: [] })
        mockPrisma.job_postings.findMany.mockResolvedValue([] as any)
        mockPrisma.job_postings.count.mockResolvedValue(0)
        await getJobPostings({ bucket: 'matched' })
        const where = (mockPrisma.job_postings.findMany.mock.calls[0][0] as any).where
        expect(where.AND).toHaveLength(3)
        expect(JSON.stringify(where)).not.toContain('notIn')
    })
})

describe('getJobPostings ordering and paging', () => {
    async function argsFor(params: Parameters<typeof getJobPostings>[0]) {
        primeIdSets()
        mockPrisma.job_postings.findMany.mockResolvedValue([] as any)
        mockPrisma.job_postings.count.mockResolvedValue(0)
        await getJobPostings(params)
        // Last call, not first: some cases invoke this helper twice in one test.
        const calls = mockPrisma.job_postings.findMany.mock.calls
        return calls[calls.length - 1][0] as any
    }

    it('defaults to score desc, id asc', async () => {
        expect((await argsFor({ bucket: 'matched' })).orderBy).toEqual([
            { score: 'desc' },
            { id: 'asc' },
        ])
    })

    it('sort=posted switches to posted_at desc, id desc', async () => {
        expect((await argsFor({ bucket: 'matched', sort: 'posted' })).orderBy).toEqual([
            { posted_at: 'desc' },
            { id: 'desc' },
        ])
    })

    it('pages with skip = page * size and clamps size to 100', async () => {
        const a = await argsFor({ bucket: 'matched', page: 2, size: 25 })
        expect({ skip: a.skip, take: a.take }).toEqual({ skip: 50, take: 25 })

        const b = await argsFor({ bucket: 'matched', page: 0, size: 5000 })
        expect({ skip: b.skip, take: b.take }).toEqual({ skip: 0, take: 100 })
    })

    it('floors negative pages to 0 and sizes below 1 to 1', async () => {
        const a = await argsFor({ bucket: 'matched', page: -3, size: 0 })
        expect({ skip: a.skip, take: a.take }).toEqual({ skip: 0, take: 1 })
    })
})

// bulkRemove/bulkReopen were covered ONLY by *.int.test.ts, which jest.config.ts
// excludes from the default run — so the refactor that routed them through a shared
// helper would have had no fast-suite guard. These pin the status literal and the
// updated_at stamp for all four hand-moved-status actions.
describe('pipeline status mutations', () => {
    const cases = [
        ['bulkRemove', bulkRemove, 'removed'],
        ['bulkReopen', bulkReopen, 'scored'],
    ] as const

    it.each(cases)('%s writes its status and stamps updated_at', async (_n, fn, status) => {
        mockPrisma.job_postings.updateMany.mockResolvedValue({ count: 2 } as any)
        const res = await fn([1, 2])

        const call = mockPrisma.job_postings.updateMany.mock.calls[0][0] as any
        expect(call.where).toEqual({ id: { in: [1, 2] } })
        expect(call.data.pipeline_status).toBe(status)
        expect(call.data.updated_at).toMatch(/^\d{4}-\d{2}-\d{2}T/)
        expect(res).toEqual({ success: true, count: 2 })
    })

    it.each([
        ['discardJobPosting', discardJobPosting, 'removed'],
        ['reopenJobPosting', reopenJobPosting, 'scored'],
    ] as const)('%s writes its status for one row', async (_n, fn, status) => {
        mockPrisma.job_postings.update.mockResolvedValue({} as any)
        const res = await fn(42)

        const call = mockPrisma.job_postings.update.mock.calls[0][0] as any
        expect(call.where).toEqual({ id: 42 })
        expect(call.data.pipeline_status).toBe(status)
        expect(res).toEqual({ success: true })
    })

    it('reports the driver error rather than throwing', async () => {
        mockPrisma.job_postings.updateMany.mockRejectedValue(new Error('db is gone'))
        expect(await bulkRemove([1])).toEqual({ success: false, error: 'db is gone' })
    })
})

describe('removeAllInView query shape', () => {
    it('builds the same where as getJobPostings for the discarded bucket + cause', async () => {
        primeIdSets()
        mockPrisma.job_postings.updateMany.mockResolvedValue({ count: 3 } as any)
        await removeAllInView({ bucket: 'discarded', cause: 'degree' })

        const call = mockPrisma.job_postings.updateMany.mock.calls[0][0] as any
        expect(call.where.AND).toHaveLength(5)
        expect(call.where.AND[3]).toEqual({ id: { in: CAUSE_IDS } })
        expect(call.where.AND[4]).toEqual({ id: { notIn: LOW_IDS } })
        expect(call.data.pipeline_status).toBe('removed')
    })

    // KNOWN ASYMMETRY, pinned so a refactor cannot quietly "fix" it. removeAllInView
    // has no lowcontext branch, so buildJobWhere falls through to its `matched`
    // default. Unreachable today -- the "Remove all in view" button renders only on
    // the discarded bucket (DiscoveredJobsTable.tsx:347) -- but it is a landmine if
    // that button is ever shown elsewhere. Recorded in the deep-clean decision
    // register; correcting it is a behavior change, not cleanup.
    it('lowcontext falls through to the matched shape (latent, documented)', async () => {
        primeIdSets()
        mockPrisma.job_postings.updateMany.mockResolvedValue({ count: 0 } as any)
        await removeAllInView({ bucket: 'lowcontext' })

        const call = mockPrisma.job_postings.updateMany.mock.calls[0][0] as any
        expect(call.where.AND[0]).toEqual({
            pipeline_status: { in: ACTIVE },
            id: { in: MATCH_IDS },
        })
    })
})
