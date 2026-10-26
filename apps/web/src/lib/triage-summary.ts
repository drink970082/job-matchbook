export const TRIAGE_STATUSES = [
    'rule_disqualified',
    'screen_disqualified',
    'candidate',
    'needs_review',
] as const

export type TriageStatus = (typeof TRIAGE_STATUSES)[number]

export const TRIAGE_STATUS_LABELS: Record<TriageStatus, string> = {
    rule_disqualified: 'Rule-based rejection',
    screen_disqualified: 'Standalone screening rejection',
    candidate: 'Candidate · retained for fit research',
    needs_review: 'Needs review',
}

export interface JobTriageSummary {
    status: TriageStatus
    reason: string
    provenance: 'job_screenings' | 'job_postings.score_detail' | 'pipeline_status' | 'none'
}

export interface TriageScreenRecord {
    state: string
    result_json: string | null
}

const KNOWN_PIPELINE_STATUSES = new Set([
    'new', 'scored', 'notified', 'applied', 'discarded', 'failed', 'removed', 'expired',
])
const ACTIVE_CANDIDATE_STATUSES = new Set(['new', 'scored', 'notified'])
const SUPPORTED_SCREEN_CHECKS = new Set([
    'location', 'internships', 'degree', 'authorization', 'clearance',
])
const DETERMINISTIC_SCREEN_CHECKS = new Set(['location', 'internships'])
const MAX_TRIAGE_REASON_CHARS = 300

function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value)
}

function parseObject(raw: unknown): Record<string, unknown> | null {
    if (typeof raw !== 'string') return null
    try {
        const parsed: unknown = JSON.parse(raw)
        return isRecord(parsed) ? parsed : null
    } catch {
        return null
    }
}

function hasOnlyKeys(value: Record<string, unknown>, keys: Set<string>): boolean {
    return Object.keys(value).every((key) => keys.has(key))
}

function checkShape(
    screen: unknown,
    supported: Set<string>,
): { valid: boolean; hasFailure: boolean; hasPass: boolean; failingKeys: string[] } {
    if (!isRecord(screen) || Object.keys(screen).length === 0) {
        return { valid: false, hasFailure: false, hasPass: false, failingKeys: [] }
    }
    let hasFailure = false
    let hasPass = false
    const failingKeys: string[] = []
    for (const [key, rawCheck] of Object.entries(screen)) {
        if (!supported.has(key) || !isRecord(rawCheck) || typeof rawCheck.pass !== 'boolean') {
            return { valid: false, hasFailure: false, hasPass: false, failingKeys: [] }
        }
        if (!hasOnlyKeys(rawCheck, new Set(['pass', 'note'])) ||
            ('note' in rawCheck && typeof rawCheck.note !== 'string')) {
            return { valid: false, hasFailure: false, hasPass: false, failingKeys: [] }
        }
        if (rawCheck.pass === false) {
            hasFailure = true
            failingKeys.push(key)
        } else {
            hasPass = true
        }
    }
    return { valid: true, hasFailure, hasPass, failingKeys }
}

function standaloneResult(raw: unknown): {
    status: 'rule_disqualified' | 'disqualified' | 'candidate' | 'unknown'
    failingKeys: string[]
} {
    const result = parseObject(raw)
    if (!result || !hasOnlyKeys(result, new Set(['screen', 'disqualified', 'disqualification_reason'])) ||
        typeof result.disqualified !== 'boolean' ||
        ('disqualification_reason' in result && typeof result.disqualification_reason !== 'string')) {
        return { status: 'unknown', failingKeys: [] }
    }
    const checks = checkShape(result.screen, SUPPORTED_SCREEN_CHECKS)
    if (!checks.valid) return { status: 'unknown', failingKeys: [] }
    if (result.disqualified === true && checks.hasFailure) {
        return {
            status: Object.keys(result.screen as Record<string, unknown>)
                .every((key) => DETERMINISTIC_SCREEN_CHECKS.has(key))
                ? 'rule_disqualified' : 'disqualified',
            failingKeys: checks.failingKeys,
        }
    }
    if (result.disqualified === false && checks.hasPass && !checks.hasFailure) {
        return { status: 'candidate', failingKeys: [] }
    }
    return { status: 'unknown', failingKeys: [] }
}

