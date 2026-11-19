'use server'

import { prisma } from '@/lib/db'
import { type Actor, WORK_AUTHORIZATIONS } from '@/lib/constants'
import { checkedActor } from '@/lib/action-helpers'

// --- Candidate preferences (#157): the screen's hard requirements --------------
// One row (id=1) the worker reads each pass. A set merges the given fields over the
// stored ones; an actual change bumps `version`, stamps `changed_at` (screens completed
// before it are stale) and is audited with the row it replaced. A no-op writes nothing.

const MAX_PREFERENCE_TEXT = 100
const MAX_LOCATIONS = 50
const PREFERENCE_TEXT = ['highest_degree', 'work_authorization', 'security_clearance'] as const

function parsePreferences(input: Record<string, unknown>) {
    const unknown = Object.keys(input).filter((k) =>
        !(PREFERENCE_TEXT as readonly string[]).includes(k) && k !== 'locations' && k !== 'exclude_internships')
    if (unknown.length) throw new Error(`Unknown preference field(s): ${unknown.join(', ')}`)
    if (!Object.keys(input).length) throw new Error('No preference fields given')
    const out: Record<string, string | boolean> = {}
    for (const key of PREFERENCE_TEXT) {
        if (input[key] === undefined) continue
        if (typeof input[key] !== 'string') throw new Error(`${key} must be a string`)
        const value = (input[key] as string).trim()
        if (value.length > MAX_PREFERENCE_TEXT) throw new Error(`${key} is over ${MAX_PREFERENCE_TEXT} characters`)
        out[key] = value
    }
    if (out.work_authorization !== undefined) {
        out.work_authorization = (out.work_authorization as string).toLowerCase()
        if (out.work_authorization && !(WORK_AUTHORIZATIONS as readonly string[]).includes(out.work_authorization)) {
            throw new Error(`work_authorization must be blank or one of: ${WORK_AUTHORIZATIONS.join(', ')}`)
        }
    }
    if (input.locations !== undefined) {
        const list = input.locations
        if (!Array.isArray(list) || list.some((l) => typeof l !== 'string')) throw new Error('locations must be a list of strings')
        const clean = (list as string[]).map((l) => l.trim()).filter(Boolean)
        if (clean.length > MAX_LOCATIONS) throw new Error(`locations has over ${MAX_LOCATIONS} entries`)
        if (clean.some((l) => l.length > MAX_PREFERENCE_TEXT)) throw new Error(`a location is over ${MAX_PREFERENCE_TEXT} characters`)
        out.locations = JSON.stringify(clean)
    }
    if (input.exclude_internships !== undefined) {
        if (typeof input.exclude_internships !== 'boolean') throw new Error('exclude_internships must be true or false')
        out.exclude_internships = input.exclude_internships
    }
    return out
}

