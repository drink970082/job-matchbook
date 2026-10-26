export type SourceFreshness = 'not_assessed' | 'current' | 'stale' | 'unknown' | 'provider_error'

export interface SourceLifecycleSummary {
    state: 'unknown' | 'available' | 'closed'
    last_seen_at: string | null
    last_check_attempted_at: string | null
    last_checked_at: string | null
    last_check_outcome: 'not_checked' | 'found' | 'confirmed_closed' | 'inconclusive'
    last_check_error_category: string | null
    content_revision: number | null
    fit_freshness: SourceFreshness
    screen_freshness: SourceFreshness
    combined_screen_freshness: SourceFreshness
}

type PostingEvidence = {
    source_state?: unknown
    source_last_seen_at?: unknown
    source_last_check_attempted_at?: unknown
    source_last_checked_at?: unknown
    source_last_check_outcome?: unknown
    source_last_check_error_category?: unknown
    source_content_revision?: unknown
    score_detail?: unknown
}

type ScreenEvidence = {
    state?: unknown
    source_content_revision?: unknown
} | null | undefined

function revision(value: unknown): number | null {
    return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : null
}

function assessFreshness(assessed: boolean, captured: unknown, current: number | null): SourceFreshness {
    if (!assessed) return 'not_assessed'
    const sourceRevision = revision(captured)
    if (sourceRevision == null || current == null) return 'unknown'
    return sourceRevision === current ? 'current' : 'stale'
}

function parseScoreEvidence(raw: unknown): {
    assessed: boolean
    screened: boolean
    revision: unknown
} {
    if (typeof raw !== 'string') return { assessed: false, screened: false, revision: null }
    try {
        const parsed: unknown = JSON.parse(raw)
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
            return { assessed: false, screened: false, revision: null }
        }
        const detail = parsed as Record<string, unknown>
        const assessment = detail.assessment
        const assessed = !!assessment && typeof assessment === 'object' &&
            !Array.isArray(assessment) && Object.keys(assessment).length > 0
        return {
            assessed,
            screened: !!detail.screen && typeof detail.screen === 'object' &&
                !Array.isArray(detail.screen),
            revision: detail.source_content_revision,
        }
    } catch {
        return { assessed: false, screened: false, revision: null }
    }
}

function timestamp(value: unknown): string | null {
    return typeof value === 'string' && value.length <= 40 ? value : null
}

const ERROR_CATEGORIES = new Set([
    'invalid_request', 'malformed_response', 'identity_mismatch', 'company_mismatch',
    'invalid_active', 'incomplete_content', 'timeout', 'connection_error', 'http_403',
    'http_404', 'http_410', 'http_429', 'http_5xx', 'http_error', 'refresh_error',
])

export function sourceLifecycleSummary(
    posting: PostingEvidence,
    screen?: ScreenEvidence,
): SourceLifecycleSummary {
    const state = posting.source_state
    const outcome = posting.source_last_check_outcome
    const current = revision(posting.source_content_revision)
    const fit = parseScoreEvidence(posting.score_detail)
    const screenState = screen?.state
    const screenFreshness: SourceFreshness = screenState === 'provider_error'
        ? 'provider_error'
        : screenState === 'complete'
            ? assessFreshness(true, screen?.source_content_revision, current)
            : screen == null ? 'not_assessed' : 'unknown'
    const errorCategory = posting.source_last_check_error_category

    return {
        state: state === 'available' || state === 'closed' ? state : 'unknown',
        last_seen_at: timestamp(posting.source_last_seen_at),
        last_check_attempted_at: timestamp(posting.source_last_check_attempted_at),
        last_checked_at: timestamp(posting.source_last_checked_at),
        last_check_outcome: outcome === 'found' || outcome === 'confirmed_closed' || outcome === 'inconclusive'
            ? outcome : 'not_checked',
        last_check_error_category: typeof errorCategory === 'string' && ERROR_CATEGORIES.has(errorCategory)
            ? errorCategory : null,
        content_revision: current,
        fit_freshness: assessFreshness(fit.assessed, fit.revision, current),
        screen_freshness: screenFreshness,
        combined_screen_freshness: assessFreshness(fit.screened, fit.revision, current),
    }
}
