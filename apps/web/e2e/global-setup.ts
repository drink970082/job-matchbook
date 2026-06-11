import { execSync } from 'node:child_process'
import { DATABASE_URL } from './helpers/db-path.mjs'
import { seed } from './helpers/seed.mjs'

/** Create + schema-init the throwaway e2e DB (from the real Prisma schema) and
 * seed deterministic fixtures, before the web server (pointed at the same DB)
 * starts. */
export default async function globalSetup() {
    execSync('npx prisma db push --skip-generate --accept-data-loss', {
        cwd: process.cwd(),
        env: { ...process.env, DATABASE_URL },
        stdio: 'inherit',
    })
    await seed()
}
