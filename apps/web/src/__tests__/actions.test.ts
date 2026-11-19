import { prisma } from '@/lib/db'
import { getApplications, addApplication, updateApplicationStatus, updateApplicationDetails } from '@/lib/application-actions'
import { getKPIs } from '@/lib/analytics-actions'
import { markJobApplied } from '@/lib/job-actions'
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
        orderBy: [{ date_applied: 'desc' }, { id: 'desc' }]
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
      const newStatus = 'Interviewing'
      
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
      const recent = new Date().toISOString()
      const mockApps = [
        { status: 'Applied', last_updated: recent, date_applied: '2026-01-01' },
        { status: 'Applied', last_updated: null, date_applied: '2020-01-01' }, // silent > 60 days
        { status: 'Rejected', last_updated: recent, date_applied: '2026-01-01' },
        { status: 'Offer', last_updated: recent, date_applied: '2026-01-01' },
        { status: 'Interviewing', last_updated: recent, date_applied: '2026-01-01' },
      ]

      mockPrisma.applications.findMany.mockResolvedValue(mockApps as any)

      const kpis = await getKPIs()

      expect(kpis.total).toBe(5)
      expect(kpis.rejected).toBe(1)
      expect(kpis.offer).toBe(1)
      expect(kpis.interviewing).toBe(1)
      expect(kpis.active).toBe(2) // recent Applied + Interviewing
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
      mockPrisma.$queryRaw.mockResolvedValue([{ id: 7 }] as any)
      mockPrisma.job_postings.findUnique.mockResolvedValue(posting as any)
      // markJobApplied wraps create + backfill in a $transaction
      mockPrisma.$transaction.mockImplementation(async (cb: any) => cb(mockPrisma))
      mockPrisma.applications.findFirst.mockResolvedValue(null)
      mockPrisma.applications.create.mockResolvedValue({ id: 42, company_name: 'Acme', job_title: 'Backend Engineer' } as any)
      mockPrisma.job_postings.updateMany.mockResolvedValue({ count: 1 } as any)

      const result = await markJobApplied(7, undefined, { stage: 'all' })

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
      expect(mockPrisma.job_postings.updateMany).toHaveBeenCalledWith(
        expect.objectContaining({
          where: expect.objectContaining({ id: 7 }),
          data: expect.objectContaining({
            pipeline_status: 'applied',
            application_id: 42,
          }),
        })
      )
    })

    it('keeps the chosen category, defaulting a blank one to Others', async () => {
      const posting = { id: 7, company_name: 'Acme', job_title: 'Backend Engineer', job_url: 'u', pipeline_status: 'scored' }
      mockPrisma.$queryRaw.mockResolvedValue([{ id: 7 }] as any)
      mockPrisma.job_postings.findUnique.mockResolvedValue(posting as any)
      mockPrisma.$transaction.mockImplementation(async (cb: any) => cb(mockPrisma))
      mockPrisma.applications.findFirst.mockResolvedValue(null)
      mockPrisma.applications.create.mockResolvedValue({ id: 42 } as any)
      mockPrisma.job_postings.updateMany.mockResolvedValue({ count: 1 } as any)

      await markJobApplied(7, 'MLE', { stage: 'all' })
      expect(mockPrisma.applications.create).toHaveBeenCalledWith(
        expect.objectContaining({ data: expect.objectContaining({ category: 'MLE' }) })
      )

      mockPrisma.applications.create.mockClear()
      await markJobApplied(7, '   ', { stage: 'all' })
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
      mockPrisma.$queryRaw.mockResolvedValue([{ id: 7 }] as any)
      mockPrisma.job_postings.findUnique.mockResolvedValue(posting as any)
      mockPrisma.$transaction.mockImplementation(async (cb: any) => cb(mockPrisma))
      mockPrisma.applications.findFirst.mockResolvedValue({ id: 1 } as any) // duplicate

      const result = await markJobApplied(7, undefined, { stage: 'all' })

      expect(result.success).toBe(false)
      expect(mockPrisma.job_postings.updateMany).not.toHaveBeenCalled()
    })

    it('should fail when the posting does not exist', async () => {
      mockPrisma.$queryRaw.mockResolvedValue([] as any)
      mockPrisma.$transaction.mockImplementation(async (callback: any) => callback(mockPrisma))
      mockPrisma.job_postings.findUnique.mockResolvedValue(null)

      const result = await markJobApplied(123, undefined, { stage: 'all' })

      expect(result.success).toBe(false)
      expect(mockPrisma.$transaction).toHaveBeenCalled()
    })
  })
})
