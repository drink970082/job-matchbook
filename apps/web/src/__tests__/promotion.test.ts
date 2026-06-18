import { prisma } from '@/lib/db'
import {
  getPromotionSuggestions,
  dismissPromotion,
} from '@/lib/promotion-actions'
import { mockDeep, mockReset } from 'jest-mock-extended'
import { PrismaClient, Prisma } from '@prisma/client'

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

describe('Promotion actions', () => {
  describe('getPromotionSuggestions', () => {
    it('shapes rows and coerces numeric fields (BigInt -> Number)', async () => {
      // SQLite SUM/COUNT can come back as BigInt; the action must coerce.
      mockPrisma.$queryRawUnsafe.mockResolvedValue([
        {
          source: 'greenhouse',
          slug: 'acme',
          name: 'Acme',
          applied: BigInt(2),
          highScores: BigInt(3),
          total: 5,
        },
      ] as any)

      const { data } = await getPromotionSuggestions()

      expect(data).toEqual([
        { source: 'greenhouse', slug: 'acme', name: 'Acme', applied: 2, highScores: 3, total: 5 },
      ])
      // Coerced to plain numbers, not BigInt.
      expect(typeof data[0].applied).toBe('number')
      expect(typeof data[0].highScores).toBe('number')
      expect(typeof data[0].total).toBe('number')
      expect(mockPrisma.$queryRawUnsafe).toHaveBeenCalled()
    })

    it('returns an empty array when nothing qualifies', async () => {
      mockPrisma.$queryRawUnsafe.mockResolvedValue([] as any)
      const { data } = await getPromotionSuggestions()
      expect(data).toEqual([])
    })
  })

  describe('dismissPromotion', () => {
    it('creates a promotion_dismissed row (trimmed) and returns success', async () => {
      mockPrisma.promotion_dismissed.create.mockResolvedValue({ id: 1 } as any)

      const result = await dismissPromotion(' greenhouse ', ' acme ')

      expect(result.success).toBe(true)
      expect(mockPrisma.promotion_dismissed.create).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({ source: 'greenhouse', slug: 'acme' }),
        })
      )
    })

    it('rejects missing fields without creating', async () => {
      const result = await dismissPromotion('greenhouse', '')
      expect(result.success).toBe(false)
      expect(mockPrisma.promotion_dismissed.create).not.toHaveBeenCalled()
    })

    it('is idempotent on a duplicate (source, slug) unique violation', async () => {
      const dupErr = new Prisma.PrismaClientKnownRequestError('Unique constraint failed', {
        code: 'P2002',
        clientVersion: 'test',
      })
      mockPrisma.promotion_dismissed.create.mockRejectedValue(dupErr)

      const result = await dismissPromotion('greenhouse', 'acme')
      expect(result.success).toBe(true)
    })

    it('surfaces an unexpected create error as a failure', async () => {
      mockPrisma.promotion_dismissed.create.mockRejectedValue(new Error('boom'))
      const result = await dismissPromotion('greenhouse', 'acme')
      expect(result.success).toBe(false)
      expect(result.error).toBe('boom')
    })
  })
})
