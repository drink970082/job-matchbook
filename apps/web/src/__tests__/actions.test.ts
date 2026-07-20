import { prisma } from '@/lib/db'
import {
  getApplications,
  addApplication,
  updateApplicationStatus,
  updateApplicationDetails,
  getKPIs,
  getJobPostings,
  discardJobPosting,
  reopenJobPosting,
  markJobApplied,
} from '@/lib/actions'
import { mockDeep, mockReset } from 'jest-mock-extended'
import { PrismaClient } from '@prisma/client'

jest.mock('@/lib/db', () => {
  const { mockDeep } = jest.requireActual('jest-mock-extended')
  return {
    __esModule: true,
    prisma: mockDeep(),
  }
})

const mockPrisma = prisma as unknown as ReturnType<typeof mockDeep<PrismaClient>>

beforeEach(() => {
  mockReset(mockPrisma)
})

describe('Backend Actions', () => {
  describe('getApplications', () => {
    it('should return applications with pagination', async () => {
      const mockApps = [
        { id: 1, company_name: 'Google', job_title: 'SWE', status: 'Applied', category: 'SWE', date_applied: '2023-01-01', notes: '' },
        { id: 2, company_name: 'Meta', job_title: 'MLE', status: 'Applied', category: 'MLE', date_applied: '2023-01-02', notes: '' },
      ]
      
      mockPrisma.applications.findMany.mockResolvedValue(mockApps as any)
      mockPrisma.applications.count.mockResolvedValue(2)

      const result = await getApplications({ page: 0, size: 10 })

      expect(result.data).toHaveLength(2)
      expect(result.total).toBe(2)
      expect(mockPrisma.applications.findMany).toHaveBeenCalledWith(expect.objectContaining({
        skip: 0,
        take: 10,
        orderBy: { date_applied: 'desc' }
      }))
    })

    it('should filter by status', async () => {
      mockPrisma.applications.findMany.mockResolvedValue([])
      mockPrisma.applications.count.mockResolvedValue(0)

      await getApplications({ page: 0, size: 10, status: 'Applied' })

      expect(mockPrisma.applications.findMany).toHaveBeenCalledWith(expect.objectContaining({
        where: expect.objectContaining({
          AND: expect.arrayContaining([
            expect.objectContaining({ status: 'Applied' })
          ])
        })
      }))
    })

    it('should filter by search term', async () => {
      mockPrisma.applications.findMany.mockResolvedValue([])
      mockPrisma.applications.count.mockResolvedValue(0)

      await getApplications({ page: 0, size: 10, search: 'Google' })

      expect(mockPrisma.applications.findMany).toHaveBeenCalledWith(expect.objectContaining({
        where: expect.objectContaining({
          AND: expect.arrayContaining([
            expect.objectContaining({
              OR: expect.arrayContaining([
                expect.objectContaining({ company_name: { contains: 'Google' } })
              ])
            })
          ])
        })
      }))
    })

    it('clamps an oversized page size', async () => {
      mockPrisma.applications.findMany.mockResolvedValue([])
      mockPrisma.applications.count.mockResolvedValue(0)

      await getApplications({ page: -5, size: 99999 })

      expect(mockPrisma.applications.findMany).toHaveBeenCalledWith(
        expect.objectContaining({ skip: 0, take: 100 }))
    })
  })

  describe('addApplication', () => {
    it('should add a valid application', async () => {
      const newApp = {
        company_name: 'Amazon',
        job_title: 'SDE',
        date_applied: '2023-01-03',
        category: 'SWE',
        status: 'Applied',
        application_url: '',
        notes: ''
      }

      // addApplication wraps findFirst + create in a $transaction
      mockPrisma.$transaction.mockImplementation(async (callback: any) => await callback(mockPrisma))
      mockPrisma.applications.findFirst.mockResolvedValue(null)
      mockPrisma.applications.create.mockResolvedValue({ id: 3, ...newApp } as any)

      const result = await addApplication(newApp)

      expect(result.success).toBe(true)
      expect(mockPrisma.applications.create).toHaveBeenCalled()
    })

    it('should fail if duplicate exists', async () => {
      const newApp = {
        company_name: 'Amazon',
        job_title: 'SDE',
        date_applied: '2023-01-03',
        category: 'SWE',
        status: 'Applied'
      }

      mockPrisma.$transaction.mockImplementation(async (callback: any) => await callback(mockPrisma))
      mockPrisma.applications.findFirst.mockResolvedValue({ id: 1 } as any)

      const result = await addApplication(newApp)

      expect(result.success).toBe(false)
      expect(result.error).toContain('already exists')
      expect(mockPrisma.applications.create).not.toHaveBeenCalled()
    })

    it('coerces an out-of-set status to Applied', async () => {
      mockPrisma.$transaction.mockImplementation(async (callback: any) => await callback(mockPrisma))
      mockPrisma.applications.findFirst.mockResolvedValue(null)
      mockPrisma.applications.create.mockResolvedValue({ id: 1 } as any)

      await addApplication({ company_name: 'A', job_title: 'B', date_applied: '2026-01-01', status: 'Hacked' })

      expect(mockPrisma.applications.create).toHaveBeenCalledWith(
        expect.objectContaining({ data: expect.objectContaining({ status: 'Applied' }) }))
    })

    it('keeps a free-form category (blank falls back to Others)', async () => {
      mockPrisma.$transaction.mockImplementation(async (callback: any) => await callback(mockPrisma))
      mockPrisma.applications.findFirst.mockResolvedValue(null)
      mockPrisma.applications.create.mockResolvedValue({ id: 1 } as any)

      await addApplication({ company_name: 'A', job_title: 'B', date_applied: '2026-01-01', category: 'Private Equity' })
      expect(mockPrisma.applications.create).toHaveBeenCalledWith(
        expect.objectContaining({ data: expect.objectContaining({ category: 'Private Equity' }) }))

      mockPrisma.applications.create.mockClear()
      await addApplication({ company_name: 'A', job_title: 'B', date_applied: '2026-01-01', category: '   ' })
      expect(mockPrisma.applications.create).toHaveBeenCalledWith(
        expect.objectContaining({ data: expect.objectContaining({ category: 'Others' }) }))
    })
  })

  describe('updateApplicationDetails', () => {
    it('keeps a free-form category', async () => {
      mockPrisma.applications.update.mockResolvedValue({ id: 1 } as any)

      await updateApplicationDetails(1, { company_name: 'A', job_title: 'B', category: 'Investment Banking' })

      expect(mockPrisma.applications.update).toHaveBeenCalledWith(
        expect.objectContaining({ data: expect.objectContaining({ category: 'Investment Banking' }) }))
    })
  })

  describe('updateApplicationStatus', () => {
    it('should update status and add history', async () => {
      const appId = 1
      const newStatus = 'Interviewing: 1st round'
      
      mockPrisma.applications.findUnique.mockResolvedValue({ id: appId, status: 'Applied' } as any)
      // $transaction is overloaded (batch array + interactive callback); only `any`
      // satisfies both overloads for mockImplementation. Explicit, not implicit.
      mockPrisma.$transaction.mockImplementation(async (callback: any) => await callback(mockPrisma))

      const result = await updateApplicationStatus(appId, newStatus)

      expect(result.success).toBe(true)
      expect(mockPrisma.applications.update).toHaveBeenCalledWith(expect.objectContaining({
        where: { id: appId },
        data: expect.objectContaining({ status: newStatus })
      }))
      expect(mockPrisma.status_history.create).toHaveBeenCalledWith(expect.objectContaining({
        data: expect.objectContaining({
          application_id: appId,
          status: newStatus
        })
      }))
    })
  })

  describe('getKPIs', () => {
    it('should calculate KPIs correctly', async () => {
      const mockApps = [
        { status: 'Applied' },
        { status: 'Applied' },
        { status: 'Rejected' },
        { status: 'Offer' },
        { status: 'Interviewing: 1st round' },
      ]

      mockPrisma.applications.findMany.mockResolvedValue(mockApps as any)

      const kpis = await getKPIs()

      expect(kpis.applied).toBe(5) // total count
      expect(kpis.rejected).toBe(1)
      expect(kpis.offer).toBe(1)
      expect(kpis.interviewing).toBe(1)
      expect(kpis.active).toBe(3) // Total - Rejected - Offer = 5 - 1 - 1
    })
  })

  describe('getJobPostings', () => {
    // getJobPostings derives the low-context id set via a raw query first; default it
    // to empty so the score-aware bucket assertions below see the unmodified where.
    beforeEach(() => {
      mockPrisma.$queryRaw.mockResolvedValue([] as any)
    })

    it('excludes the derived low-context ids from a score-aware bucket', async () => {
      mockPrisma.$queryRaw.mockResolvedValue([{ id: 7 }, { id: 9 }] as any)
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ bucket: 'matched' })

      const where = (mockPrisma.job_postings.findMany.mock.calls[0][0] as any).where
      expect(JSON.stringify(where)).toContain('"notIn":[7,9]')
    })

    it('lowcontext bucket selects exactly the derived low-context ids', async () => {
      mockPrisma.$queryRaw.mockResolvedValue([{ id: 3 }, { id: 5 }] as any)
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ bucket: 'lowcontext' })

      const where = (mockPrisma.job_postings.findMany.mock.calls[0][0] as any).where
      expect(JSON.stringify(where)).toContain('"in":[3,5]')
    })

    it('should default to the matched bucket (actionable + verdict id set), score desc then id', async () => {
      // getJobPostings derives lowIds then matchIds via Promise.all([lowContextIds(),
      // matchedIds()]) — both hit $queryRaw in that order. Queue: low-context = [] (no
      // notIn), matched-verdict = [11, 22] (the id IN set).
      mockPrisma.$queryRaw.mockResolvedValueOnce([])
      mockPrisma.$queryRaw.mockResolvedValueOnce([{ id: 11 }, { id: 22 }])
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      const result = await getJobPostings({})

      expect(result.total).toBe(0)
      expect(mockPrisma.job_postings.findMany).toHaveBeenCalledWith(
        expect.objectContaining({
          where: expect.objectContaining({
            AND: expect.arrayContaining([
              expect.objectContaining({
                pipeline_status: { in: ['scored', 'notified'] },
                id: { in: [11, 22] },
              }),
            ]),
          }),
          orderBy: [{ score: 'desc' }, { id: 'asc' }],
          skip: 0,
          take: 25,
        })
      )
    })

    it('discarded bucket = disqualified only (discarded status + disqualified flag)', async () => {
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ bucket: 'discarded' })

      expect(mockPrisma.job_postings.findMany).toHaveBeenCalledWith(
        expect.objectContaining({
          where: expect.objectContaining({
            AND: expect.arrayContaining([
              expect.objectContaining({
                pipeline_status: 'discarded',
                OR: [
                  { score_detail: { contains: '"disqualified": true' } },
                  { score_detail: { contains: '"disqualified":true' } },
                ],
              }),
            ]),
          }),
        })
      )
    })

    it('belowbar bucket = live rows outside the matched-verdict id set', async () => {
      // Queue: low-context = [] (no notIn), matched-verdict = [11, 22] (excluded via notIn).
      mockPrisma.$queryRaw.mockResolvedValueOnce([])
      mockPrisma.$queryRaw.mockResolvedValueOnce([{ id: 11 }, { id: 22 }])
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ bucket: 'belowbar' })

      expect(mockPrisma.job_postings.findMany).toHaveBeenCalledWith(
        expect.objectContaining({
          where: expect.objectContaining({
            AND: expect.arrayContaining([
              expect.objectContaining({
                pipeline_status: { in: ['scored', 'notified'] },
                id: { notIn: [11, 22] },
              }),
            ]),
          }),
        })
      )
    })

    it('belowbar bucket omits notIn entirely when the matched-verdict id set is empty', async () => {
      // Guard: an empty matchIds must not emit `id: { notIn: [] }` (which would exclude
      // nothing rather than nothing being excluded from a would-be-empty set).
      mockPrisma.$queryRaw.mockResolvedValue([] as any)
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ bucket: 'belowbar' })

      const where = (mockPrisma.job_postings.findMany.mock.calls[0][0] as any).where
      expect(JSON.stringify(where)).not.toContain('notIn')
    })

    it('failed bucket filters to pipeline_status=failed', async () => {
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ bucket: 'failed' })

      expect(mockPrisma.job_postings.findMany).toHaveBeenCalledWith(
        expect.objectContaining({
          where: expect.objectContaining({
            AND: expect.arrayContaining([
              expect.objectContaining({ pipeline_status: 'failed' }),
            ]),
          }),
        })
      )
    })

    it('paginates with skip/take', async () => {
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ page: 2, size: 10 })

      expect(mockPrisma.job_postings.findMany).toHaveBeenCalledWith(
        expect.objectContaining({ skip: 20, take: 10 })
      )
    })

    it('clamps an oversized page size', async () => {
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ page: -5, size: 99999 })

      expect(mockPrisma.job_postings.findMany).toHaveBeenCalledWith(
        expect.objectContaining({ skip: 0, take: 100 })
      )
    })

    it('applies a minScore filter', async () => {
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ minScore: 60 })

      expect(mockPrisma.job_postings.findMany).toHaveBeenCalledWith(
        expect.objectContaining({
          where: expect.objectContaining({
            AND: expect.arrayContaining([expect.objectContaining({ score: { gte: 60 } })]),
          }),
        })
      )
    })

    it('cause sub-filter layers a disqualification-cause id set onto the discarded bucket', async () => {
      // getJobPostings runs lowContextIds() then matchedIds() (via Promise.all, in that
      // order), then disqualifyCauseIds(); all three use $queryRaw. Queue: low-context =
      // [] (no notIn), matched-verdict = [] (unused by the discarded bucket), cause =
      // [4, 8] (the id IN set).
      mockPrisma.$queryRaw.mockResolvedValueOnce([])
      mockPrisma.$queryRaw.mockResolvedValueOnce([])
      mockPrisma.$queryRaw.mockResolvedValueOnce([{ id: 4 }, { id: 8 }])
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ bucket: 'discarded', cause: 'degree' })

      const where = (mockPrisma.job_postings.findMany.mock.calls[0][0] as any).where
      const serialized = JSON.stringify(where)
      expect(serialized).toContain('"pipeline_status":"discarded"')
      expect(serialized).toContain('"in":[4,8]')
    })

    it('should support search over company_name and job_title', async () => {
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ search: 'acme' })

      expect(mockPrisma.job_postings.findMany).toHaveBeenCalledWith(
        expect.objectContaining({
          where: expect.objectContaining({
            AND: expect.arrayContaining([
              expect.objectContaining({
                OR: expect.arrayContaining([
                  expect.objectContaining({ company_name: { contains: 'acme' } }),
                  expect.objectContaining({ job_title: { contains: 'acme' } }),
                ]),
              }),
            ]),
          }),
        })
      )
    })
  })

  describe('discardJobPosting', () => {
    it('should set pipeline_status to removed (hidden, not the disqualified-only discarded bucket)', async () => {
      mockPrisma.job_postings.update.mockResolvedValue({ id: 1 } as any)

      const result = await discardJobPosting(1)

      expect(result.success).toBe(true)
      expect(mockPrisma.job_postings.update).toHaveBeenCalledWith(
        expect.objectContaining({
          where: { id: 1 },
          data: expect.objectContaining({ pipeline_status: 'removed' }),
        })
      )
    })
  })

  describe('reopenJobPosting', () => {
    it('should set pipeline_status back to scored', async () => {
      mockPrisma.job_postings.update.mockResolvedValue({ id: 1 } as any)

      const result = await reopenJobPosting(1)

      expect(result.success).toBe(true)
      expect(mockPrisma.job_postings.update).toHaveBeenCalledWith(
        expect.objectContaining({
          where: { id: 1 },
          data: expect.objectContaining({ pipeline_status: 'scored' }),
        })
      )
    })
  })

  // discard/reopen share the same try/catch error path
  it.each([
    ['discardJobPosting', discardJobPosting],
    ['reopenJobPosting', reopenJobPosting],
  ] as const)('%s returns { success: false, error } when the update throws', async (_name, fn) => {
    mockPrisma.job_postings.update.mockRejectedValue(new Error('boom'))

    const result = await fn(99)

    expect(result.success).toBe(false)
    expect(result.error).toBe('boom')
  })

  describe('markJobApplied', () => {
    it('should create an application, backfill the link and set status=applied atomically', async () => {
      const posting = {
        id: 7,
        company_name: 'Acme',
        job_title: 'Backend Engineer',
        job_url: 'https://acme.example/jobs/7',
        pipeline_status: 'scored',
      }
      mockPrisma.job_postings.findUnique.mockResolvedValue(posting as any)
      // markJobApplied wraps create + backfill in a $transaction
      mockPrisma.$transaction.mockImplementation(async (cb: any) => cb(mockPrisma))
      mockPrisma.applications.findFirst.mockResolvedValue(null)
      mockPrisma.applications.create.mockResolvedValue({ id: 42, company_name: 'Acme', job_title: 'Backend Engineer' } as any)
      mockPrisma.job_postings.update.mockResolvedValue({ ...posting, pipeline_status: 'applied', application_id: 42 } as any)

      const result = await markJobApplied(7)

      expect(result.success).toBe(true)
      expect(mockPrisma.$transaction).toHaveBeenCalled()
      expect(mockPrisma.applications.create).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            company_name: 'Acme',
            job_title: 'Backend Engineer',
            application_url: 'https://acme.example/jobs/7',
            status: 'Applied',
          }),
        })
      )
      expect(mockPrisma.job_postings.update).toHaveBeenCalledWith(
        expect.objectContaining({
          where: { id: 7 },
          data: expect.objectContaining({
            pipeline_status: 'applied',
            application_id: 42,
          }),
        })
      )
    })

    it('keeps the chosen category, defaulting a blank one to Others', async () => {
      const posting = { id: 7, company_name: 'Acme', job_title: 'Backend Engineer', job_url: 'u', pipeline_status: 'scored' }
      mockPrisma.job_postings.findUnique.mockResolvedValue(posting as any)
      mockPrisma.$transaction.mockImplementation(async (cb: any) => cb(mockPrisma))
      mockPrisma.applications.findFirst.mockResolvedValue(null)
      mockPrisma.applications.create.mockResolvedValue({ id: 42 } as any)
      mockPrisma.job_postings.update.mockResolvedValue({} as any)

      await markJobApplied(7, 'MLE')
      expect(mockPrisma.applications.create).toHaveBeenCalledWith(
        expect.objectContaining({ data: expect.objectContaining({ category: 'MLE' }) })
      )

      mockPrisma.applications.create.mockClear()
      await markJobApplied(7, '   ')
      expect(mockPrisma.applications.create).toHaveBeenCalledWith(
        expect.objectContaining({ data: expect.objectContaining({ category: 'Others' }) })
      )
    })

    it('should fail and not update the posting when the application is a duplicate', async () => {
      const posting = {
        id: 7,
        company_name: 'Acme',
        job_title: 'Backend Engineer',
        job_url: 'https://acme.example/jobs/7',
        pipeline_status: 'scored',
      }
      mockPrisma.job_postings.findUnique.mockResolvedValue(posting as any)
      mockPrisma.$transaction.mockImplementation(async (cb: any) => cb(mockPrisma))
      mockPrisma.applications.findFirst.mockResolvedValue({ id: 1 } as any) // duplicate

      const result = await markJobApplied(7)

      expect(result.success).toBe(false)
      expect(mockPrisma.job_postings.update).not.toHaveBeenCalled()
    })

    it('should fail when the posting does not exist', async () => {
      mockPrisma.job_postings.findUnique.mockResolvedValue(null)

      const result = await markJobApplied(123)

      expect(result.success).toBe(false)
      expect(mockPrisma.$transaction).not.toHaveBeenCalled()
    })
  })
})
