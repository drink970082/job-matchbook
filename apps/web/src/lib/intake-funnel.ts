// The intake funnel (#248): where every listing a pass saw went. The figures before a
// posting is stored come from the pass record (`worker_runs.counts_json`); the rest are
// the stored verdicts of the postings that pass inserted (`created_at` = the pass's
// `started_at`). The MCP's ats_worker/mcp/intake_funnel.py is the same rule, both pinned
// by worker/tests/fixtures/intake-funnel-cases.json. Pure: activity-actions reads the rows.

export const FUNNEL_WINDOW_MS = 7 * 86_400_000

export interface FunnelRun { started_at: string; status: string; counts: Record<string, any> }
export interface FunnelPosting { created_at: string; verdict: string; source_state: string | null; result_json: string | null }
export interface FunnelStage { stage: string; input: number; removed: number; reasons: Record<string, number>; output: number }
export interface FunnelWindow {
    passes: number
    passes_without_intake: number
    since: string | null
    stages: FunnelStage[]
    open: number
}
export interface IntakeFunnel { latest_pass: FunnelWindow | null; last_7_days: FunnelWindow }

const isObject = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v)

const n = (tally: unknown, ...keys: string[]) => isObject(tally)
    ? keys.reduce((sum, k) => sum + (Number.isInteger(tally[k]) ? tally[k] : 0), 0) : 0

// A pass counts once it recorded both fetch and feed: before that its postings have no
// complete listing figures to reconcile with.
const hasIntake = (c: Record<string, any>) => isObject(c.fetch) && isObject(c.feed)

// The latest pass with intake figures, and the ones inside the window. `runs` is in
// `started_at` order.
function windows(runs: FunnelRun[], since: string) {
    const done = runs.filter((r) => hasIntake(r.counts))
    return {
        latest: done.slice(-1),
        recent: done.filter((r) => r.started_at >= since),
        missed: runs.filter((r) => r.started_at >= since && r.status !== 'running' && !hasIntake(r.counts)).length,
    }
}

// The `started_at` values whose postings `intakeFunnel` needs.
export function funnelStarts(runs: FunnelRun[], now: number): string[] {
    const { latest, recent } = windows(runs, new Date(now - FUNNEL_WINDOW_MS).toISOString())
    return Array.from(new Set([...latest, ...recent].map((r) => r.started_at)))
}

export function intakeFunnel(runs: FunnelRun[], postings: FunnelPosting[], now: number): IntakeFunnel {
    const { latest, recent, missed } = windows(runs, new Date(now - FUNNEL_WINDOW_MS).toISOString())
    return {
        latest_pass: latest.length ? funnelWindow(latest, postings, 0) : null,
        last_7_days: funnelWindow(recent, postings, missed),
    }
}

function funnelWindow(passes: FunnelRun[], all: FunnelPosting[], missed: number): FunnelWindow {
    let listed = 0
    const filters = { title: 0, age: 0, feed_gate: 0 }
    const notNew = { already_stored: 0, duplicate: 0, unreadable: 0, closed: 0, unaccounted: 0 }
    for (const { counts: { fetch, feed: feeds } } of passes) {
        listed += n(fetch, 'listed')
        filters.title += n(fetch, 'dropped_title')
        filters.age += n(fetch, 'dropped_age')
        notNew.already_stored += n(fetch, 'already_stored')
        notNew.unreadable += n(fetch, 'bodyless', 'detail_failed')
        notNew.closed += n(fetch, 'inactive')
        for (const feed of Object.values<any>(feeds)) {
            listed += n(feed, 'listings')
            filters.title += n(feed, 'dropped_title')
            filters.age += n(feed, 'dropped_age', 'dropped_age_board')
            filters.feed_gate += n(feed, 'prefilter_dropped')
            // A resolved posting that was neither too old nor inserted was stored already.
            notNew.already_stored += n(feed, 'already_stored', 'resolved') - n(feed, 'dropped_age_board', 'inserted')
            notNew.duplicate += n(feed, 'duplicate')
            const unresolved = feed?.unresolved_by_reason
            notNew.unreadable += n(feed, 'no_url', 'not_on_board')
                + (isObject(unresolved) ? n(unresolved, ...Object.keys(unresolved)) : 0)
        }
    }

    const starts = passes.map((p) => p.started_at).sort()
    const postings = all.filter((p) => starts.includes(p.created_at))
    const verdict = (v: string) => postings.filter((p) => p.verdict === v)
    const requirements: Record<string, number> = {}
    for (const p of verdict('discarded')) {
        for (const check of failedChecks(p.result_json)) requirements[check] = (requirements[check] ?? 0) + 1
    }
    // `new` is the postings themselves, so a record that claims more or fewer inserts
    // than the store holds shows here too.
    notNew.unaccounted = listed - total(filters) - total(notNew) - postings.length

    const stages: FunnelStage[] = []
    let left = listed
    const stage = (name: string, reasons: Record<string, number>, removed = total(reasons)) => {
        stages.push({ stage: name, input: left, removed, reasons, output: left - removed })
        left -= removed
    }
    stage('filters', filters)
    stage('new', notNew)
    stage('evaluated', { pending: verdict('pending').length, not_evaluated: verdict('not_evaluated').length })
    stage('requirements', requirements, verdict('discarded').length)
    stage('triage', { skip: verdict('skip').length })
    stage('closed', { closed: verdict('keep').filter((p) => p.source_state === 'closed').length })
    return { passes: passes.length, passes_without_intake: missed, since: starts[0] ?? null, stages, open: left }
}

function total(reasons: Record<string, number>): number {
    return Object.values(reasons).reduce((a, b) => a + b, 0)
}

// The requirement checks a discard failed; one posting can fail several.
function failedChecks(raw: string | null): string[] {
    let screen: unknown
    try { screen = JSON.parse(raw ?? '')?.screen } catch { screen = null }
    const failed = isObject(screen) ? Object.keys(screen).filter((k) => (screen as any)[k]?.pass === false) : []
    return failed.length ? failed : ['unknown']
}

// How the Activity page names the stages and reasons; a reason not named here (a
// requirement check) is shown as recorded.
export const STAGE_LABEL: Record<string, string> = {
    filters: 'Dropped by title, age or the feed gate',
    new: 'Not a new posting',
    evaluated: 'Not evaluated',
    requirements: 'Removed by a requirement',
    triage: 'Removed by triage',
    closed: 'Closed since',
}
const REASON_LABEL: Record<string, string> = {
    feed_gate: 'feed gate (inactive, category, sponsorship)', already_stored: 'already stored', duplicate: 'listed twice in the feed', unreadable: 'could not be read',
    closed: 'closed', unaccounted: 'unaccounted', pending: 'waiting', not_evaluated: 'aged out',
}

export function reasonText(stage: FunnelStage): string {
    return Object.entries(stage.reasons).filter(([, count]) => count !== 0)
        .map(([reason, count]) => `${REASON_LABEL[reason] ?? reason} ${count.toLocaleString('en-US')}`).join(', ')
}
