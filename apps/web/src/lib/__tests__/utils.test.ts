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

// Runs under the TZ pinned in jest.config.ts (America/New_York) — these assertions are
// only meaningful in a zone whose offset is negative, and an unpinned TZ would make
// them tautological on a UTC CI runner.
describe('todayISO', () => {
    afterEach(() => {
        jest.useRealTimers()
    })

    test('returns a bare YYYY-MM-DD date, no time part', () => {
        expect(todayISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    })

    // The property that matters: the boundary is the VIEWER'S midnight, not UTC's.
    // At 20:30 US Eastern on the 1st it is already the 2nd in UTC, and a form
    // pre-filled from here must still offer the 1st.
    test('rolls over at local midnight, not UTC midnight', () => {
        jest.useFakeTimers().setSystemTime(new Date('2026-06-02T00:30:00Z'))
        expect(todayISO()).toBe('2026-06-01')

        jest.useFakeTimers().setSystemTime(new Date('2026-06-02T05:30:00Z'))
        expect(todayISO()).toBe('2026-06-02')
    })

    // Zero-padded on both fields — a bare `${d.getMonth() + 1}` build emits '2026-6-2',
    // which every consumer here (a date input, a CSV filename, date_applied) reads wrong.
    test('zero-pads single-digit months and days', () => {
        jest.useFakeTimers().setSystemTime(new Date('2026-06-02T12:00:00Z'))
        expect(todayISO()).toBe('2026-06-02')
    })
})
