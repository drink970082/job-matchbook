import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { jobTriageSummary } from '@/lib/triage-summary'

const fixture = JSON.parse(readFileSync(
    resolve(__dirname, '../../../../worker/tests/fixtures/job_triage_contract.json'),
    'utf8',
))

describe('job triage contract fixture', () => {
    it.each(fixture.cases)('$name', (...args: any[]) => {
        const item = args[0]
        const screening = item.screening && {
            id: 1,
            state: item.screening.state,
            result_json: item.screening.result_json_raw,
            error_message: item.screening.error_message ?? null,
        }
        const summary = jobTriageSummary(
            item.pipeline_status,
            item.score_detail_raw,
            screening,
        )

        expect(summary.status).toBe(item.expected_status)
        expect(summary.provenance).toBe(item.expected_provenance)
        expect(typeof summary.reason).toBe('string')
        expect(summary.reason.length).toBeLessThanOrEqual(300)
        expect(summary.reason).not.toContain('Synthetic private error text')
    })
})
