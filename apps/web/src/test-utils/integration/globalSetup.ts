/**
 * Jest globalSetup for the integration project: create a throwaway SQLite DB and
 * initialise it from the real Prisma schema (the single source of truth). The DB
 * URL is handed to the test workers through `process.env` (workers inherit the
 * parent's env), so concurrent runs in other checkouts never share a pointer.
 * `setEnv.ts` reads it to point DATABASE_URL at this DB BEFORE `@/lib/db`
 * constructs its PrismaClient.
 */
import { execSync } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export const IT_DB_URL = 'ATS_IT_DB_URL'
export const IT_DB_DIR = 'ATS_IT_DB_DIR'

export default async function globalSetup() {
    const dir = mkdtempSync(join(tmpdir(), 'ats-it-'))
    const url = `file:${join(dir, 'it.db')}`
    // Build the schema from prisma/schema.prisma (no migrations in this repo).
    // --skip-generate: the client is already generated; offline-capable.
    execSync('npx prisma db push --skip-generate --accept-data-loss', {
        cwd: process.cwd(),
        env: { ...process.env, DATABASE_URL: url },
        stdio: 'inherit',
    })
    process.env[IT_DB_URL] = url
    process.env[IT_DB_DIR] = dir
}
