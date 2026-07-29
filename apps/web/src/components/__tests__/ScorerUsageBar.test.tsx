import { windowLabel, formatResetsIn, backendLabel } from '@/components/ScorerUsageBar'

describe('windowLabel', () => {
    test('maps the known windows to friendly names', () => {
        expect(windowLabel({ window_minutes: 10080, key: 'primary' })).toBe('weekly')
        expect(windowLabel({ window_minutes: 300, key: 'session' })).toBe('5h')
    })
    test('falls back to minutes, then to a generic label', () => {
        expect(windowLabel({ window_minutes: 45, key: 'x' })).toBe('45m')
        expect(windowLabel({ window_minutes: null, key: 'x' })).toBe('usage')
    })
    test('carries a model scope through so two weekly rows are distinguishable', () => {
        // Claude returns weekly_all beside a model-scoped weekly row; a bare "weekly"
        // on both would read as one number contradicting the other.
        expect(windowLabel({ window_minutes: 10080, key: 'weekly_all' })).toBe('weekly')
        expect(windowLabel({ window_minutes: 10080, key: 'weekly_scoped (Fable)' }))
            .toBe('weekly · Fable')
    })
})

describe('backendLabel', () => {
    test('names which provider the numbers describe', () => {
        expect(backendLabel('codex')).toBe('Codex')
        expect(backendLabel('claude')).toBe('Claude Code')
    })
    test('an absent/unknown backend degrades to a neutral label, never a guess', () => {
        expect(backendLabel(null)).toBe('Scorer')
        expect(backendLabel('gemini')).toBe('Scorer')
    })
})

describe('formatResetsIn', () => {
    const now = 1_000_000 // fixed epoch seconds for determinism
    test('formats days + hours out', () => {
        expect(formatResetsIn(now + 2 * 86400 + 3 * 3600, now)).toBe('resets in 2d 3h')
    })
    test('drops the day part under 24h', () => {
        expect(formatResetsIn(now + 5 * 3600, now)).toBe('resets in 5h')
    })
    test('past reset reads as resetting; null is blank', () => {
        expect(formatResetsIn(now - 1, now)).toBe('resetting')
        expect(formatResetsIn(null, now)).toBe('')
    })
})
