// Single source of truth for the e2e throwaway DB path. Deliberately Prisma-free
// so playwright.config.ts can import it without loading the client. Deterministic
// path (not a random tmpdir) so config, global-setup, specs, and the CLI seeder
// all agree without a pointer file. NEVER the real db/applications.db.
import os from 'node:os'
import path from 'node:path'

export const E2E_DB_FILE = path.join(os.tmpdir(), 'ats-e2e.db')
export const DATABASE_URL = `file:${E2E_DB_FILE}`
export const E2E_PORT = 3100
