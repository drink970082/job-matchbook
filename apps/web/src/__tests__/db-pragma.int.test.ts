/** The web Prisma connection must carry busy_timeout so a worker write-lock makes
 *  web block-and-retry (up to 5s) instead of throwing SQLITE_BUSY. */
import { prisma } from '@/test-utils/db'

afterAll(() => prisma.$disconnect())

test('Prisma connection has busy_timeout >= 5000ms', async () => {
    const rows = await prisma.$queryRawUnsafe<Array<{ timeout: number | bigint }>>(
        'PRAGMA busy_timeout'
    )
    expect(Number(rows[0].timeout)).toBeGreaterThanOrEqual(5000)
})
