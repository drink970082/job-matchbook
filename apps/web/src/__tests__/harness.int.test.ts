import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication } from '@/test-utils/factories'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

test('integration harness: real PrismaClient round-trips against the temp DB', async () => {
    const created = await prisma.applications.create({ data: makeApplication() })
    expect(created.id).toBe(1) // sequence reset by resetDb
    const all = await prisma.applications.findMany()
    expect(all).toHaveLength(1)
    expect(all[0].company_name).toBe('Acme')
})