export async function setCandidatePreferences(input: Record<string, unknown>, actor: Actor = 'web') {
    checkedActor(actor)
    try {
        const fields = parsePreferences(input)
        const data = await prisma.$transaction(async (tx) => {
            const before = await tx.candidate_preferences.findUnique({ where: { id: 1 } })
            if (before && Object.entries(fields).every(([k, v]) => (before as Record<string, unknown>)[k] === v)) {
                return { ...before, unchanged: true }
            }
            const now = new Date().toISOString()
            const stamp = { ...fields, actor, changed_at: now, updated_at: now }
            const row = await tx.candidate_preferences.upsert({
                where: { id: 1 },
                create: { id: 1, version: 1, ...stamp },
                update: { ...stamp, version: { increment: 1 } },
            })
            await tx.audit_log.create({ data: {
                at: now, actor, action: before ? 'update' : 'add', entity: 'candidate_preferences', entity_id: 1,
                payload: JSON.stringify(before ? { before, after: row } : row),
            } })
            return { ...row, unchanged: false }
        })
        return { success: true, data: { ...data, locations: JSON.parse(data.locations) } }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

// --- JEV profile (#157): the keep/skip filter's profile and experience facts -----
// The worker seeds row id=1 from config `jev_dir` (question packs included, and those
// come only from there). This updates the profile text and/or the experience context;
// a change bumps `version` and is audited. The policy hash covers both, so the next JEV
// pass re-assesses every in-window posting.

const MAX_JEV_PROFILE = 16000
const MAX_YOE_CONTEXT = 2000

// The Settings dialog's read: both stored rows (null until seeded or set) and how many
// postings a JEV profile change would re-assess. The count mirrors the worker's JEV
// eligibility (db._JEV_ELIGIBLE + pipeline.JEV_MAX_AGE_DAYS) and MCP get_jev_profile.
export async function getSettings() {
    const since = new Date(Date.now() - 7 * 86_400_000).toISOString().slice(0, 10)
    const [prefs, jev, counted] = await Promise.all([
        prisma.candidate_preferences.findUnique({ where: { id: 1 } }),
        prisma.jev_profile.findUnique({
            where: { id: 1 }, select: { profile_text: true, yoe_context: true, version: true, actor: true, changed_at: true },
        }),
        prisma.$queryRaw<{ n: bigint | number }[]>`SELECT COUNT(*) AS n FROM job_postings p
            JOIN job_screenings s ON s.job_posting_id = p.id
            WHERE p.pipeline_status = 'new' AND s.state = 'complete' AND json_valid(s.result_json)
              AND COALESCE(json_extract(s.result_json, '$.disqualified'), 0) = 0
              AND substr(COALESCE(p.posted_at, p.created_at), 1, 10) >= ${since}`,
    ])
    return {
        preferences: prefs ? { ...prefs, locations: JSON.parse(prefs.locations) as string[] } : null,
        jev,
        reassessOnChange: Number(counted[0]?.n ?? 0),
    }
}

export async function setJevProfile(input: Record<string, unknown>, actor: Actor = 'web') {
    checkedActor(actor)
    try {
        const unknown = Object.keys(input).filter((k) => k !== 'profile_text' && k !== 'yoe_context')
        if (unknown.length) throw new Error(`Only profile_text and yoe_context can be set (got ${unknown.join(', ')}); question packs come from jev_dir`)
        const fields: { profile_text?: string; yoe_context?: string } = {}
        if (input.profile_text !== undefined) {
            if (typeof input.profile_text !== 'string') throw new Error('profile_text must be a string')
            if (input.profile_text.length > MAX_JEV_PROFILE) throw new Error(`profile_text is over ${MAX_JEV_PROFILE} characters`)
            let parsed: unknown
            try { parsed = JSON.parse(input.profile_text) } catch { throw new Error('profile_text must be a JSON object') }
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('profile_text must be a JSON object')
            fields.profile_text = input.profile_text // verbatim: the policy hash covers these bytes
        }
        if (input.yoe_context !== undefined) {
            if (typeof input.yoe_context !== 'string') throw new Error('yoe_context must be a string')
            const text = input.yoe_context.trim()
            if (!text) throw new Error('yoe_context must not be empty')
            if (text.length > MAX_YOE_CONTEXT) throw new Error(`yoe_context is over ${MAX_YOE_CONTEXT} characters`)
            fields.yoe_context = text
        }
        if (!Object.keys(fields).length) throw new Error('Give profile_text and/or yoe_context')
        const data = await prisma.$transaction(async (tx) => {
            const before = await tx.jev_profile.findUnique({ where: { id: 1 } })
            if (!before) throw new Error('No JEV profile is stored yet: the worker seeds it from jev_dir, which also supplies the question packs')
            const pick = (r: typeof before) => ({ version: r.version, profile_text: r.profile_text, yoe_context: r.yoe_context })
            if (Object.entries(fields).every(([k, v]) => (before as Record<string, unknown>)[k] === v)) {
                return { version: before.version, changed_at: before.changed_at, unchanged: true }
            }
            const now = new Date().toISOString()
            const row = await tx.jev_profile.update({
                where: { id: 1 }, data: { ...fields, actor, changed_at: now, updated_at: now, version: { increment: 1 } },
            })
            await tx.audit_log.create({ data: {
                at: now, actor, action: 'update', entity: 'jev_profile', entity_id: 1,
                payload: JSON.stringify({ before: pick(before), after: pick(row) }),
            } })
            return { version: row.version, changed_at: row.changed_at, unchanged: false }
        })
        return { success: true, data }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}
