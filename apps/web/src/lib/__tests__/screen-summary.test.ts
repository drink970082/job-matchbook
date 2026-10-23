import { standaloneScreenSummary } from '@/lib/screen-summary'

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
