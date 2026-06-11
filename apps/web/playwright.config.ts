import { defineConfig, devices } from '@playwright/test'
import { DATABASE_URL, E2E_PORT } from './e2e/helpers/db-path.mjs'

// E2E against a throwaway seeded SQLite (see e2e/global-setup.ts). The web server
// is built + started bound to that DB on a dedicated port (3100, distinct from
// dev's 3000) — the real db/applications.db is never touched.
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
    globalSetup: './e2e/global-setup.ts',
    use: {
        baseURL: `http://localhost:${E2E_PORT}`,
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
    },
    projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
    webServer: {
        command: `npm run build && npm run start -- -p ${E2E_PORT}`,
        url: `http://localhost:${E2E_PORT}`,
        timeout: 180_000,
        reuseExistingServer: !process.env.CI,
        env: { DATABASE_URL },
    },
})