function legacyRuleDisqualification(pipelineStatus: string | null | undefined, scoreDetail: unknown): boolean {
    if (pipelineStatus !== 'discarded') return false
    const detail = parseObject(scoreDetail)
    if (!detail || !hasOnlyKeys(detail, new Set([
        'screen', 'disqualified', 'disqualification_reason', 'source_content_revision',
    ])) || detail.disqualified !== true ||
        ('disqualification_reason' in detail && typeof detail.disqualification_reason !== 'string')) {
        return false
    }
    if ('source_content_revision' in detail && detail.source_content_revision !== null &&
        (typeof detail.source_content_revision !== 'number' ||
            !Number.isSafeInteger(detail.source_content_revision) || detail.source_content_revision <= 0)) {
        return false
    }
    const checks = checkShape(detail.screen, DETERMINISTIC_SCREEN_CHECKS)
    return checks.valid && checks.hasFailure
}

export function jobTriageSummary(
    pipelineStatus: string | null | undefined,
    scoreDetail: string | null | undefined,
    screening: TriageScreenRecord | null | undefined,
): JobTriageSummary {
    const provenance: JobTriageSummary['provenance'] = screening
        ? 'job_screenings'
        : scoreDetail != null
            ? 'job_postings.score_detail'
            : pipelineStatus === 'discarded'
                ? 'pipeline_status'
                : 'none'

    const summary = (status: TriageStatus, reason: string): JobTriageSummary => ({
        status,
        reason: reason.slice(0, MAX_TRIAGE_REASON_CHARS),
        provenance,
    })

    if (!pipelineStatus || !KNOWN_PIPELINE_STATUSES.has(pipelineStatus)) {
        return summary('needs_review', 'Stored lifecycle state is unrecognized.')
    }

    if (screening) {
        if (screening.state !== 'complete') {
            return summary('needs_review', 'Standalone screening did not complete successfully.')
        }
        const result = standaloneResult(screening.result_json)
        if (result.status === 'rule_disqualified') {
            return summary(
                'rule_disqualified',
                `Deterministic ${[...new Set(result.failingKeys)].sort().join(' and ')} rule rejected this posting.`,
            )
        }
        if (result.status === 'disqualified') {
            return summary('screen_disqualified', 'Standalone screening recorded a supported failing requirement.')
        }
        if (result.status === 'candidate') {
            if (ACTIVE_CANDIDATE_STATUSES.has(pipelineStatus)) {
                return summary('candidate', 'Standalone screening found no disqualifier; retained for fit research, not qualified.')
            }
            return summary('needs_review', 'A standalone pass conflicts with the stored lifecycle state.')
        }
        return summary('needs_review', 'Stored standalone assessment is malformed, contradictory, or unsupported.')
    }

    if (legacyRuleDisqualification(pipelineStatus, scoreDetail)) {
        const detail = parseObject(scoreDetail)!
        const screen = detail.screen as Record<string, { pass: boolean }>
        const failed = Object.entries(screen).filter(([, check]) => check.pass === false)
            .map(([key]) => key).sort()
        return summary('rule_disqualified', `Legacy deterministic ${failed.join(' and ')} rule rejected this posting.`)
    }

    const detail = parseObject(scoreDetail)
    if (pipelineStatus === 'discarded') {
        return detail
            ? summary('needs_review', 'Legacy fit evidence does not meet the rule-rejection contract.')
            : summary('needs_review', 'Discarded lifecycle state alone does not establish a rule rejection.')
    }
    if (detail) return summary('needs_review', 'Legacy fit evidence does not establish current triage status.')
    if (scoreDetail != null) return summary('needs_review', 'Stored legacy evidence is malformed or unsupported.')
    return summary('needs_review', 'No standalone record or supported legacy rule rejection is stored.')
}
