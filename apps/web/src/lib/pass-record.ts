// The latest worker pass (`worker_runs`, #249) as the Activity strip shows it: when it
// ran, whether it finished, what it ran with, and one line per stage. Pure, so the
// strip can judge "running too long" against the browser's clock. The counts and
// config shapes are the worker's (docs/SPEC.md §7.1 run.py, "Pass record").

export interface PassRecord {
    startedAt: string
    finishedAt: string | null
    status: string // running | ok | failed
    errorCategory: string | null
    fetchOnly: boolean
    jevEnabled: boolean
    config: Record<string, any>
    counts: Record<string, any>
}

// The newest `failed` row newer than the newest `ok` row, and how many failed rows
// that run holds. The worker marks a dead pass `failed` only as the next one starts, so
// a failure is never the latest row while that next pass runs.
export interface PassFailure { startedAt: string; errorCategory: string | null; since: number }

export interface StageLine { stage: string; text: string; warn: boolean }

export interface PassView {
    problem: string | null
    state: string
    ranWith: string
    lines: StageLine[]
}

const HOUR = 3_600_000
// The worker's default `schedule_hours`, for a record that does not carry its own.
const DEFAULT_INTERVAL_HOURS = 24
// Passes start on the hour; this much slack past the interval before a missing one is a problem.
const SLACK_MS = HOUR

const FAILURE_HINT: Record<string, string> = {
    abandoned: 'it died before finishing and the next pass marked it',
}

// The worker writes both JSON columns (`config_json`, `counts_json`); a value it could not have written reads as empty.
export function parseObject(raw: string): Record<string, any> {
    try {
        const v = JSON.parse(raw)
        return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
    } catch {
        return {}
    }
}

export function duration(ms: number): string {
    const s = Math.max(0, Math.floor(ms / 1000))
    return s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
}

const n = (v: unknown) => (typeof v === 'number' ? v : 0)

function errors(t: Record<string, any>): string {
    const by = Object.entries(t.errors_by_category ?? {}).map(([k, v]) => `${k} ${v}`).join(', ')
    return `${n(t.errors)} errors${by ? ` (${by})` : ''}`
}

const failureText = (cat: string) => `${cat}${FAILURE_HINT[cat] ? ` (${FAILURE_HINT[cat]})` : ''}`

export function describePass(pass: PassRecord | null, now: number, failure: PassFailure | null = null): PassView {
    if (!pass) {
        return { problem: 'No pass recorded yet: the worker has not run against this database.', state: 'never',
            ranWith: '', lines: [] }
    }
    const { config: cfg, counts: c } = pass
    const hours = typeof cfg.schedule_hours === 'number' ? cfg.schedule_hours : DEFAULT_INTERVAL_HOURS
    const age = now - Date.parse(pass.startedAt)

    let state: string
    let problem: string | null = null
    if (pass.status === 'failed') {
        const cat = pass.errorCategory ?? 'unknown'
        state = `failed: ${cat}`
        problem = `Last pass failed: ${failureText(cat)}.`
    } else if (pass.status === 'running') {
        state = `running for ${duration(age)}`
        if (age > hours * HOUR) problem = `The last pass has been running for ${duration(age)}, longer than the ${hours}h pass interval: it may be hung.`
    } else {
        state = pass.finishedAt ? `finished in ${duration(Date.parse(pass.finishedAt) - Date.parse(pass.startedAt))}` : pass.status
    }
    if (!problem && pass.status !== 'running' && age > hours * HOUR + SLACK_MS) {
        problem = `No pass started in ${duration(age)} (the pass interval is ${hours}h): the worker may be stopped.`
    }
    if (!problem && failure && pass.status !== 'failed') {
        const when = `${duration(now - Date.parse(failure.startedAt))} ago`
        const lead = failure.since > 1
            ? `${failure.since} passes failed since the last finished one, the latest ${when}`
            : `A pass failed since the last finished one, ${when}`
        problem = `${lead}: ${failureText(failure.errorCategory ?? 'unknown')}.`
    }

    const ran: string[] = []
    if (pass.fetchOnly) ran.push('fetch only')
    if (cfg.screen) ran.push(`screen ${cfg.screen.backend} ${cfg.screen.model}${cfg.screen.effort ? ` (${cfg.screen.effort})` : ''}`)
    if (cfg.triage) ran.push(`triage ${cfg.triage.backend}${cfg.triage.max_usd ? `, USD ${cfg.triage.max_usd} cap` : ''}`)
    ran.push(`every ${hours}h`)

    // A stage with no tally: not configured, not run by mode, or the pass stopped first.
    const absent = pass.status === 'running' ? 'not yet' : 'not reached'
    const lines: StageLine[] = []
    if (c.fetch) {
        lines.push({ stage: 'fetch', warn: n(c.fetch.boards_failed) > 0,
            text: `Fetch: ${n(c.fetch.boards_attempted)} boards, ${n(c.fetch.boards_failed)} failed; ${n(c.fetch.inserted)} new postings` })
    }
    for (const [name, f] of Object.entries<Record<string, any>>(c.feed ?? {})) {
        lines.push({ stage: 'feed', warn: false,
            text: `Feed ${name}: ${n(f.listings)} listings, ${n(f.resolved)} resolved; ${n(f.inserted)} new postings` })
    }
    if (c.expire) {
        lines.push({ stage: 'expire', warn: false,
            text: `Closures: ${n(c.expire.closed)} closed of ${n(c.expire.checked)} re-checked, ${n(c.expire.inconclusive)} inconclusive` })
    }
    if (c.verdict) lines.push({ stage: 'verdict', warn: false, text: `Aged out unevaluated: ${n(c.verdict.aged_out)}` })

    const s = c.screen
    lines.push(s?.skipped
        // The confirmation gate (#227): nothing is spent until the profile is confirmed.
        ? { stage: 'screen', warn: true, text: `Screen: skipped (${s.skipped})`
            + (s.would_discard ? `; the current profile would discard ${n(s.would_discard)} waiting posting(s)` : '') }
        : s ? { stage: 'screen', warn: n(s.errors) > 0,
            text: `Screen: ${n(s.attempted)} screened, ${errors(s)}, ${n(s.uncalled)} deferred by the call cap` }
        : { stage: 'screen', warn: false, text: `Screen: ${pass.fetchOnly ? 'not run (fetch only)' : absent}` })

    const t = c.triage
    if (t?.skipped) {
        lines.push({ stage: 'triage', warn: true, text: `Triage: skipped (${t.skipped})` })
    } else if (t) {
        lines.push({ stage: 'triage', warn: n(t.errors) > 0 || !!t.stopped,
            text: `Triage: ${n(t.attempted)} assessed (${n(t.keep)} keep, ${n(t.skip)} skip), ${errors(t)}, `
                + `${n(t.deferred)} deferred, USD ${t.spent_usd ?? 0}${t.stopped ? `, stopped: ${t.stopped}` : ''}` })
    } else {
        lines.push({ stage: 'triage', warn: false,
            text: `Triage: ${!pass.jevEnabled ? 'off' : pass.fetchOnly ? 'not run (fetch only)' : absent}` })
    }
    return { problem, state, ranWith: ran.join('; '), lines }
}
