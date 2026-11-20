import { readFileSync } from 'node:fs'
import path from 'node:path'
import { nameFromSlug, resolveBoardUrl } from '@/lib/board-url'

// Shared with the worker (tests/test_board_url_cases.py), so the resolvers cannot drift.
const CASES: { url: string; source: string | null; slug: string | null }[] = JSON.parse(readFileSync(
    path.join(__dirname, '../../../../worker/tests/fixtures/board-url-cases.json'), 'utf8')).cases

test.each(CASES.map((c) => [c.url, c] as const))('%s', (_url, c) => {
    expect(resolveBoardUrl(c.url)).toEqual(c.source ? { source: c.source, slug: c.slug } : null)
})

test('nameFromSlug', () => {
    expect(nameFromSlug('acme-robotics')).toBe('Acme Robotics')
    expect(nameFromSlug('nvidia/wd5/site')).toBe('Nvidia')
})
