export const SCREEN_OUTCOMES = [
    'not_screened',
    'provider_error',
    'disqualified',
    'no_disqualifier_found',
    'unknown',
] as const

export type ScreenOutcome = (typeof SCREEN_OUTCOMES)[number]

export interface StandaloneScreenRecord {
    id: number
    state: string
    result_json: string | null
    error_message: string | null
    backend: string
    model: string | null
    effort: string | null
    evaluator_version: string
    updated_at: string | null
}

export interface ScreenSummary {
    outcome: ScreenOutcome
    is_advisory: true
    reason: string | null
    assessment_time: string | null
    backend: string | null
    model: string | null
    effort: string | null
    evaluator_version: string | null
    origin: 'job_screenings' | 'none'
}

export interface LegacyScreenEvidence {
    available: boolean
    origin: 'job_postings.score_detail.screen' | null
}

const MAX_REASON_CHARS = 300
const MAX_PROVENANCE_CHARS = 120
const MAX_TIMESTAMP_CHARS = 40
const DAYS_BEFORE_MONTH = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
const URL_IN_TEXT = /https?:\/\/[^\s<>"']+/gi
const SECRET_QUERY_KEYS = new Set([
    'token', 'accesstoken', 'authtoken', 'auth', 'authorization', 'apikey', 'key',
    'secret', 'clientsecret', 'signature', 'sig', 'password', 'passwd',
    'credential', 'credentials', 'accesskey', 'jwt',
])

function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value)
}

