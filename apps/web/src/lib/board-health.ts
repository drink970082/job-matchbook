// A watchlist board's last-pass record (#231), written by the worker's run_fetch on
// watched_companies, read as one state. The rule is the worker's db.board_health (MCP
// list_sources returns the same state); both are pinned by
// apps/worker/tests/fixtures/board-health-cases.json.
export const BOARD_HEALTH = ['never_fetched', 'fetch_failed', 'empty', 'kept_zero', 'teaser', 'ok'] as const
export type BoardHealth = (typeof BOARD_HEALTH)[number]

// A kept median description shorter than this is a teaser, not a job description
// (worker db.TEASER_MEDIAN_CHARS).
export const TEASER_MEDIAN_CHARS = 1500

export type BoardHealthRecord = {
    last_fetch_status: string | null
    last_fetched: number | null
    last_kept: number | null
    last_desc_median: number | null
}

export function boardHealth(r: BoardHealthRecord): BoardHealth {
    if (!r.last_fetch_status) return 'never_fetched'
    if (r.last_fetch_status !== 'ok') return 'fetch_failed'
    if (!r.last_fetched) return 'empty'
    if (!r.last_kept) return 'kept_zero'
    if ((r.last_desc_median ?? 0) < TEASER_MEDIAN_CHARS) return 'teaser'
    return 'ok'
}
