import { safeHref } from '@/lib/utils'

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