function sanitizeUrl(raw: string): string {
    try {
        const url = new URL(raw)
        const query = new URLSearchParams()
        for (const [key, value] of url.searchParams) {
            const normalized = key.replace(/[^a-z0-9]/gi, '').toLowerCase()
            const secret = SECRET_QUERY_KEYS.has(normalized) ||
                ['token', 'secret', 'apikey', 'signature', 'credential'].some((suffix) => normalized.endsWith(suffix))
            query.append(key, secret ? '[REDACTED]' : value)
        }
        url.search = query.toString()
        return url.toString()
    } catch {
        return raw.replace(/([?&])([^=&#]+)=([^&#]*)/g, (part, separator: string, key: string) => {
            const normalized = key.replace(/[^a-z0-9]/gi, '').toLowerCase()
            const secret = SECRET_QUERY_KEYS.has(normalized) ||
                ['token', 'secret', 'apikey', 'signature', 'credential'].some((suffix) => normalized.endsWith(suffix))
            return secret ? `${separator}${key}=[REDACTED]` : part
        })
    }
}

function sanitizeReason(value: unknown): string | null {
    if (typeof value !== 'string') return null
    return value.replace(URL_IN_TEXT, sanitizeUrl).split(/\s+/).filter(Boolean).join(' ').slice(0, MAX_REASON_CHARS)
}

function bounded(value: string | null | undefined): string | null {
    return typeof value === 'string' ? value.slice(0, MAX_PROVENANCE_CHARS) : null
}

function assessmentTime(value: string | null | undefined): string | null {
    if (!value || value.length > MAX_TIMESTAMP_CHARS) return null
    const match = /^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?([Zz]|([+-])(\d{2}):(\d{2}))$/.exec(value)
    if (!match || match[0] !== value) return null

    const year = Number(match[1])
    const month = Number(match[2])
    const day = Number(match[3])
    const hour = Number(match[4])
    const minute = Number(match[5])
    const second = Number(match[6])
    if (year === 0 || month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59) return null

    const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
    const daysInMonth = month === 2 ? (leapYear ? 29 : 28) :
        [4, 6, 9, 11].includes(month) ? 30 : 31
    if (day < 1 || day > daysInMonth) return null

    const offsetHours = Number(match[9] ?? 0)
    const offsetMinutes = Number(match[10] ?? 0)
    let offsetTotalMinutes = offsetHours * 60 + offsetMinutes
    // datetime.fromisoformat accepts minute fields above 59 and normalizes them, as
    // long as the resulting UTC offset is still strictly less than 24 hours.
    if (offsetTotalMinutes >= 24 * 60) return null
    if (match[8] === '-') offsetTotalMinutes *= -1

    // Python's UTC conversion rejects a timestamp whose offset would cross its
    // supported year range (0001 through 9999), even when its local fields are valid.
    const daysBeforeYear = (value: number) => {
        const prior = value - 1
        return prior * 365 + Math.floor(prior / 4) - Math.floor(prior / 100) + Math.floor(prior / 400)
    }
    const dayOfYear = DAYS_BEFORE_MONTH[month - 1] + day - 1 + (month > 2 && leapYear ? 1 : 0)
    const localDay = daysBeforeYear(year) + dayOfYear
    const utcDay = Math.floor((localDay * 24 * 60 + hour * 60 + minute - offsetTotalMinutes) / (24 * 60))
    const lastSupportedUtcDay = daysBeforeYear(10_000) - 1
    if (utcDay < 0 || utcDay > lastSupportedUtcDay) return null

    return value
}

export function standaloneScreenOutcome(record: Pick<StandaloneScreenRecord, 'state' | 'result_json'> | null | undefined): ScreenOutcome {
    if (!record) return 'not_screened'
    if (record.state === 'provider_error') return 'provider_error'
    if (record.state !== 'complete' || typeof record.result_json !== 'string') return 'unknown'

    let parsed: unknown
    try {
        parsed = JSON.parse(record.result_json)
    } catch {
        return 'unknown'
    }
    if (!isRecord(parsed) || !isRecord(parsed.screen)) return 'unknown'

    const hasFailingCheck = Object.values(parsed.screen).some(
        (check) => isRecord(check) && check.pass === false,
    )
    const hasPassingCheck = Object.values(parsed.screen).some(
        (check) => isRecord(check) && check.pass === true,
    )
    if (parsed.disqualified === true && hasFailingCheck) return 'disqualified'
    if (parsed.disqualified === false && hasPassingCheck && !hasFailingCheck) return 'no_disqualifier_found'
    return 'unknown'
}

export function standaloneScreenSummary(record: StandaloneScreenRecord | null | undefined): ScreenSummary {
    const outcome = standaloneScreenOutcome(record)
    const parsed = (() => {
        if (!record?.result_json) return null
        try {
            return JSON.parse(record.result_json) as unknown
        } catch {
            return null
        }
    })()
    let reason: string | null
    switch (outcome) {
        case 'not_screened':
            reason = null
            break
        case 'provider_error':
            reason = sanitizeReason(record?.error_message) || 'Screening provider failed.'
            break
        case 'disqualified':
            reason = sanitizeReason(isRecord(parsed) ? parsed.disqualification_reason : null) ||
                'The stored checked result marks a disqualifier.'
            break
        case 'no_disqualifier_found':
            reason = 'No failing typed check was stored; unchecked requirements remain unknown.'
            break
        default:
            reason = 'The stored assessment is incomplete, contradictory, or not classifiable.'
    }

    return {
        outcome,
        is_advisory: true,
        reason,
        assessment_time: assessmentTime(record?.updated_at),
        backend: bounded(record?.backend),
        model: bounded(record?.model),
        effort: bounded(record?.effort),
        evaluator_version: bounded(record?.evaluator_version),
        origin: record ? 'job_screenings' : 'none',
    }
}

export function legacyScreenEvidence(scoreDetail: string | null | undefined): LegacyScreenEvidence {
    if (!scoreDetail) return { available: false, origin: null }
    try {
        const parsed: unknown = JSON.parse(scoreDetail)
        const available = isRecord(parsed) && isRecord(parsed.screen)
        return {
            available,
            origin: available ? 'job_postings.score_detail.screen' : null,
        }
    } catch {
        return { available: false, origin: null }
    }
}
