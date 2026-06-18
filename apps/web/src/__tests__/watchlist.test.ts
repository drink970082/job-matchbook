import { prisma } from '@/lib/db'
import {
  getWatchedCompanies,
  addWatchedCompany,
  removeWatchedCompany,
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

describe('Watchlist actions', () => {
  describe('getWatchedCompanies', () => {
    it('returns { data, total }, ordered by name', async () => {
      const rows = [{ id: 1, source: 'greenhouse', slug: 'acme', name: 'Acme' }]
      mockPrisma.watched_companies.findMany.mockResolvedValue(rows as any)
      mockPrisma.watched_companies.count.mockResolvedValue(1)

      const result = await getWatchedCompanies()

      expect(result).toEqual({ data: rows, total: 1 })
      expect(mockPrisma.watched_companies.findMany).toHaveBeenCalledWith(
        expect.objectContaining({ orderBy: { name: 'asc' } })
      )
    })
  })

  describe('addWatchedCompany', () => {
    it('creates a company (trimmed) when valid and new', async () => {
      mockPrisma.watched_companies.findFirst.mockResolvedValue(null)
      mockPrisma.watched_companies.create.mockResolvedValue({ id: 1 } as any)

      const result = await addWatchedCompany({ source: 'ashby', slug: ' acme ', name: ' Acme ' })

      expect(result.success).toBe(true)
      expect(mockPrisma.watched_companies.create).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({ source: 'ashby', slug: 'acme', name: 'Acme' }),
        })
      )
    })

    it('rejects an unknown source without creating', async () => {
      const result = await addWatchedCompany({ source: 'linkedin', slug: 'x', name: 'X' })
      expect(result.success).toBe(false)
      expect(mockPrisma.watched_companies.create).not.toHaveBeenCalled()
    })

    it('rejects missing fields', async () => {
      const result = await addWatchedCompany({ source: 'greenhouse', slug: '', name: 'X' })
      expect(result.success).toBe(false)
      expect(mockPrisma.watched_companies.create).not.toHaveBeenCalled()
    })

    it('rejects a duplicate (source, slug)', async () => {
      mockPrisma.watched_companies.findFirst.mockResolvedValue({ id: 9 } as any)
      const result = await addWatchedCompany({ source: 'lever', slug: 'foobar', name: 'Foobar' })
      expect(result.success).toBe(false)
      expect(mockPrisma.watched_companies.create).not.toHaveBeenCalled()
    })
  })

  describe('removeWatchedCompany', () => {
    it('deletes by id', async () => {
      mockPrisma.watched_companies.delete.mockResolvedValue({ id: 1 } as any)
      const result = await removeWatchedCompany(1)
      expect(result.success).toBe(true)
      expect(mockPrisma.watched_companies.delete).toHaveBeenCalledWith({ where: { id: 1 } })
    })
  })
})
