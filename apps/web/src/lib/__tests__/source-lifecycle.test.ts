import { sourceLifecycleSummary } from '../source-lifecycle'

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
})
