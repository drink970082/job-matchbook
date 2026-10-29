import { validOffsetTimestamp } from '@/lib/screen-summary'

export type AssessmentState = 'not_assessed' | 'current' | 'stale' | 'unknown'
export type LatestAttemptState = 'not_attempted' | 'succeeded' | 'provider_error' | 'unknown'

export interface AssessmentEvidence {
    id: string
    label: string
    label_truncated: boolean
    excerpt: string
    excerpt_truncated: boolean
}

export interface AssessmentComponent {
    id: string
    label: string
    label_truncated: boolean
    score: number
    jd_evidence: AssessmentEvidence[]
}

export interface AssessmentView {
    schema_version: 1
    scope: 'synthetic_assessment_view'
    synthetic: true
    assessment_state: AssessmentState
    assessment_reason: string | null
    latest_attempt: {
        state: LatestAttemptState
        attempted_at: string | null
        provider: string | null
        provider_truncated: boolean
        requested_model: string | null
        requested_model_truncated: boolean
        resolved_model: string | null
        resolved_model_truncated: boolean
        error_category: string | null
    }
    assessment_time: string | null
    metadata: Record<string, string | number | boolean> | null
    components: AssessmentComponent[]
}

const MAX_COMPONENTS = 32
const MAX_JD_EVIDENCE = 32
const MAX_DISPLAY_LABEL_CHARS = 120
const MAX_JD_EXCERPT_CHARS = 300
const COMPONENT_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/
const DISPLAY_IDENTITY_KEYS = [
    'question_version',
    'rubric_version',
    'policy_version',
    'prompt_version',
    'result_schema_version',
    'input_variant',
    'provider',
    'requested_model',
    'resolved_model',
] as const
const ASSESSMENT_REASONS = new Set([
    'unsupported_schema',
    'malformed_snapshot',
    'non_synthetic_input',
    'invalid_expected_identity',
    'malformed_success',
    'invalid_captured_identity',
    'invalid_assessment_time',
    'invalid_assessment_payload',
    'too_many_components',
    'too_many_jd_evidence',
    'identity_mismatch',
    'malformed_view',
])
const ATTEMPT_STATES = new Set<LatestAttemptState>([
    'not_attempted', 'succeeded', 'provider_error', 'unknown',
])
const ERROR_CATEGORIES = new Set([
    'timeout', 'connection_error', 'rate_limited', 'provider_unavailable',
    'invalid_response', 'unknown_error',
])

function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value)
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: Set<string>): boolean {
    return Object.keys(value).every((key) => allowed.has(key))
}

function safeDisplayText(value: unknown, limit: number): value is string {
    return typeof value === 'string' && value.length > 0 && Array.from(value).length <= limit &&
        value.trim() === value && !/[\u0000-\u001f\u007f]/.test(value)
}

function emptyAttempt(state: LatestAttemptState = 'unknown'): AssessmentView['latest_attempt'] {
    return {
        state,
        attempted_at: null,
        provider: null,
        provider_truncated: false,
        requested_model: null,
        requested_model_truncated: false,
        resolved_model: null,
        resolved_model_truncated: false,
        error_category: null,
    }
}

function normalizeAttempt(value: unknown): AssessmentView['latest_attempt'] {
    if (!isRecord(value) || !ATTEMPT_STATES.has(value.state as LatestAttemptState)) return emptyAttempt()
    const state = value.state as LatestAttemptState
    if (state === 'unknown') return emptyAttempt()
    if (state === 'not_attempted') {
        if (value.attempted_at !== null || value.provider !== null || value.requested_model !== null ||
            value.resolved_model !== null || value.error_category !== null) return emptyAttempt()
        return emptyAttempt('not_attempted')
    }

    const labels = ['provider', 'requested_model', 'resolved_model'] as const
    const flags = ['provider_truncated', 'requested_model_truncated', 'resolved_model_truncated'] as const
    for (const key of labels) {
        if (!safeDisplayText(value[key], MAX_DISPLAY_LABEL_CHARS)) return emptyAttempt()
    }
    for (const key of flags) {
        if (typeof value[key] !== 'boolean') return emptyAttempt()
        const label = value[key.replace('_truncated', '')]
        if (value[key] === true && (typeof label !== 'string' || Array.from(label).length !== MAX_DISPLAY_LABEL_CHARS)) {
            return emptyAttempt()
        }
    }
    if (typeof value.attempted_at !== 'string' || !validOffsetTimestamp(value.attempted_at)) return emptyAttempt()
    if (state === 'provider_error') {
        if (typeof value.error_category !== 'string' || !ERROR_CATEGORIES.has(value.error_category)) {
            return emptyAttempt()
        }
    } else if (value.error_category !== null) {
        return emptyAttempt()
    }
    return {
        state,
        attempted_at: value.attempted_at,
        provider: value.provider as string,
        provider_truncated: value.provider_truncated as boolean,
        requested_model: value.requested_model as string,
        requested_model_truncated: value.requested_model_truncated as boolean,
        resolved_model: value.resolved_model as string,
        resolved_model_truncated: value.resolved_model_truncated as boolean,
        error_category: state === 'provider_error' ? value.error_category as string : null,
    }
}

