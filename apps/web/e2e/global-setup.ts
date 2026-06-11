import { execSync } from 'node:child_process'
import { DATABASE_URL } from './helpers/db-path.mjs'

/** Create + schema-init the throwaway e2e DB (from the real Prisma schema) before
 * the web server (pointed at the same DB) starts. Data is owned by each spec's
 * `beforeEach` (seed/seedEmpty), so we only init the schema here. */
export default async function globalSetup() {
    execSync('npx prisma db push --skip-generate --accept-data-loss', {
        cwd: process.cwd(),
        env: { ...process.env, DATABASE_URL },
        stdio: 'inherit',
    })
}
