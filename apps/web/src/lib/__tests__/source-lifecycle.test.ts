import { sourceLifecycleSummary } from '../source-lifecycle'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const timestampContract: {
    assessment_time_cases: Array<{
        name: string
        stored_updated_at: string
        expected_summary_time: string | null
    }>
} = JSON.parse(readFileSync(
    resolve(__dirname, '../../../../worker/tests/fixtures/standalone_screen_contract.json'),
    'utf8',
))

describe('source lifecycle summary', () => {
    const posting = {
        source_state: 'available',
        source_last_seen_at: '2026-10-22T10:00:00Z',
        source_last_check_attempted_at: '2026-10-23T10:00:00Z',
        source_last_checked_at: '2026-10-22T09:00:00Z',
        source_last_check_outcome: 'inconclusive',
        source_last_check_error_category: 'timeout',
        source_content_revision: 2,
        score_detail: JSON.stringify({
            assessment: { domain: { verdict: 'match' } },
            screen: { degree: { pass: true } },
            source_content_revision: 1,
        }),
    }

    it('keeps the confirmed source state separate from a failed recent attempt', () => {
        expect(sourceLifecycleSummary(posting, {
            state: 'complete', source_content_revision: 2,
        })).toEqual({
            state: 'available',
            last_seen_at: '2026-10-22T10:00:00Z',
            last_check_attempted_at: '2026-10-23T10:00:00Z',
            last_checked_at: '2026-10-22T09:00:00Z',
            last_check_outcome: 'inconclusive',
            last_check_error_category: 'timeout',
            content_revision: 2,
            fit_freshness: 'stale',
            screen_freshness: 'current',
            combined_screen_freshness: 'stale',
        })
    })

    it('reports legacy evidence as unknown and keeps provider errors distinct', () => {
        expect(sourceLifecycleSummary({
            ...posting,
            source_content_revision: null,
            score_detail: '{"assessment":{"domain":{}}}',
        }, { state: 'provider_error', source_content_revision: null })).toMatchObject({
            fit_freshness: 'unknown',
            screen_freshness: 'provider_error',
        })
    })

    it('does not classify malformed or empty assessment data as a fit verdict', () => {
        expect(sourceLifecycleSummary({ ...posting, score_detail: '{bad json' }).fit_freshness)
            .toBe('not_assessed')
        expect(sourceLifecycleSummary({
            ...posting, score_detail: '{"assessment":{}}',
        }).fit_freshness).toBe('not_assessed')
    })

    it.each(timestampContract.assessment_time_cases)(
        'validates source timestamp with the shared calendar/offset contract: $name',
        (timeCase) => {
            expect(sourceLifecycleSummary({
                ...posting,
                source_last_seen_at: timeCase.stored_updated_at,
                source_last_check_attempted_at: timeCase.stored_updated_at,
                source_last_checked_at: timeCase.stored_updated_at,
            })).toMatchObject({
                last_seen_at: timeCase.expected_summary_time,
                last_check_attempted_at: timeCase.expected_summary_time,
                last_checked_at: timeCase.expected_summary_time,
            })
        },
    )

    it.each([0, -1, true, Number.MAX_SAFE_INTEGER + 1])(
        'treats invalid standalone screen revision %p as unknown',
        (screenRevision) => {
            expect(sourceLifecycleSummary(posting, {
                state: 'complete', source_content_revision: screenRevision,
            }).screen_freshness).toBe('unknown')
        },
    )

    it('treats an unsafe current posting revision as unknown for every assessment', () => {
        expect(sourceLifecycleSummary({
            ...posting,
            source_content_revision: Number.MAX_SAFE_INTEGER + 1,
        }, { state: 'complete', source_content_revision: 1 })).toMatchObject({
            content_revision: null,
            fit_freshness: 'unknown',
            screen_freshness: 'unknown',
            combined_screen_freshness: 'unknown',
        })
    })
})