function normalizeMetadata(value: unknown): AssessmentView['metadata'] {
    if (!isRecord(value)) return null
    const variant = value.input_variant
    if (!safeDisplayText(variant, MAX_DISPLAY_LABEL_CHARS)) return null
    const required = new Set<string>(['source_revision', ...DISPLAY_IDENTITY_KEYS])
    const truncatedKeys = DISPLAY_IDENTITY_KEYS.map((key) => `${key}_truncated`)
    if (variant === 'extracted') {
        required.add('extractor_version')
        truncatedKeys.push('extractor_version_truncated')
    }
    const allowed = new Set([...required, ...truncatedKeys])
    if (!hasOnlyKeys(value, allowed) || !Number.isSafeInteger(value.source_revision) ||
        (value.source_revision as number) <= 0) return null
    for (const key of required) {
        if (key === 'source_revision') continue
        if (!safeDisplayText(value[key], MAX_DISPLAY_LABEL_CHARS)) return null
    }
    for (const key of truncatedKeys) {
        if (key in value) {
            const labelKey = key.replace('_truncated', '')
            if (typeof value[key] !== 'boolean' ||
                (value[key] === true && (typeof value[labelKey] !== 'string' ||
                Array.from(value[labelKey] as string).length !== MAX_DISPLAY_LABEL_CHARS))) return null
        }
    }
    return value as AssessmentView['metadata']
}

function normalizeEvidence(value: unknown): AssessmentEvidence | null {
    if (!isRecord(value) || !hasOnlyKeys(value, new Set([
        'id', 'label', 'label_truncated', 'excerpt', 'excerpt_truncated',
    ]))) return null
    if (typeof value.id !== 'string' || !COMPONENT_ID.test(value.id) ||
        !safeDisplayText(value.label, MAX_DISPLAY_LABEL_CHARS) ||
        typeof value.label_truncated !== 'boolean' ||
        (value.label_truncated && Array.from(value.label).length !== MAX_DISPLAY_LABEL_CHARS) ||
        !safeDisplayText(value.excerpt, MAX_JD_EXCERPT_CHARS) ||
        typeof value.excerpt_truncated !== 'boolean' ||
        (value.excerpt_truncated && Array.from(value.excerpt).length !== MAX_JD_EXCERPT_CHARS)) return null
    return {
        id: value.id,
        label: value.label,
        label_truncated: value.label_truncated,
        excerpt: value.excerpt,
        excerpt_truncated: value.excerpt_truncated,
    }
}

