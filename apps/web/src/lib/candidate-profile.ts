// The candidate profile (#224): one row (candidate_profile, id=1) every worker stage
// reads. This module is the web side's one validation and derivation, shared by the
// Settings form (client) and setCandidateProfile (server, behind /api/v1 and MCP).
// The worker's counterpart is apps/worker/ats_worker/profile.py; both run
// worker/tests/fixtures/candidate-profile-cases.json.

import { DEGREES, WORK_AUTHORIZATIONS } from '@/lib/constants'

export type Degree = (typeof DEGREES)[number]
export interface Education { degree: Degree; field: string }
export interface Experience { title: string; company: string; years: number }
export interface TriageContext { profile_text: string; yoe_context: string }

// The editable fields, as the API takes them and getCandidateProfile returns them.
export interface ProfileFields {
    title_include: string[]
    title_exclude: string[]
    max_age_days: number
    locations: string[]
    work_authorization: string
    security_clearance: string
    exclude_internships: boolean
    exclude_contract: boolean
    education: Education[]
    experience: Experience[]
    target_roles: string[]
    open_to: string[]
    not_interested: string[]
    custom_triage_context: TriageContext | null
    custom_packs: null // settable only to null (back to the committed defaults)
}
export type ProfileField = keyof ProfileFields

const LISTS = { title_include: [100, 100], title_exclude: [100, 100], locations: [50, 100],
    target_roles: [30, 200], open_to: [30, 200], not_interested: [30, 200] } as const
const MAX_ROWS = 30
const MAX_TEXT = 200
const MAX_CLEARANCE = 100
const MAX_AGE_DAYS = 3650
const MAX_PROFILE_TEXT = 16000
const MAX_YOE_CONTEXT = 2000
// What triage reads (background, preferences, custom context and packs).
export const TRIAGE_FIELDS: readonly ProfileField[] = ['education', 'experience', 'target_roles', 'open_to',
    'not_interested', 'custom_triage_context', 'custom_packs']
export const PROFILE_FIELDS: readonly ProfileField[] = ['title_include', 'title_exclude', 'max_age_days', 'locations',
    'work_authorization', 'security_clearance', 'exclude_internships', 'exclude_contract', ...TRIAGE_FIELDS]

const text = (v: unknown, what: string, max: number) => {
    if (typeof v !== 'string') throw new Error(`${what} must be a string`)
    const t = v.trim()
    if (t.length > max) throw new Error(`${what} is over ${max} characters`)
    return t
}
const list = (v: unknown, what: string, maxItems: number) => {
    if (!Array.isArray(v)) throw new Error(`${what} must be a list`)
    if (v.length > maxItems) throw new Error(`${what} has over ${maxItems} entries`)
    return v
}
const obj = (v: unknown, what: string) => {
    if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error(`${what} must be an object`)
    return v as Record<string, unknown>
}

const onlyKeys = (e: Record<string, unknown>, what: string, keys: readonly string[]) => {
    const extra = Object.keys(e).filter((k) => !keys.includes(k))
    if (extra.length) throw new Error(`${what} takes only ${keys.join(', ')} (got ${extra.join(', ')})`)
    return e
}

function education(v: unknown): Education[] {
    return list(v, 'education', MAX_ROWS).map((r) => {
        const e = onlyKeys(obj(r, 'education entry'), 'an education entry', ['degree', 'field'])
        const degree = text(e.degree ?? '', 'degree', MAX_TEXT).toLowerCase()
        const field = text(e.field ?? '', 'field', MAX_TEXT)
        return { degree, field }
    }).filter((e) => e.degree || e.field).map((e) => {
        if (!(DEGREES as readonly string[]).includes(e.degree)) throw new Error(`degree must be one of: ${DEGREES.join(', ')}`)
        return e as Education
    })
}

function experience(v: unknown): Experience[] {
    return list(v, 'experience', MAX_ROWS).map((r) => {
        const e = onlyKeys(obj(r, 'experience entry'), 'an experience entry', ['title', 'company', 'years'])
        const years = e.years ?? 0
        if (typeof years !== 'number' || !Number.isFinite(years) || years < 0 || years > 60) {
            throw new Error('years must be a number from 0 to 60')
        }
        return { title: text(e.title ?? '', 'title', MAX_TEXT), company: text(e.company ?? '', 'company', MAX_TEXT), years }
    }).filter((e) => e.title || e.company || e.years)
}

// `storedProfileText`: the stored context's profile text. Restating it unchanged is
// allowed even when it is not a JSON object (a legacy free-text profile), so a
// yoe_context-only edit can be saved.
function triageContext(v: unknown, storedProfileText?: string): TriageContext | null {
    if (v === null) return null
    const c = obj(v, 'custom_triage_context')
    const extra = Object.keys(c).filter((k) => k !== 'profile_text' && k !== 'yoe_context')
    if (extra.length) throw new Error(`custom_triage_context takes only profile_text and yoe_context (got ${extra.join(', ')})`)
    if (typeof c.profile_text !== 'string') throw new Error('profile_text must be a string')
    if (c.profile_text.length > MAX_PROFILE_TEXT) throw new Error(`profile_text is over ${MAX_PROFILE_TEXT} characters`)
    if (c.profile_text !== storedProfileText) {
        let parsed: unknown
        try { parsed = JSON.parse(c.profile_text) } catch { throw new Error('profile_text must be a JSON object') }
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('profile_text must be a JSON object')
    }
    const yoe = text(c.yoe_context ?? '', 'yoe_context', MAX_YOE_CONTEXT)
    if (!yoe) throw new Error('yoe_context must not be empty')
    // profile_text verbatim: the JEV policy hash covers these bytes.
    return { profile_text: c.profile_text, yoe_context: yoe }
}

