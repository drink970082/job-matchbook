import type { Config } from 'jest'
import nextJest from 'next/jest.js'

// Pin the timezone for every test worker. Several things under test are LOCAL-time by
// design — todayISO's date defaults, TimelineHeatmap's grid reference — so an unpinned
// TZ means the dev host (EDT) and CI (UTC) exercise different branches of the same
// code, and a local-vs-UTC bug passes on one and fails on the other. A negative-offset
// zone is the deliberate choice: it is where "UTC has already rolled over" bites.
//
// It must be set HERE rather than in a setup file: workers inherit env at fork time,
// and Node/ICU caches the zone before `setupFilesAfterEach` gets to run (reassigning
// process.env.TZ mid-suite is silently ignored there).
process.env.TZ = 'America/New_York'

const createJestConfig = nextJest({
    dir: './',
})

const config: Config = {
    coverageProvider: 'v8',
    testEnvironment: 'jsdom',
    setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
    moduleNameMapper: {
        '^@/(.*)$': '<rootDir>/src/$1',
    },
    // Integration tests (*.int.test.ts) run under the node-env project in
    // jest.integration.config.ts; Playwright e2e specs (e2e/*.spec.ts) run under
    // Playwright, not Jest. Exclude both from the fast jsdom unit run.
    testPathIgnorePatterns: ['/node_modules/', '/e2e/', '\\.int\\.test\\.ts$'],
}

export default createJestConfig(config)
