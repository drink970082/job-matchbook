import type { Config } from 'jest'

/**
 * Aggregator config: runs BOTH the jsdom unit project and the node integration
 * project so a single `--coverage` run merges them into one report (and one
 * threshold gate that accounts for lines only the integration suite covers).
 */
const config: Config = {
    projects: ['<rootDir>/jest.config.ts', '<rootDir>/jest.integration.config.ts'],
    // Serial: a sub-project's maxWorkers is NOT honored under `projects`, and the
    // integration files share one SQLite file — parallel runs race. Serial across
    // all projects keeps the merged coverage run correct (it's small enough).
    maxWorkers: 1,
    coverageProvider: 'v8',
    collectCoverageFrom: [
        'src/lib/**/*.{ts,tsx}',
        'src/components/**/*.{ts,tsx}',
        '!src/components/ui/**',          // shadcn primitives, not our logic
        '!src/**/*.d.ts',
        '!src/**/__tests__/**',
    ],
    coveragePathIgnorePatterns: ['/node_modules/', '/src/test-utils/'],
    // Baseline floor set a few points under the first measurement; ratchet UP as
    // component tests are added, never down. Catches regressions immediately.
    coverageThreshold: {
        global: { statements: 48, branches: 73, functions: 45, lines: 48 },
    },
}

export default config
