import { standaloneScreenSummary } from '@/lib/screen-summary'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const contract: {
    assessment_time_cases: Array<{
        name: string
        stored_updated_at: string
        expected_known: boolean
        expected_summary_time: string | null
    }>
} = JSON.parse(readFileSync(
    resolve(__dirname, '../../../../worker/tests/fixtures/standalone_screen_contract.json'),
    'utf8',
))

test('provider error summary does not imply that a retry is scheduled', () => {
    const summary = standaloneScreenSummary({
        id: 1,
        state: 'provider_error',
        result_json: null,
        error_message: null,
        backend: 'synthetic',
        model: null,
        effort: null,
        evaluator_version: 'fixture-v1',
        updated_at: null,
    })

    expect(summary.outcome).toBe('provider_error')
    expect(summary.reason).toBe('Screening provider failed.')
    expect(summary.reason).not.toMatch(/retry/i)
})

test.each(contract.assessment_time_cases)(
    'assessment time contract case $name',
    (timeCase) => {
        const summary = standaloneScreenSummary({
            id: 1,
            state: 'provider_error',
            result_json: null,
            error_message: null,
            backend: 'synthetic',
            model: null,
            effort: null,
            evaluator_version: 'fixture-v1',
            updated_at: timeCase.stored_updated_at,
        })

        expect(summary.assessment_time).toBe(timeCase.expected_summary_time)
    },
)
