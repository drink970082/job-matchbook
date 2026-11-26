import { describePass, type PassRecord } from '@/lib/pass-record'

const HOUR = 3_600_000
const START = '2026-11-22T00:00:00.000Z'
const at = (hours: number) => Date.parse(START) + hours * HOUR

// The counts_json shape the worker writes (a real pass, trimmed).
const COUNTS = {
    fetch: { boards_attempted: 168, boards_failed: 31, inserted: 12 },
    feed: { simplify: { listings: 900, resolved: 40, inserted: 5 } },
    expire: { checked: 50, closed: 2, inconclusive: 47 },
    verdict: { aged_out: 3 },
    screen: { attempted: 69, errors: 2, uncalled: 4, errors_by_category: { provider_auth: 2 } },
    triage: { attempted: 262, keep: 100, skip: 160, deferred: 0, errors: 2, spent_usd: '0.067', stopped: null,
        errors_by_category: { provider_unreachable: 2 } },
}

const pass = (over: Partial<PassRecord> = {}): PassRecord => ({
    startedAt: START, finishedAt: '2026-11-22T00:04:12.000Z', status: 'ok', errorCategory: null,
    fetchOnly: false, jevEnabled: true, counts: COUNTS,
    config: { schedule_hours: 6, screen: { backend: 'codex', model: 'gpt-5.6-luna', effort: 'low' },
        triage: { backend: 'openrouter-native', limit: 300, max_usd: '0.25' } },
    ...over,
})

test('a finished pass: when, how long, what it ran with, one line per stage', () => {
    const d = describePass(pass(), at(1))
    expect(d.problem).toBeNull()
    expect(d.state).toBe('finished in 4m 12s')
    expect(d.ranWith).toBe('screen codex gpt-5.6-luna (low); triage openrouter-native, USD 0.25 cap; every 6h')
    expect(d.lines.map((l) => l.text)).toEqual([
        'Fetch: 168 boards, 31 failed; 12 new postings',
        'Feed simplify: 900 listings, 40 resolved; 5 new postings',
        'Closures: 2 closed of 50 re-checked, 47 inconclusive',
        'Aged out unevaluated: 3',
        'Screen: 69 screened, 2 errors (provider_auth 2), 4 deferred by the call cap',
        'Triage: 262 assessed (100 keep, 160 skip), 2 errors (provider_unreachable 2), 0 deferred, USD 0.067',
    ])
    expect(d.lines.filter((l) => l.warn).map((l) => l.stage)).toEqual(['fetch', 'screen', 'triage'])
})

test('a failed pass is a problem that names its error category', () => {
    const d = describePass(pass({ status: 'failed', errorCategory: 'abandoned', finishedAt: null,
        counts: { fetch: COUNTS.fetch } }), at(1))
    expect(d.problem).toMatch(/^Last pass failed: abandoned/)
    expect(d.state).toBe('failed: abandoned')
    expect(d.lines.map((l) => l.text)).toEqual(['Fetch: 168 boards, 31 failed; 12 new postings',
        'Screen: not reached', 'Triage: not reached'])
})

test('a pass that keeps dying shows as a problem even while the next one runs', () => {
    // Every slot: the dead pass is marked abandoned as the next one starts running.
    const running = pass({ status: 'running', finishedAt: null, counts: {} })
    const failure = { startedAt: '2026-11-21T18:00:00.000Z', errorCategory: 'abandoned', since: 3 }
    const d = describePass(running, at(0.5), failure)
    expect(d.state).toBe('running for 30m 0s')
    expect(d.problem).toBe('3 passes failed since the last finished one, the latest 6h 30m ago: abandoned '
        + '(it died before finishing and the next pass marked it).')
    expect(describePass(running, at(0.5), { ...failure, since: 1 }).problem).toMatch(/^A pass failed since the last finished one, 6h 30m ago: abandoned/)
    // A hung current pass is the more urgent notice.
    expect(describePass(running, at(7), failure).problem).toMatch(/running for 7h 0m/)
})

test('a running pass is fine within the pass interval and a problem past it', () => {
    const running = pass({ status: 'running', finishedAt: null, counts: {} })
    expect(describePass(running, at(1))).toMatchObject({ problem: null, state: 'running for 1h 0m' })
    expect(describePass(running, at(7)).problem).toMatch(/running for 7h 0m, longer than the 6h pass interval/)
})

test('no pass within the interval means the worker may be stopped; none at all says so', () => {
    expect(describePass(pass(), at(6.5)).problem).toBeNull()
    expect(describePass(pass(), at(8)).problem).toMatch(/No pass started in 8h 0m .*6h.*worker may be stopped/)
    // A record without schedule_hours falls back to the 24h default.
    expect(describePass(pass({ config: {} }), at(8)).problem).toBeNull()
    expect(describePass(null, at(0)).problem).toMatch(/No pass recorded yet/)
})

test('fetch-only and triage-off passes, a skipped triage, a triage stopped early', () => {
    const fetchOnly = describePass(pass({ fetchOnly: true, jevEnabled: false, config: {},
        counts: { fetch: COUNTS.fetch } }), at(1))
    expect(fetchOnly.ranWith).toBe('fetch only; every 24h')
    expect(fetchOnly.lines.slice(-2).map((l) => l.text)).toEqual(['Screen: not run (fetch only)', 'Triage: off'])
    const skipped = describePass(pass({ counts: { triage: { skipped: 'quota_exhausted' } } }), at(1))
    expect(skipped.lines.at(-1)).toEqual({ stage: 'triage', text: 'Triage: skipped (quota_exhausted)', warn: true })
    // The confirmation gate (#227) records the screen as skipped, not as zero screened.
    const gated = describePass(pass({ counts: { screen: { skipped: 'profile not confirmed' } } }), at(1))
    expect(gated.lines.find((l) => l.stage === 'screen')).toEqual(
        { stage: 'screen', text: 'Screen: skipped (profile not confirmed)', warn: true })
    const previewed = describePass(pass({ counts: { screen: { skipped: 'profile not confirmed', checked: 9, would_discard: 4 } } }), at(1))
    expect(previewed.lines.find((l) => l.stage === 'screen')?.text).toBe(
        'Screen: skipped (profile not confirmed); the current profile would discard 4 waiting posting(s)')
    const stopped = describePass(pass({ counts: { triage: { ...COUNTS.triage, errors: 0, errors_by_category: {}, deferred: 40, stopped: 'max_usd' } } }), at(1))
    expect(stopped.lines.at(-1)).toEqual({ stage: 'triage', warn: true,
        text: 'Triage: 262 assessed (100 keep, 160 skip), 0 errors, 40 deferred, USD 0.067, stopped: max_usd' })
})
