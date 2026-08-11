import { safeHref, todayISO } from '@/lib/utils'

test('passes http/https through', () => {
    expect(safeHref('https://acme.example/jobs/1')).toBe('https://acme.example/jobs/1')
    expect(safeHref('http://x.test/a')).toBe('http://x.test/a')
})

test('neutralizes dangerous or empty hrefs to #', () => {
    expect(safeHref('javascript:alert(1)')).toBe('#')
    expect(safeHref('data:text/html,<script>')).toBe('#')
    expect(safeHref('')).toBe('#')
    expect(safeHref(null)).toBe('#')
})

describe('todayISO', () => {
    afterEach(() => {
        jest.useRealTimers()
    })

    test('returns a bare YYYY-MM-DD date, no time part', () => {
        expect(todayISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    })

    // The property that matters, and the one that would break if someone "helpfully"
    // switched this to a local-time getFullYear/getMonth/getDate build: the boundary
    // is UTC midnight, not the viewer's. At 20:30 US Eastern on the 1st it is already
    // the 2nd in UTC, and this must say so — five call sites behaved that way before
    // the helper existed. TimelineHeatmap is the deliberate exception and computes its
    // own LOCAL reference; see the comment on todayISO.
    test('rolls over at UTC midnight, not local midnight', () => {
        jest.useFakeTimers().setSystemTime(new Date('2026-06-02T00:30:00Z'))
        expect(todayISO()).toBe('2026-06-02')

        jest.useFakeTimers().setSystemTime(new Date('2026-06-01T23:30:00Z'))
        expect(todayISO()).toBe('2026-06-01')
    })
})
