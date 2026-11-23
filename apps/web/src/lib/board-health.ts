// A watchlist board's last-pass record (#231), written by the worker's run_fetch on
// watched_companies, read as one state. The rule is the worker's db.board_health (MCP
// list_sources returns the same state); both are pinned by
// apps/worker/tests/fixtures/board-health-cases.json.
//
// `kept` is postings stored with a description (gate discards and bodyless excluded);
// `detail_failed` is stubs that passed the gate and came back as nothing. First match:
// never_fetched; disabled (a browser row skipped while enable_browser_sources is off);
// fetch_failed; empty (listed 0); with nothing kept, details_failed / bodyless /
// kept_zero; details_failed or bodyless when that cause is over half of what reached
// hydration; teaser (a measured median under 1500 chars); ok.
export const BOARD_HEALTH = ['never_fetched', 'disabled', 'fetch_failed', 'empty', 'details_failed', 'bodyless',
    'kept_zero', 'teaser', 'ok'] as const
export type BoardHealth = (typeof BOARD_HEALTH)[number]

// worker db.TEASER_MEDIAN_CHARS
export const TEASER_MEDIAN_CHARS = 1500

export type BoardHealthRecord = {
    last_fetch_status: string | null
    last_fetched: number | null
    last_kept: number | null
    last_bodyless: number | null
    last_detail_failed: number | null
    last_desc_median: number | null
}

export function boardHealth(r: BoardHealthRecord): BoardHealth {
    if (!r.last_fetch_status) return 'never_fetched'
    if (r.last_fetch_status === 'disabled') return 'disabled'
    if (r.last_fetch_status !== 'ok') return 'fetch_failed'
    if (!r.last_fetched) return 'empty'
    const kept = r.last_kept ?? 0
    const bodyless = r.last_bodyless ?? 0
    const failed = r.last_detail_failed ?? 0
    if (!kept) return failed ? 'details_failed' : bodyless ? 'bodyless' : 'kept_zero'
    const reached = kept + bodyless + failed
    if (failed * 2 > reached) return 'details_failed'
    if (bodyless * 2 > reached) return 'bodyless'
    const median = r.last_desc_median
    if (median !== null && median !== undefined && median < TEASER_MEDIAN_CHARS) return 'teaser'
    return 'ok'
}

// Postings that reached hydration: the denominator the partial states are judged on.
export const reachedHydration = (r: BoardHealthRecord) =>
    (r.last_kept ?? 0) + (r.last_bodyless ?? 0) + (r.last_detail_failed ?? 0)
