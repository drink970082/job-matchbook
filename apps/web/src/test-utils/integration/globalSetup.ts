/**
 * Jest globalSetup for the integration project: create a throwaway SQLite DB and
 * initialise it from the real Prisma schema (the single source of truth). The DB
 * path is written to a pointer file because globalSetup runs in a separate process
 * from the test workers — `setEnv.ts` reads it to point DATABASE_URL at this DB
 * BEFORE `@/lib/db` constructs its PrismaClient.
 */
import { execSync } from 'node:child_process'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export const POINTER = join(tmpdir(), 'ats-integration-db.json')

export default async function globalSetup() {
    const dir = mkdtempSync(join(tmpdir(), 'ats-it-'))
    const dbFile = join(dir, 'it.db')
    const url = `file:${dbFile}`
    // Build the schema from prisma/schema.prisma (no migrations in this repo).
    // --skip-generate: the client is already generated; offline-capable.
    execSync('npx prisma db push --skip-generate --accept-data-loss', {
        cwd: process.cwd(),
        env: { ...process.env, DATABASE_URL: url },
        stdio: 'inherit',
    })
    writeFileSync(POINTER, JSON.stringify({ dir, url }))
}
