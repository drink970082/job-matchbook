import type { Config } from 'jest'
import nextJest from 'next/jest.js'

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
