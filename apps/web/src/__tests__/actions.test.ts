import { prisma } from '@/lib/db'
import {
  getApplications,
  addApplication,
  updateApplicationStatus,
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

      mockPrisma.applications.findFirst.mockResolvedValue({ id: 1 } as any)

      const result = await addApplication(newApp)

      expect(result.success).toBe(false)
      expect(result.error).toContain('already exists')
      expect(mockPrisma.applications.create).not.toHaveBeenCalled()
    })
  })

  describe('updateApplicationStatus', () => {
    it('should update status and add history', async () => {
      const appId = 1
      const newStatus = 'Interviewing: 1st round'
      
      mockPrisma.applications.findUnique.mockResolvedValue({ id: appId, status: 'Applied' } as any)
      mockPrisma.$transaction.mockImplementation(async (callback) => await callback(mockPrisma))

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
    it('should default-filter to the actionable queue and order by score desc then id', async () => {
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      const result = await getJobPostings({})

      expect(result.total).toBe(0)
      expect(mockPrisma.job_postings.findMany).toHaveBeenCalledWith(
        expect.objectContaining({
          where: expect.objectContaining({
            AND: expect.arrayContaining([
              expect.objectContaining({
                pipeline_status: { in: ['scored', 'tailored', 'notified'] },
              }),
            ]),
          }),
          orderBy: [{ score: 'desc' }, { id: 'asc' }],
        })
      )
    })

    it('should allow an explicit status override', async () => {
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ status: 'applied' })

      expect(mockPrisma.job_postings.findMany).toHaveBeenCalledWith(
        expect.objectContaining({
          where: expect.objectContaining({
            AND: expect.arrayContaining([
              expect.objectContaining({ pipeline_status: 'applied' }),
            ]),
          }),
        })
      )
    })

    it("should not constrain pipeline_status when status='all'", async () => {
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ status: 'all' })

      const call = mockPrisma.job_postings.findMany.mock.calls[0][0] as any
      const serialized = JSON.stringify(call.where)
      expect(serialized).not.toContain('pipeline_status')
    })

    it('should apply minScore filter', async () => {
      mockPrisma.job_postings.findMany.mockResolvedValue([])
      mockPrisma.job_postings.count.mockResolvedValue(0)

      await getJobPostings({ minScore: 80 })

      expect(mockPrisma.job_postings.findMany).toHaveBeenCalledWith(
        expect.objectContaining({
          where: expect.objectContaining({
            AND: expect.arrayContaining([
              expect.objectContaining({ score: { gte: 80 } }),
            ]),
          }),
        })
      )
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
    it('should set pipeline_status to discarded', async () => {
      mockPrisma.job_postings.update.mockResolvedValue({ id: 1 } as any)

      const result = await discardJobPosting(1)

      expect(result.success).toBe(true)
      expect(mockPrisma.job_postings.update).toHaveBeenCalledWith(
        expect.objectContaining({
          where: { id: 1 },
          data: expect.objectContaining({ pipeline_status: 'discarded' }),
        })
      )
    })

    it('should return error on failure', async () => {
      mockPrisma.job_postings.update.mockRejectedValue(new Error('boom'))

      const result = await discardJobPosting(99)

      expect(result.success).toBe(false)
      expect(result.error).toBe('boom')
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

    it('should return error on failure', async () => {
      mockPrisma.job_postings.update.mockRejectedValue(new Error('boom'))

      const result = await reopenJobPosting(99)

      expect(result.success).toBe(false)
      expect(result.error).toBe('boom')
    })
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