// Throws on a malformed patch; returns only the given fields, normalized (trimmed,
// blank entries dropped). The same rules the worker applies to the stored row.
export function validateProfilePatch(input: unknown, storedProfileText?: string): Partial<ProfileFields> {
    const o = obj(input, 'profile')
    const unknown = Object.keys(o).filter((k) => !(PROFILE_FIELDS as readonly string[]).includes(k))
    if (unknown.length) throw new Error(`Unknown profile field(s): ${unknown.join(', ')}`)
    if (!Object.keys(o).length) throw new Error('No profile fields given')
    const out: Partial<ProfileFields> = {}
    for (const [key, [maxItems, maxText]] of Object.entries(LISTS) as [keyof typeof LISTS, readonly [number, number]][]) {
        if (o[key] === undefined) continue
        const clean = list(o[key], key, maxItems).map((x) => text(x, `an entry of ${key}`, maxText)).filter(Boolean)
        out[key] = clean
    }
    if (o.max_age_days !== undefined) {
        const n = o.max_age_days
        if (typeof n !== 'number' || !Number.isInteger(n) || n < 0 || n > MAX_AGE_DAYS) {
            throw new Error(`max_age_days must be a whole number from 0 to ${MAX_AGE_DAYS}`)
        }
        out.max_age_days = n
    }
    if (o.work_authorization !== undefined) {
        const w = text(o.work_authorization, 'work_authorization', MAX_TEXT).toLowerCase()
        if (w && !(WORK_AUTHORIZATIONS as readonly string[]).includes(w)) {
            throw new Error(`work_authorization must be blank or one of: ${WORK_AUTHORIZATIONS.join(', ')}`)
        }
        out.work_authorization = w
    }
    if (o.security_clearance !== undefined) out.security_clearance = text(o.security_clearance, 'security_clearance', MAX_CLEARANCE)
    for (const key of ['exclude_internships', 'exclude_contract'] as const) {
        if (o[key] === undefined) continue
        if (typeof o[key] !== 'boolean') throw new Error(`${key} must be true or false`)
        out[key] = o[key] as boolean
    }
    if (o.education !== undefined) out.education = education(o.education)
    if (o.experience !== undefined) out.experience = experience(o.experience)
    if (o.custom_triage_context !== undefined) out.custom_triage_context = triageContext(o.custom_triage_context, storedProfileText)
    if (o.custom_packs !== undefined) {
        if (o.custom_packs !== null) throw new Error('custom_packs can only be cleared (null): packs are not set here')
        out.custom_packs = null
    }
    return out
}

// --- derived fields (worker: profile.highest_degree / profile.total_years) ---------

export function highestDegree(rows: { degree: string }[]): string {
    const ranks = rows.map((e) => (DEGREES as readonly string[]).indexOf(e.degree)).filter((i) => i >= 0)
    return ranks.length ? DEGREES[Math.max(...ranks)] : ''
}

// Rounded to 0.01 so 1.1 + 2.2 reads 3.3, not 3.3000000000000003.
export const totalYears = (rows: { years: number }[]) =>
    Math.round(rows.reduce((n, e) => n + (Number(e.years) || 0), 0) * 100) / 100

// --- stored row <-> fields -------------------------------------------------------

const JSON_COLUMNS = ['title_include', 'title_exclude', 'locations', 'education', 'experience',
    'target_roles', 'open_to', 'not_interested'] as const

// A field as its column value: lists and rows as compact JSON (the bytes the worker's
// seed writes, so restating a seeded value is a no-op), the context as JSON or null.
export function toColumn(key: ProfileField, value: unknown): unknown {
    if ((JSON_COLUMNS as readonly string[]).includes(key)) return JSON.stringify(value)
    if (key === 'custom_triage_context') {
        const c = value as TriageContext | null
        return c === null ? null : JSON.stringify({ profile_text: c.profile_text, yoe_context: c.yoe_context })
    }
    return value
}

type Row = Record<string, unknown> & { custom_packs: string | null; custom_triage_context: string | null }

// The stored row as the form/MCP read it: parsed fields, derived values, and which
// packs triage uses (their private texts stay out of the read).
export function profileView(row: Row) {
    const fields = Object.fromEntries(JSON_COLUMNS.map((k) => [k, JSON.parse(String(row[k] ?? '[]'))])) as
        Pick<ProfileFields, (typeof JSON_COLUMNS)[number]>
    const context = row.custom_triage_context ? JSON.parse(row.custom_triage_context) as TriageContext : null
    return {
        ...fields,
        max_age_days: Number(row.max_age_days ?? 0),
        work_authorization: String(row.work_authorization ?? ''),
        security_clearance: String(row.security_clearance ?? ''),
        exclude_internships: Boolean(row.exclude_internships),
        exclude_contract: Boolean(row.exclude_contract),
        custom_triage_context: context,
        packs: row.custom_packs ? 'custom' as const : 'default' as const,
        highest_degree: highestDegree(fields.education),
        total_years: totalYears(fields.experience),
        triage_configured: fields.target_roles.length > 0 || context !== null,
        version: Number(row.version),
        actor: String(row.actor),
        changed_at: (row.changed_at as string | null) ?? null,
        confirmed_at: (row.confirmed_at as string | null) ?? null,
    }
}
export type ProfileView = ReturnType<typeof profileView>

// The screen has something to check: same rule as worker config.Candidate.is_empty.
export const requirementsConfigured = (p: Pick<ProfileView, 'education' | 'work_authorization' |
    'security_clearance' | 'locations' | 'exclude_internships' | 'exclude_contract'>) =>
    p.education.length > 0 || !!p.work_authorization.trim() || !!p.security_clearance.trim()
    || p.locations.length > 0 || p.exclude_internships || p.exclude_contract
