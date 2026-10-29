import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { normalizeAssessmentView } from '@/lib/assessment-view'

const workerRoot = resolve(__dirname, '../../../../worker')
const fixture = JSON.parse(readFileSync(
    resolve(workerRoot, 'tests/fixtures/preselection_assessment_contract.json'),
    'utf8',
)) as {
    cases: Array<{
        name: string
        expected_assessment_state: string
        expected_latest_attempt_state: string
    }>
}

let projectedCases: Map<string, unknown> | undefined

function projectCase(name: string): unknown {
    if (!projectedCases) {
        const result = spawnSync('python3', [
            '-m',
            'ats_worker.preselection_view_cli',
            '--fixture',
            'tests/fixtures/preselection_assessment_contract.json',
            '--all',
        ], { cwd: workerRoot, encoding: 'utf8' })
        if (result.status !== 0) {
            throw new Error(`Python fixture CLI failed: ${result.error?.message ?? 'no status'} ${result.stderr}`)
        }
        const report = JSON.parse(result.stdout) as {
            scope: string
            synthetic: boolean
            cases: Array<{ name: string; view: unknown }>
        }
        if (report.scope !== 'synthetic_assessment_cases' || report.synthetic !== true) {
            throw new Error('Python fixture CLI returned an invalid case report')
        }
        projectedCases = new Map(report.cases.map((item) => [item.name, item.view]))
    }
    const result = projectedCases.get(name)
    if (!result) throw new Error(`Python fixture CLI omitted case ${name}`)
    return result
}

describe('Python/TypeScript synthetic assessment contract', () => {
    it.each(fixture.cases)('$name', (scenario) => {
        const view = normalizeAssessmentView(projectCase(scenario.name))

        expect(view.assessment_state).toBe(scenario.expected_assessment_state)
        expect(view.latest_attempt.state).toBe(scenario.expected_latest_attempt_state)
        expect(JSON.stringify(view)).not.toContain('SYNTHETIC_PRIVATE_')
        if (view.assessment_state === 'unknown' || view.assessment_state === 'not_assessed') {
            expect(view.components).toEqual([])
            expect(view.assessment_time).toBeNull()
            expect(view.metadata).toBeNull()
        }
    })

    it('treats a future view schema as unsupported without reusing old values', () => {
        const normalized = normalizeAssessmentView({
            schema_version: 2,
            scope: 'synthetic_assessment_view',
            synthetic: true,
            components: [{ id: 'old-value', score: 100 }],
        })

        expect(normalized.assessment_state).toBe('unknown')
        expect(normalized.assessment_reason).toBe('unsupported_schema')
        expect(normalized.components).toEqual([])
    })

    it('fails closed when a projected view contains private or malformed data', () => {
        const projected = projectCase('current_success') as {
            metadata: Record<string, unknown>
            components: Array<Record<string, unknown>>
            [key: string]: unknown
        }
        const untrusted = JSON.parse(JSON.stringify(projected)) as typeof projected
        untrusted.metadata.content_digest = 'SYNTHETIC_PRIVATE_DIGEST'
        const normalized = normalizeAssessmentView(untrusted)

        expect(normalized.assessment_state).toBe('unknown')
        expect(normalized.components).toEqual([])
        expect(JSON.stringify(normalized)).not.toContain('SYNTHETIC_PRIVATE_DIGEST')
    })

    it('does not turn a malformed component value into a zero score', () => {
        const projected = projectCase('current_success') as {
            components: Array<Record<string, unknown>>
            [key: string]: unknown
        }
        const untrusted = JSON.parse(JSON.stringify(projected)) as typeof projected
        untrusted.components[0].score = '0'
        const normalized = normalizeAssessmentView(untrusted)

        expect(normalized.assessment_state).toBe('unknown')
        expect(normalized.components).toEqual([])
    })
})
