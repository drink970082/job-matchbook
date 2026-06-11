import type { Config } from 'jest'
import nextJest from 'next/jest.js'

// Integration project: real PrismaClient against a throwaway SQLite DB (created in
// globalSetup, pointed at via setEnv before @/lib/db loads). Node env, serial.
const createJestConfig = nextJest({ dir: './' })

const config: Config = {
    coverageProvider: 'v8',
    testEnvironment: 'node',
    testMatch: ['**/*.int.test.ts'],
    moduleNameMapper: {
        '^@/(.*)$': '<rootDir>/src/$1',
    },
    globalSetup: '<rootDir>/src/test-utils/integration/globalSetup.ts',
    globalTeardown: '<rootDir>/src/test-utils/integration/globalTeardown.ts',
    setupFiles: ['<rootDir>/src/test-utils/integration/setEnv.ts'],
    maxWorkers: 1,
}

export default createJestConfig(config)
