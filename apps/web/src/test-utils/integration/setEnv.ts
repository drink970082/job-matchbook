/**
 * Runs in each worker (jest `setupFiles`) BEFORE any test module — and therefore
 * before `@/lib/db` is imported — so the PrismaClient it builds at module load
 * targets the throwaway integration DB created by globalSetup, never the real one.
 */
import { readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const pointer = join(tmpdir(), 'ats-integration-db.json')
const { url } = JSON.parse(readFileSync(pointer, 'utf8'))
// Defense-in-depth: the integration DB is a throwaway temp file (it.db). Refuse
// to ever run against the real applications.db, no matter how the pointer got set.
if (typeof url !== 'string' || url.includes('applications.db')) {
    throw new Error(`integration setEnv refusing a non-throwaway DATABASE_URL: ${url}`)
}
process.env.DATABASE_URL = url
