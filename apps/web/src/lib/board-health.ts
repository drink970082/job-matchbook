// A watchlist board's last-pass record (#231), written by the worker's run_fetch on
// watched_companies, read as one state. The rule is the worker's db.board_health (MCP
// list_sources returns the same state); both are pinned by
// apps/worker/tests/fixtures/board-health-cases.json.
// `disabled`: a browser row the worker skips while enable_browser_sources is off.
// `bodyless`: nothing kept because the postings came back with no description (a broken
// selector), not because the filters matched none.
export const BOARD_HEALTH = ['never_fetched', 'disabled', 'fetch_failed', 'empty', 'bodyless', 'kept_zero', 'teaser', 'ok'] as const
export type BoardHealth = (typeof BOARD_HEALTH)[number]

// A measured median description shorter than this is a teaser, not a job description
// (worker db.TEASER_MEDIAN_CHARS). The median covers hydrated postings only and is NULL
// when none was hydrated: nothing measured, not a teaser.
export const TEASER_MEDIAN_CHARS = 1500

export type BoardHealthRecord = {
    last_fetch_status: string | null
    last_fetched: number | null
    last_kept: number | null
    last_bodyless: number | null
    last_desc_median: number | null
}

export function boardHealth(r: BoardHealthRecord): BoardHealth {
    if (!r.last_fetch_status) return 'never_fetched'
    if (r.last_fetch_status === 'disabled') return 'disabled'
    if (r.last_fetch_status !== 'ok') return 'fetch_failed'
    if (!r.last_fetched) return 'empty'
    if (!r.last_kept) return r.last_bodyless ? 'bodyless' : 'kept_zero'
    if (r.last_desc_median !== null && r.last_desc_median !== undefined && r.last_desc_median < TEASER_MEDIAN_CHARS) return 'teaser'
    return 'ok'
}