function normalizeComponents(value: unknown): AssessmentComponent[] | null {
    if (!Array.isArray(value) || value.length === 0 || value.length > MAX_COMPONENTS) return null
    const ids = new Set<string>()
    const evidenceIds = new Set<string>()
    const components: AssessmentComponent[] = []
    let evidenceReferenceCount = 0
    for (const raw of value) {
        if (!isRecord(raw) || !hasOnlyKeys(raw, new Set([
            'id', 'label', 'label_truncated', 'score', 'jd_evidence',
        ]))) return null
        if (typeof raw.id !== 'string' || !COMPONENT_ID.test(raw.id) || ids.has(raw.id) ||
            !safeDisplayText(raw.label, MAX_DISPLAY_LABEL_CHARS) ||
            typeof raw.label_truncated !== 'boolean' ||
            (raw.label_truncated && Array.from(raw.label).length !== MAX_DISPLAY_LABEL_CHARS) ||
            typeof raw.score !== 'number' || !Number.isFinite(raw.score) ||
            raw.score < 0 || raw.score > 100 || !Array.isArray(raw.jd_evidence) ||
            raw.jd_evidence.length > MAX_JD_EVIDENCE) return null
        const evidence = raw.jd_evidence.map(normalizeEvidence)
        if (evidence.some((item) => item === null)) return null
        evidenceReferenceCount += evidence.length
        if (evidenceReferenceCount > MAX_JD_EVIDENCE) return null
        for (const item of evidence as AssessmentEvidence[]) evidenceIds.add(item.id)
        if (evidenceIds.size > MAX_JD_EVIDENCE) return null
        ids.add(raw.id)
        components.push({
            id: raw.id,
            label: raw.label,
            label_truncated: raw.label_truncated,
            score: raw.score,
            jd_evidence: evidence as AssessmentEvidence[],
        })
    }
    return components
}

function unknownView(reason: string, latestAttempt = emptyAttempt()): AssessmentView {
    return {
        schema_version: 1,
        scope: 'synthetic_assessment_view',
        synthetic: true,
        assessment_state: 'unknown',
        assessment_reason: reason,
        latest_attempt: latestAttempt,
        assessment_time: null,
        metadata: null,
        components: [],
    }
}

/** Validate and copy a Python-projected view, dropping all unrecognized data. */
export function normalizeAssessmentView(value: unknown): AssessmentView {
    if (!isRecord(value)) return unknownView('malformed_view')
    if (value.schema_version !== 1) return unknownView('unsupported_schema')
    if (value.scope !== 'synthetic_assessment_view' || value.synthetic !== true) {
        return unknownView('malformed_view')
    }
    const latestAttempt = normalizeAttempt(value.latest_attempt)
    if (!['not_assessed', 'current', 'stale', 'unknown'].includes(value.assessment_state as string) ||
        !hasOnlyKeys(value, new Set([
            'schema_version', 'scope', 'synthetic', 'assessment_state', 'assessment_reason',
            'latest_attempt', 'assessment_time', 'metadata', 'components',
        ]))) return unknownView('malformed_view', latestAttempt)

    const state = value.assessment_state as AssessmentState
    if (state === 'unknown') {
        if (typeof value.assessment_reason !== 'string' || !ASSESSMENT_REASONS.has(value.assessment_reason) ||
            value.assessment_time !== null || value.metadata !== null ||
            !Array.isArray(value.components) || value.components.length !== 0) {
            return unknownView('malformed_view', latestAttempt)
        }
        return unknownView(value.assessment_reason, latestAttempt)
    }
    if (state === 'not_assessed') {
        if (value.assessment_reason !== null || value.assessment_time !== null || value.metadata !== null ||
            !Array.isArray(value.components) || value.components.length !== 0) {
            return unknownView('malformed_view', latestAttempt)
        }
        return {
            ...unknownView('malformed_view', latestAttempt),
            assessment_state: 'not_assessed',
            assessment_reason: null,
        }
    }

    if (typeof value.assessment_time !== 'string' || !validOffsetTimestamp(value.assessment_time)) {
        return unknownView('malformed_view', latestAttempt)
    }
    if (state === 'current' && value.assessment_reason !== null) return unknownView('malformed_view', latestAttempt)
    if (state === 'stale' && value.assessment_reason !== 'identity_mismatch') {
        return unknownView('malformed_view', latestAttempt)
    }
    const metadata = normalizeMetadata(value.metadata)
    const components = normalizeComponents(value.components)
    if (metadata === null || components === null) return unknownView('malformed_view', latestAttempt)
    return {
        schema_version: 1,
        scope: 'synthetic_assessment_view',
        synthetic: true,
        assessment_state: state,
        assessment_reason: value.assessment_reason as string | null,
        latest_attempt: latestAttempt,
        assessment_time: value.assessment_time,
        metadata,
        components,
    }
}
