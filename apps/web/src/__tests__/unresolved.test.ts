import { prisma } from '@/lib/db'
import { getUnresolvedFeeds } from '@/lib/unresolved-actions'
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

describe('getUnresolvedFeeds', () => {
  it('shapes groupBy rows into { host, reason, count } and totals them', async () => {
    mockPrisma.feed_unresolved.groupBy.mockResolvedValue([
      { host: 'a.com', reason: 'unsupported_host', _count: { _all: 2 } },
      { host: 'b.com', reason: 'workday_deferred', _count: { _all: 5 } },
    ] as any)

    const result = await getUnresolvedFeeds()

    expect(result.total).toBe(7)
    expect(result.data).toEqual([
      { host: 'b.com', reason: 'workday_deferred', count: 5 },
      { host: 'a.com', reason: 'unsupported_host', count: 2 },
    ])
  })

  it('sorts by count descending regardless of groupBy order', async () => {
    mockPrisma.feed_unresolved.groupBy.mockResolvedValue([
      { host: 'low.com', reason: 'unsupported_host', _count: { _all: 1 } },
      { host: 'high.com', reason: 'embedded_greenhouse', _count: { _all: 9 } },
      { host: 'mid.com', reason: 'workday_deferred', _count: { _all: 4 } },
    ] as any)

    const result = await getUnresolvedFeeds()

    expect(result.data.map((r) => r.count)).toEqual([9, 4, 1])
    expect(result.data.map((r) => r.host)).toEqual(['high.com', 'mid.com', 'low.com'])
    expect(result.total).toBe(14)
  })

  it('returns empty data and zero total when nothing is unresolved', async () => {
    mockPrisma.feed_unresolved.groupBy.mockResolvedValue([] as any)

    const result = await getUnresolvedFeeds()

    expect(result).toEqual({ data: [], total: 0 })
  })

  it('groups by both host and reason', async () => {
    mockPrisma.feed_unresolved.groupBy.mockResolvedValue([] as any)

    await getUnresolvedFeeds()

    expect(mockPrisma.feed_unresolved.groupBy).toHaveBeenCalledWith(
      expect.objectContaining({
        by: ['host', 'reason'],
        _count: { _all: true },
      })
    )
  })
})
