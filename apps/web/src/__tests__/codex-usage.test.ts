/**
 * @jest-environment node
 */
// node env so the Web Request/Response globals next/server needs are present.
// Unit test for /api/codex-usage: it serves the worker's quota snapshot, adds the
// file mtime as `as_of`, and degrades to an empty state (not a 500) when the file
// is absent — the worker may not have scored yet. See docs/SPEC.md §13.
jest.mock('node:fs', () => ({
    promises: { readFile: jest.fn(), stat: jest.fn() },
}))

import { promises as fs } from 'node:fs'
import { GET } from '@/app/api/codex-usage/route'

const readFile = fs.readFile as unknown as jest.Mock
const stat = fs.stat as unknown as jest.Mock

beforeEach(() => {
    readFile.mockReset()
    stat.mockReset()
    process.env.CODEX_USAGE_FILE = '/data/codex_usage.json'
})

test('serves the snapshot with as_of from the file mtime', async () => {
    const mtime = new Date('2026-07-17T11:27:00.000Z')
    readFile.mockResolvedValue(JSON.stringify({
        plan_type: 'plus',
        limits: [{ key: 'primary', used_percent: 32, window_minutes: 10080, resets_at: 1784839672 }],
    }))
    stat.mockResolvedValue({ mtime })
    const res = await GET()
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({
        plan_type: 'plus',
        limits: [{ key: 'primary', used_percent: 32, window_minutes: 10080, resets_at: 1784839672 }],
        as_of: mtime.toISOString(),
    })
})

test('returns an empty state (not an error) when the file is missing', async () => {
    readFile.mockRejectedValue(Object.assign(new Error('ENOENT'), { code: 'ENOENT' }))
    stat.mockRejectedValue(new Error('ENOENT'))
    const res = await GET()
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ plan_type: null, limits: [], as_of: null })
})
