import { defineConfig, devices } from '@playwright/test'
import { DATABASE_URL, E2E_PORT } from './e2e/helpers/db-path.mjs'

// E2E against a throwaway seeded SQLite. The schema is pushed into that DB as
// part of the webServer command itself, before the server boots (globalSetup
// runs too late — Playwright starts webServer as a plugin-setup task ahead of
// it, so the server would come up against a schema-less DB). Per-spec data
// seeding still happens in each spec's beforeEach (see e2e/helpers/seed.mjs).
// The web server is built + started bound to that DB on a dedicated port
// (3100, distinct from dev's 3000) — the real db/applications.db is never touched.
export default defineConfig({
    testDir: './e2e',
    testMatch: '**/*.spec.ts',
    fullyParallel: false, // specs share one SQLite file; re-seed per test, run serial
    workers: 1,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 2 : 0,
    reporter: process.env.CI
        ? [['github'], ['html', { open: 'never' }], ['list']]
        : [['list'], ['html', { open: 'never' }]],
    use: {
        baseURL: `http://localhost:${E2E_PORT}`,
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
    },
    projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
    webServer: {
        command: `npm run build && npx prisma db push --skip-generate --accept-data-loss && npm run start -- -p ${E2E_PORT}`,
        url: `http://localhost:${E2E_PORT}`,
        timeout: 180_000,
        reuseExistingServer: !process.env.CI,
        env: { DATABASE_URL },
    },
})
