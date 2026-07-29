/**
 * @jest-environment node
 */
// node env so the Web Request/Response globals next/server needs are present.
// Unit test for /api/scorer-usage: it serves the worker's quota snapshot, adds the
// file mtime as `as_of`, and degrades to an empty state (not a 500) when the file
// is absent — the worker may not have scored yet. See docs/SPEC.md §13.
jest.mock('node:fs', () => ({
    promises: { readFile: jest.fn(), stat: jest.fn() },
}))

import { promises as fs } from 'node:fs'
import { GET } from '@/app/api/scorer-usage/route'

const readFile = fs.readFile as unknown as jest.Mock
const stat = fs.stat as unknown as jest.Mock

beforeEach(() => {
    readFile.mockReset()
    stat.mockReset()
    process.env.SCORER_USAGE_FILE = '/data/scorer_usage.json'
})

test('serves the snapshot with as_of from the file mtime', async () => {
    const mtime = new Date('2026-07-17T11:27:00.000Z')
    readFile.mockResolvedValue(JSON.stringify({
        backend: 'codex',
        plan_type: 'plus',
        limits: [{ key: 'primary', used_percent: 32, window_minutes: 10080, resets_at: 1784839672 }],
    }))
    stat.mockResolvedValue({ mtime })
    const res = await GET()
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({
        backend: 'codex',
        plan_type: 'plus',
        limits: [{ key: 'primary', used_percent: 32, window_minutes: 10080, resets_at: 1784839672 }],
        as_of: mtime.toISOString(),
    })
})

test('passes the backend through so the bar can label whose quota this is', async () => {
    // Switching SCORE_BACKEND must relabel the bar, not silently show the other
    // provider's numbers under the old name.
    const mtime = new Date('2026-07-29T09:00:00.000Z')
    readFile.mockResolvedValue(JSON.stringify({
        backend: 'claude',
        plan_type: null,
        limits: [{ key: 'weekly_all', used_percent: 72, window_minutes: 10080, resets_at: 1785672000 }],
    }))
    stat.mockResolvedValue({ mtime })
    const res = await GET()
    expect((await res.json()).backend).toBe('claude')
})

test('returns an empty state (not an error) when the file is missing', async () => {
    readFile.mockRejectedValue(Object.assign(new Error('ENOENT'), { code: 'ENOENT' }))
    stat.mockRejectedValue(new Error('ENOENT'))
    const res = await GET()
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ backend: null, plan_type: null, limits: [], as_of: null })
})
