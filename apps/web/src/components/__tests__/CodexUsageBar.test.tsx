import { windowLabel, formatResetsIn } from '@/components/CodexUsageBar'

describe('windowLabel', () => {
    test('maps the known codex windows to friendly names', () => {
        expect(windowLabel({ window_minutes: 10080 })).toBe('weekly')
        expect(windowLabel({ window_minutes: 300 })).toBe('5h')
    })
    test('falls back to minutes, then to a generic label', () => {
        expect(windowLabel({ window_minutes: 45 })).toBe('45m')
        expect(windowLabel({ window_minutes: null })).toBe('usage')
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
