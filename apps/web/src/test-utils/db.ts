/**
 * Integration-test DB helpers. Imports the SAME `prisma` singleton the server
 * actions use (already pointed at the throwaway DB via setEnv.ts), so assertions
 * read exactly what the actions wrote. Call resetDb() in beforeEach for isolation.
 */
import { prisma } from '@/lib/db'

export { prisma }

export async function resetDb() {
    // Children first (status_history -> applications; job_postings -> applications).
    await prisma.$executeRawUnsafe('DELETE FROM status_history')
    await prisma.$executeRawUnsafe('DELETE FROM job_postings')
    await prisma.$executeRawUnsafe('DELETE FROM applications')
    // Reset AUTOINCREMENT counters so ids are deterministic per test.
    await prisma.$executeRawUnsafe(
        "DELETE FROM sqlite_sequence WHERE name IN ('applications','job_postings','status_history')"
    )
}
