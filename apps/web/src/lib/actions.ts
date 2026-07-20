'use server'

import { prisma } from '@/lib/db'
import { Prisma } from '@prisma/client'
import { STATUSES, DEFAULT_CATEGORIES, VALID_SOURCES, RECIPE_SOURCES, LOW_CONTEXT_MAX_DESCRIPTION_LENGTH } from '@/lib/constants'

export async function getApplications(params: {
    page?: number
    size?: number
    status?: string
    historicalStatus?: string
    category?: string
    search?: string
}) {
    const page = Math.max(0, Math.floor(params.page || 0))
    const size = Math.min(100, Math.max(1, Math.floor(params.size || 10)))
    const status = params.status === 'all' ? undefined : params.status
    const historicalStatus = params.historicalStatus === 'all' ? undefined : params.historicalStatus
    const category = params.category === 'all' ? undefined : params.category
    const search = params.search || ''

    const where: Prisma.applicationsWhereInput = {
        AND: [
            status ? { status } : {},
            historicalStatus ? { status_history: { some: { status: historicalStatus } } } : {},
            category ? { category } : {},
            search
                ? {
                    OR: [
                        { company_name: { contains: search } },
                        { job_title: { contains: search } },
                    ],
                }
                : {},
        ],
    }

    const [data, total] = await Promise.all([
        prisma.applications.findMany({
            where,
            skip: page * size,
            take: size,
            orderBy: { date_applied: 'desc' },
        }),
        prisma.applications.count({ where }),
    ])

    return { data, total }
}

// Pipeline statuses still "live" in the discovered queue (scored, not yet applied
// or discarded). Score then sorts them into the Matched vs Discarded buckets.
const ACTIVE_PIPELINE_STATUSES = ['scored', 'notified'] as const

// Discovered Jobs collapses to score-aware buckets (we're testing scoring). Every
// non-lowcontext bucket is mutually exclusive of the derived low-context id set:
//   matched    — live (scored|notified) + fit verdicts are seniority=match AND
//                domain=match AND NOT insufficient_context (the actionable set —
//                the SAME predicate the worker's notify gate uses, so the UI and
//                the Telegram notification never disagree; see matchedIds)
//   belowbar   — live + NOT in the matched id set (scored, but not a verdict match —
//                incl. deep misses; nothing scored is ever orphaned)
//   discarded  — disqualified ONLY: pipeline_status='discarded' with the screen's
//                disqualified:true (hard-constraint failures — the audit view)
//   lowcontext — live but the JD was too thin to score with confidence (derived)
//   failed     — pipeline failure, for monitoring
export type JobBucket = 'matched' | 'belowbar' | 'discarded' | 'failed' | 'lowcontext'

// Within the Discarded (disqualified) audit view you can narrow to one hard-constraint
// cause. The worker writes `disqualification_reason` keyed like "degree: requires phd"
// / "authorization: no visa sponsorship offered" / "clearance: …" / "location: …" /
// "internship/co-op role" (multiple joined by "; "); each cause maps to a LIKE pattern.
export type DisqualifyCause = 'authorization' | 'location' | 'degree' | 'clearance' | 'internship'

// LIKE patterns that recognize each disqualification cause inside the (possibly
// "; "-joined) disqualification_reason string. See disqualifyCauseIds.
const DISQUALIFY_CAUSE_PATTERNS: Record<DisqualifyCause, string> = {
    authorization: '%authorization:%',
    location: '%location:%',
    degree: '%degree:%',
    clearance: '%clearance:%',
    internship: '%internship/co-op%',
}

// Sort for the discovered queue: best match (score) or freshest posting.
export type JobSort = 'score' | 'posted'

function buildJobWhere(params: {
    bucket?: JobBucket
    search?: string
    minScore?: number
}, matchIds: number[]): Prisma.job_postingsWhereInput {
    const bucket = params.bucket ?? 'matched'
    const search = params.search || ''
    const minScore = params.minScore

    let bucketFilter: Prisma.job_postingsWhereInput
    if (bucket === 'failed') {
        bucketFilter = { pipeline_status: 'failed' }
    } else if (bucket === 'discarded') {
        // Disqualified ONLY — hard-constraint screen failures. (Below-threshold scored
        // rows are NOT disqualified; they live in the `belowbar` bucket now.)
        // Substring-match the score_detail JSON; tolerate json.dumps spacing
        // ("disqualified": true) and compact ("disqualified":true).
        bucketFilter = {
            pipeline_status: 'discarded',
            OR: [
                { score_detail: { contains: '"disqualified": true' } },
                { score_detail: { contains: '"disqualified":true' } },
            ],
        }
    } else if (bucket === 'belowbar') {
        // Scored but not a verdict match: live rows outside the matched id set (incl.
        // deep misses — nothing scored is orphaned). ACTIVE rows are never
        // disqualified, so this is cleanly "scored yet not a match". Guarded like the
        // lowIds `notIn`: an empty matchIds must NOT emit `NOT IN ()` (which SQLite/
        // Prisma would treat as excluding nothing rather than excluding everything).
        bucketFilter = {
            pipeline_status: { in: [...ACTIVE_PIPELINE_STATUSES] },
            ...(matchIds.length > 0 ? { id: { notIn: matchIds } } : {}),
        }
    } else {
        // matched — the SAME verdict predicate as the worker's notify gate
        // (seniority=match AND domain=match AND NOT insufficient_context). An empty
        // matchIds correctly yields `id IN ()` → no rows, so no guard needed here.
        bucketFilter = {
            pipeline_status: { in: [...ACTIVE_PIPELINE_STATUSES] },
            id: { in: matchIds },
        }
    }

    return {
        AND: [
            bucketFilter,
            minScore != null ? { score: { gte: minScore } } : {},
            search
                ? { OR: [{ company_name: { contains: search } }, { job_title: { contains: search } }] }
                : {},
        ],
    }
}

// Ids of discarded postings whose `disqualification_reason` matches one hard-constraint
// cause. Prisma's typed `where` can't reach into the score_detail JSON, so — mirroring
// lowContextIds — we fetch the matching ids once with a raw query (SQLite json_extract)
// and layer them onto the discarded bucket query (id `in`). The LIKE pattern recognizes
// the worker's keyed reason ("degree: …", "internship/co-op role") even inside a
// "; "-joined multi-cause reason. An empty result → `id IN ()` → an (intentionally)
// empty view, so no guard is needed.
async function disqualifyCauseIds(cause: DisqualifyCause): Promise<number[]> {
    const pattern = DISQUALIFY_CAUSE_PATTERNS[cause]
    const rows = await prisma.$queryRaw<Array<{ id: number | bigint }>>`
        SELECT id FROM job_postings
        WHERE pipeline_status = 'discarded'
          AND json_extract(score_detail, '$.disqualification_reason') LIKE ${pattern}
    `
    return rows.map((r) => Number(r.id))
}

// Ids of "low-context" postings: a JD too thin to score with confidence. Two signals,
// either one qualifies (OR):
//   1. a short description body — derived at query time from TRIM(description) length
//      (< LOW_CONTEXT_MAX_DESCRIPTION_LENGTH); the ingest gate only rejects EMPTY JDs.
//   2. the fit scorer's persisted `insufficient_context: true` flag in score_detail —
//      the LLM judged the JD too boilerplate/truncated to assess even at full length.
// Prisma's typed `where` can't express LENGTH(...)/json_extract, so we fetch the ids
// with a raw query and layer them onto the typed bucket queries (id `in` for the
// low-context bucket, `notIn` for every other bucket) — keeping buckets mutually
// exclusive without touching buildJobWhere. Scope: only rows that actually received a
// fit score (scored|notified); disqualified/failed/applied/removed keep their own buckets.
async function lowContextIds(): Promise<number[]> {
    const rows = await prisma.$queryRaw<Array<{ id: number | bigint }>>`
        SELECT id FROM job_postings
        WHERE pipeline_status IN ('scored', 'notified')
          AND (
                LENGTH(TRIM(description)) < ${LOW_CONTEXT_MAX_DESCRIPTION_LENGTH}
             OR json_extract(score_detail, '$.insufficient_context') = 1
          )
    `
    return rows.map((r) => Number(r.id))
}

// Ids of "matched" postings: the SAME verdict predicate as the worker's notify gate
// (ats_worker/db.py get_notifiable) — seniority=match AND domain=match AND NOT
// insufficient_context — so the UI's Matched tab and the Telegram notification never
// disagree. Score alone is a rubric-band-quantized number that flips run-to-run near
// the old threshold; the verdicts are stable (see PROGRESS.md). Prisma's typed
// `where` can't reach into the score_detail JSON, so — mirroring lowContextIds — we
// fetch the matching ids once with a raw query and layer them onto the matched/
// belowbar bucket queries (id `in` for matched, `notIn` for belowbar). Scope: only
// rows that actually received a fit score (scored|notified).
async function matchedIds(): Promise<number[]> {
    const rows = await prisma.$queryRaw<Array<{ id: number | bigint }>>`
        SELECT id FROM job_postings
        WHERE pipeline_status IN ('scored', 'notified')
          AND json_extract(score_detail, '$.assessment.seniority.verdict') = 'match'
          AND json_extract(score_detail, '$.assessment.domain.verdict') = 'match'
          AND COALESCE(json_extract(score_detail, '$.insufficient_context'), 0) <> 1
    `
    return rows.map((r) => Number(r.id))
}

export async function getJobPostings(params: {
    bucket?: JobBucket
    search?: string
    page?: number
    size?: number
    minScore?: number
    cause?: DisqualifyCause
    sort?: JobSort
}) {
    const page = Math.max(0, Math.floor(params.page ?? 0))
    const size = Math.min(100, Math.max(1, Math.floor(params.size ?? 25)))
    const search = params.search || ''
    const minScore = params.minScore

    const [lowIds, matchIds] = await Promise.all([lowContextIds(), matchedIds()])
    let where: Prisma.job_postingsWhereInput
    if (params.bucket === 'lowcontext') {
        // The low-context bucket IS the thin-JD id set, plus the shared search/minScore filters.
        where = {
            AND: [
                { id: { in: lowIds } },
                minScore != null ? { score: { gte: minScore } } : {},
                search
                    ? { OR: [{ company_name: { contains: search } }, { job_title: { contains: search } }] }
                    : {},
            ],
        }
    } else {
        // Every other bucket EXCLUDES the low-context rows so the tabs stay mutually
        // exclusive (a thin-JD scored row shows only under Low-context). Append the
        // exclusion as a peer clause (keeping buildJobWhere's flat AND shape); guarded
        // so an empty set doesn't emit a `NOT IN ()`.
        const base = buildJobWhere(params, matchIds)
        // Discarded-only cause sub-filter: layer the raw-query id set as `id IN`.
        const causeClause =
            params.bucket === 'discarded' && params.cause
                ? [{ id: { in: await disqualifyCauseIds(params.cause) } }]
                : []
        where = {
            AND: [
                ...(base.AND as Prisma.job_postingsWhereInput[]),
                ...causeClause,
                ...(lowIds.length > 0 ? [{ id: { notIn: lowIds } }] : []),
            ],
        }
    }

    const orderBy: Prisma.job_postingsOrderByWithRelationInput[] =
        params.sort === 'posted'
            ? [{ posted_at: 'desc' }, { id: 'desc' }]
            : [{ score: 'desc' }, { id: 'asc' }]

    const [data, total] = await Promise.all([
        prisma.job_postings.findMany({ where, orderBy, skip: page * size, take: size }),
        prisma.job_postings.count({ where }),
    ])

    return { data, total }
}

// Per-row dismiss. Writes 'removed' (hidden from every bucket, like bulk Remove) — NOT
// 'discarded'. The Discarded bucket is reserved for the screen's auto-disqualifications,
// so a hand-dismissed row must not masquerade as one (it would also be unreopenable,
// matching no bucket). Reopen a genuine disqualification from the Discarded view instead.
export async function discardJobPosting(id: number) {
    try {
        await prisma.job_postings.update({
            where: { id },
            data: { pipeline_status: 'removed', updated_at: new Date().toISOString() },
        })
        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

// Reverse a discard (whether user-initiated or an LLM disqualification): send the
// posting back into the actionable queue. The stored score_detail — including any
// disqualification_reason — is kept, so the override stays explainable.
export async function reopenJobPosting(id: number) {
    try {
        await prisma.job_postings.update({
            where: { id },
            data: { pipeline_status: 'scored', updated_at: new Date().toISOString() },
        })
        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

// Terminal hide: a 'removed' posting is invisible to every bucket query and inert
// to the worker (ingest is ON CONFLICT DO NOTHING; the pipeline only selects by
// explicit status), so it never re-scores/re-notifies. See the design spec.
export async function bulkRemove(ids: number[]) {
    try {
        const res = await prisma.job_postings.updateMany({
            where: { id: { in: ids } },
            data: { pipeline_status: 'removed', updated_at: new Date().toISOString() },
        })
        return { success: true, count: res.count }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function bulkReopen(ids: number[]) {
    try {
        const res = await prisma.job_postings.updateMany({
            where: { id: { in: ids } },
            data: { pipeline_status: 'scored', updated_at: new Date().toISOString() },
        })
        return { success: true, count: res.count }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

// Clear the whole current Discarded view in one click (respects bucket + cause
// sub-filter + search + minScore via the same where-builder getJobPostings uses).
export async function removeAllInView(filter: {
    bucket?: JobBucket
    search?: string
    minScore?: number
    cause?: DisqualifyCause
}) {
    try {
        const [lowIds, matchIds] = await Promise.all([lowContextIds(), matchedIds()])
        const base = buildJobWhere(filter, matchIds)
        const causeClause =
            filter.bucket === 'discarded' && filter.cause
                ? [{ id: { in: await disqualifyCauseIds(filter.cause) } }]
                : []
        // Mirror getJobPostings' "every other bucket" exclusion (buildJobWhere has no
        // lowcontext case of its own — see getJobPostings) so a bulk-remove can never
        // sweep up a row that's actually showing under the Low-context tab. Same guard:
        // an empty lowIds must not emit `NOT IN ()`. No-op today (the button only shows
        // on Discarded, whose pipeline_status='discarded' never overlaps lowContextIds'
        // scored|notified scope) — defensive if the button is ever exposed elsewhere.
        const where: Prisma.job_postingsWhereInput = {
            AND: [
                ...(base.AND as Prisma.job_postingsWhereInput[]),
                ...causeClause,
                ...(lowIds.length > 0 ? [{ id: { notIn: lowIds } }] : []),
            ],
        }
        const res = await prisma.job_postings.updateMany({
            where,
            data: { pipeline_status: 'removed', updated_at: new Date().toISOString() },
        })
        return { success: true, count: res.count }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function markJobApplied(id: number, category?: string) {
    try {
        const posting = await prisma.job_postings.findUnique({ where: { id } })
        if (!posting) {
            return { success: false, error: 'Job posting not found' }
        }

        // Category is a free-form user label chosen at apply time; keep whatever's
        // given, falling back to 'Others' only when blank (or old callers pass nothing).
        const cat = category?.trim() || 'Others'
        const today = new Date().toISOString().split('T')[0]

        // Create the application and backfill the job_postings link atomically so we
        // can never end up with an application that has no back-link (or vice versa).
        const result = await prisma.$transaction(async (tx) => {
            const existing = await tx.applications.findFirst({
                where: {
                    company_name: posting.company_name,
                    job_title: posting.job_title,
                },
            })
            if (existing) {
                // Throw to roll back the transaction; surfaced as a failure below.
                throw new Error(
                    `Application for ${posting.company_name} - ${posting.job_title} already exists`
                )
            }

            const newApp = await tx.applications.create({
                data: {
                    company_name: posting.company_name,
                    job_title: posting.job_title,
                    application_url: posting.job_url || '',
                    date_applied: today,
                    category: cat,
                    status: 'Applied',
                    notes: '',
                    last_updated: new Date().toISOString(),
                },
            })

            await tx.job_postings.update({
                where: { id },
                data: {
                    pipeline_status: 'applied',
                    application_id: newApp.id,
                    updated_at: new Date().toISOString(),
                },
            })

            return newApp
        })

        return { success: true, data: result }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function addApplication(data: {
    company_name: string
    job_title: string
    date_applied: string
    category?: string
    status?: string
    application_url?: string
    notes?: string
}) {
    try {
        if (!data.company_name || !data.job_title || !data.date_applied) {
            return { success: false, error: 'Missing required fields' }
        }

        const status = (STATUSES as readonly string[]).includes(data.status ?? '') ? data.status! : 'Applied'
        const category = data.category?.trim() || 'Others'

        const newApp = await prisma.$transaction(async (tx) => {
            const existing = await tx.applications.findFirst({
                where: {
                    company_name: data.company_name,
                    job_title: data.job_title,
                },
            })
            if (existing) {
                // Throw to roll back the transaction; surfaced as a failure below.
                throw new Error(
                    `Application for ${data.company_name} - ${data.job_title} already exists`
                )
            }

            return tx.applications.create({
                data: {
                    company_name: data.company_name,
                    job_title: data.job_title,
                    date_applied: data.date_applied,
                    category,
                    status,
                    application_url: data.application_url || '',
                    notes: data.notes || '',
                    last_updated: new Date().toISOString(),
                },
            })
        })

        return { success: true, data: newApp }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function updateApplicationDetails(
    id: number,
    data: {
        company_name: string
        job_title: string
        category: string
        application_url?: string
        date_applied?: string
        notes?: string
    }
) {
    try {
        const category = data.category?.trim() || 'Others'

        await prisma.applications.update({
            where: { id },
            data: {
                company_name: data.company_name,
                job_title: data.job_title,
                category,
                application_url: data.application_url ?? undefined,
                date_applied: data.date_applied ?? undefined,
                notes: data.notes ?? undefined,
                last_updated: new Date().toISOString(),
            },
        })
        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function updateApplicationStatus(id: number, status: string, date?: string) {
    try {
        if (!STATUSES.includes(status as any)) {
            return { success: false, error: 'Invalid status' }
        }

        const app = await prisma.applications.findUnique({ where: { id } })
        if (!app) {
            return { success: false, error: 'Application not found' }
        }

        if (app.status === status) {
            return { success: false, error: `Application is already in '${status}' status` }
        }

        // Determine timestamp: use provided date (append noon UTC so it doesn't shift days in local timezones) or current time
        const timestamp = date ? new Date(`${date}T12:00:00Z`).toISOString() : new Date().toISOString()

        await prisma.$transaction(async (tx) => {
            await tx.applications.update({
                where: { id },
                data: { status, last_updated: new Date().toISOString() },
            })

            await tx.status_history.create({
                data: {
                    application_id: id,
                    status,
                    timestamp,
                },
            })
        })

        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function getKPIs() {
    const apps = await prisma.applications.findMany()

    const stats = {
        applied: 0,
        active: 0,
        assessment: 0,
        interviewing: 0,
        rejected: 0,
        offer: 0,
    }

    stats.applied = apps.length

    let withdrew = 0
    let ghosted = 0

    for (const app of apps) {
        const status = app.status.toLowerCase()
        if (status === 'online assessment') stats.assessment += 1
        else if (status === 'phone screen' || status.includes('interviewing') || status === 'final round') stats.interviewing += 1
        else if (status === 'rejected') stats.rejected += 1
        else if (status === 'offer' || status === 'accepted') stats.offer += 1
        else if (status === 'withdrew') withdrew += 1
        else if (status === 'ghosted') ghosted += 1
    }

    stats.active = apps.length - stats.rejected - stats.offer - withdrew - ghosted

    return stats
}

export async function deleteApplication(id: number) {
    try {
        await prisma.applications.delete({
            where: { id },
        })
        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function getApplicationHistory(id: number) {
    try {
        const history = await prisma.status_history.findMany({
            where: { application_id: id },
            orderBy: { timestamp: 'desc' },
        })
        return { success: true, data: history }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function deleteHistoryItem(id: number) {
    try {
        // Find the history item first to get the application_id
        const item = await prisma.status_history.findUnique({
            where: { id },
            select: { application_id: true }
        })

        if (!item) {
            return { success: false, error: 'History item not found' }
        }

        await prisma.$transaction(async (tx) => {
            await tx.status_history.delete({
                where: { id },
            })

            // Find the most recent history item after deletion
            const latestHistory = await tx.status_history.findFirst({
                where: { application_id: item.application_id },
                orderBy: { timestamp: 'desc' }
            })

            // Update application status to the most recent history, or 'Applied' if empty
            const newStatus = latestHistory ? latestHistory.status : 'Applied'
            await tx.applications.update({
                where: { id: item.application_id },
                data: { status: newStatus }
            })
        })

        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function getStatusFlow() {
    try {
        const apps = await prisma.applications.findMany({
            include: { status_history: { orderBy: { timestamp: 'asc' } } },
        })

        const transitions: { from: string; to: string }[] = []

        for (const app of apps) {
            const history = app.status_history

            if (history.length === 0) {
                // No history at all — just use current status
                const to = app.status === 'Applied' ? 'No Response' : app.status
                transitions.push({ from: 'Applied', to })
            } else {
                // Build the full chain: start with Applied, then each history entry
                const chain: string[] = ['Applied']
                for (const h of history) {
                    // Avoid duplicate consecutive statuses
                    if (chain[chain.length - 1] !== h.status) {
                        chain.push(h.status)
                    }
                }
                // If current status differs from last history entry, add it
                if (chain[chain.length - 1] !== app.status) {
                    chain.push(app.status === 'Applied' ? 'No Response' : app.status)
                }
                // If chain is just ['Applied'] with no transitions, mark as No Response
                if (chain.length === 1) {
                    transitions.push({ from: 'Applied', to: 'No Response' })
                } else {
                    for (let i = 0; i < chain.length - 1; i++) {
                        transitions.push({ from: chain[i], to: chain[i + 1] })
                    }
                }
            }
        }

        const flowMap = new Map<string, number>()
        for (const t of transitions) {
            const key = `${t.from}|||${t.to}`
            flowMap.set(key, (flowMap.get(key) || 0) + 1)
        }

        const flows = Array.from(flowMap.entries()).map(([key, value]) => {
            const [from, to] = key.split('|||')
            return { from, to, value }
        })

        return { success: true, data: flows }
    } catch (error: any) {
        return { success: false, error: error.message, data: [] }
    }
}

export async function getTimelineData() {
    try {
        const apps = await prisma.applications.findMany({
            select: { date_applied: true },
        })

        const counts = new Map<string, number>()
        for (const app of apps) {
            const date = app.date_applied.split('T')[0]
            counts.set(date, (counts.get(date) || 0) + 1)
        }

        const data = Array.from(counts.entries())
            .map(([date, count]) => ({ date, count }))
            .sort((a, b) => a.date.localeCompare(b.date))

        return { success: true, data }
    } catch (error: any) {
        return { success: false, error: error.message, data: [] }
    }
}

export async function getCategoryData() {
    try {
        const apps = await prisma.applications.findMany({
            select: { category: true },
        })

        const counts = new Map<string, number>()
        for (const app of apps) {
            const cat = app.category || 'Others'
            counts.set(cat, (counts.get(cat) || 0) + 1)
        }

        const data = Array.from(counts.entries())
            .map(([name, value]) => ({ name, value }))
            .sort((a, b) => b.value - a.value)

        return { success: true, data }
    } catch (error: any) {
        return { success: false, error: error.message, data: [] }
    }
}

const CSV_COLUMNS = [
    'company_name',
    'job_title',
    'application_url',
    'date_applied',
    'category',
    'status',
    'notes',
    'last_updated',
] as const

function csvEscape(value: string | null | undefined): string {
    if (value === null || value === undefined) return ''
    let s = String(value)
    // Formula-injection + reversibility guard: a cell whose first char is one a spreadsheet
    // may treat as a formula lead (= + - @, or a tab/CR) — OR a cell that already starts with
    // `'` — is prefixed with a single quote so Excel/Sheets render it as literal text. Guarding
    // a leading `'` too (not just formula-lead chars) makes this a proper bijection with get()'s
    // strip below: every value, including ones that start with an apostrophe, round-trips
    // losslessly through export -> import. Prefix BEFORE the quote check so a comma-bearing
    // cell still gets wrapped.
    if (/^['=+\-@\t\r]/.test(s)) s = "'" + s
    if (/[",\r\n]/.test(s)) {
        return `"${s.replace(/"/g, '""')}"`
    }
    return s
}

function parseCSV(text: string): string[][] {
    const rows: string[][] = []
    let row: string[] = []
    let field = ''
    let inQuotes = false
    let i = 0
    while (i < text.length) {
        const ch = text[i]
        if (inQuotes) {
            if (ch === '"') {
                if (text[i + 1] === '"') {
                    field += '"'
                    i += 2
                    continue
                }
                inQuotes = false
                i++
                continue
            }
            field += ch
            i++
            continue
        }
        if (ch === '"') {
            inQuotes = true
            i++
            continue
        }
        if (ch === ',') {
            row.push(field)
            field = ''
            i++
            continue
        }
        if (ch === '\r') {
            i++
            continue
        }
        if (ch === '\n') {
            row.push(field)
            rows.push(row)
            row = []
            field = ''
            i++
            continue
        }
        field += ch
        i++
    }
    if (field.length > 0 || row.length > 0) {
        row.push(field)
        rows.push(row)
    }
    return rows.filter((r) => r.length > 0 && !(r.length === 1 && r[0] === ''))
}

export async function exportApplicationsCSV() {
    try {
        const apps = await prisma.applications.findMany({
            orderBy: { date_applied: 'desc' },
        })

        const header = CSV_COLUMNS.join(',')
        const lines = apps.map((app) =>
            CSV_COLUMNS.map((col) => csvEscape((app as any)[col])).join(',')
        )

        const csv = [header, ...lines].join('\n') + '\n'
        return { success: true, csv, count: apps.length }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function importApplicationsCSV(csvText: string) {
    try {
        const rows = parseCSV(csvText)
        if (rows.length === 0) {
            return { success: false, error: 'CSV is empty' }
        }

        const header = rows[0].map((h) => h.trim())
        const dataRows = rows.slice(1)

        const required = ['company_name', 'job_title', 'date_applied']
        for (const r of required) {
            if (!header.includes(r)) {
                return { success: false, error: `Missing required column: ${r}` }
            }
        }

        const colIndex = (name: string) => header.indexOf(name)
        const statusSet = new Set<string>(STATUSES as readonly string[])

        const CHUNK = 100
        let added = 0
        let skipped = 0
        const errors: string[] = []

        for (let start = 0; start < dataRows.length; start += CHUNK) {
            const batch = dataRows.slice(start, start + CHUNK)

            const r = await prisma.$transaction(async (tx) => {
                let a = 0
                let s = 0
                const e: string[] = []

                for (let j = 0; j < batch.length; j++) {
                    const row = batch[j]
                    const rowNum = start + j + 2

                    const get = (col: string) => {
                        const idx = colIndex(col)
                        if (idx === -1) return ''
                        let v = (row[idx] ?? '').trim()
                        // Reverse csvEscape's guard: strip a single leading `'` only when the
                        // rest of the value also starts with a formula-lead char or another `'`
                        // — the exact inverse of the export-side prepend above, so a value that
                        // never went through csvEscape (e.g. "O'Brien", no guard char following
                        // the `'`) is left untouched, while a guarded value (including one whose
                        // original first char was itself `'`) round-trips exactly.
                        if (v[0] === "'" && /^['=+\-@\t\r]/.test(v.slice(1))) v = v.slice(1)
                        return v
                    }

                    const company_name = get('company_name')
                    const job_title = get('job_title')
                    const date_applied = get('date_applied')

                    if (!company_name || !job_title || !date_applied) {
                        e.push(`Row ${rowNum}: missing required field`)
                        continue
                    }

                    const existing = await tx.applications.findFirst({
                        where: { company_name, job_title },
                    })
                    if (existing) {
                        s++
                        continue
                    }

                    const rawStatus = get('status') || 'Applied'
                    const status = statusSet.has(rawStatus) ? rawStatus : 'Applied'
                    // Category is free-form (the user's own vocabulary) — keep whatever
                    // the CSV supplies, defaulting only when blank.
                    const category = (get('category') || '').trim() || 'Others'

                    await tx.applications.create({
                        data: {
                            company_name,
                            job_title,
                            date_applied,
                            category,
                            status,
                            application_url: get('application_url') || '',
                            notes: get('notes') || '',
                            last_updated: new Date().toISOString(),
                        },
                    })
                    a++
                }

                return { a, s, e }
            }, { timeout: 15_000 })

            added += r.a
            skipped += r.s
            errors.push(...r.e)
        }

        return { success: true, added, skipped, errors }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

// --- Watchlist (DB-backed; the worker fetches these companies in full) ------
// The watchlist moved out of the worker's config.yaml into the DB so it can be
// managed here. A future step adds promotion suggestions (feed -> watchlist);
// for now this is manual list / add / remove.

export async function getWatchedCompanies() {
    const [data, total] = await Promise.all([
        prisma.watched_companies.findMany({ orderBy: { name: 'asc' } }),
        prisma.watched_companies.count(),
    ])
    return { data, total }
}

export async function addWatchedCompany(input: {
    source: string
    slug: string
    name: string
    recipe?: string
}) {
    try {
        const source = (input.source || '').trim()
        const slug = (input.slug || '').trim()
        const name = (input.name || '').trim()
        const recipeRaw = (input.recipe || '').trim()
        if (!source || !slug || !name) {
            return { success: false, error: 'source, slug, and name are required' }
        }
        // Slug is interpolated into a fetch URL host/path in the worker
        // (e.g. https://{slug}.icims.com). Allow alnum . _ - and single '/'-joined
        // segments (workday "tenant/dc/site", phenom "host/domain"); block host-injection
        // metacharacters (@ : ? # % \ whitespace) and path traversal.
        if (!/^[A-Za-z0-9._/-]+$/.test(slug) || slug.includes('..') ||
            slug.startsWith('/') || slug.endsWith('/') || slug.includes('//')) {
            return { success: false, error: 'slug contains invalid characters' }
        }
        if (!(VALID_SOURCES as readonly string[]).includes(source)) {
            return { success: false, error: `Unknown source: ${source}` }
        }

        // custom/browser rows are recipe-driven: parse the JSON and require it.
        let recipe: string | null = null
        if (recipeRaw) {
            let parsed: unknown
            try {
                parsed = JSON.parse(recipeRaw)
            } catch {
                return { success: false, error: 'recipe must be valid JSON' }
            }
            if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
                return { success: false, error: 'recipe must be a JSON object' }
            }
            recipe = JSON.stringify(parsed)   // store normalized JSON
        }
        if ((RECIPE_SOURCES as readonly string[]).includes(source) && !recipe) {
            return { success: false, error: `source '${source}' requires a recipe (JSON object)` }
        }

        const existing = await prisma.watched_companies.findFirst({
            where: { source, slug },
        })
        if (existing) {
            return { success: false, error: `${source}/${slug} is already on the watchlist` }
        }

        const created = await prisma.watched_companies.create({
            data: { source, slug, name, recipe, created_at: new Date().toISOString() },
        })
        return { success: true, data: created }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function removeWatchedCompany(id: number) {
    try {
        await prisma.watched_companies.delete({ where: { id } })
        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

// --- Categories (DB-backed vocabulary the user picks at onboarding) ----------
// The application-category list lives in one app_settings row (key='categories',
// value = a JSON string array) so a user can pick their own field's labels instead
// of the built-in DEFAULT_CATEGORIES. Categories are free-form: they drive only the
// dropdowns and the donut, never any pipeline logic.

export async function getCategories(): Promise<{ categories: string[]; configured: boolean }> {
    const row = await prisma.app_settings.findUnique({ where: { key: 'categories' } })
    if (!row) return { categories: [...DEFAULT_CATEGORIES], configured: false }
    try {
        const parsed = JSON.parse(row.value)
        const categories = Array.isArray(parsed)
            ? parsed.map((c) => String(c)).filter((c) => c.trim())
            : []
        // An empty / garbage stored value falls back to defaults and reads as
        // NOT configured, so the first-run prompt still offers to set a real list.
        if (categories.length === 0) return { categories: [...DEFAULT_CATEGORIES], configured: false }
        return { categories, configured: true }
    } catch {
        return { categories: [...DEFAULT_CATEGORIES], configured: false }
    }
}

export async function setCategories(list: string[]) {
    try {
        // Trim, drop blanks, dedupe case-insensitively (first spelling wins). Order
        // is preserved — it's the dropdown order the user sees.
        const seen = new Set<string>()
        const categories: string[] = []
        for (const raw of list ?? []) {
            const c = String(raw).trim()
            if (c && !seen.has(c.toLowerCase())) {
                seen.add(c.toLowerCase())
                categories.push(c)
            }
        }
        if (categories.length === 0) {
            return { success: false, error: 'Pick at least one category' }
        }
        const now = new Date().toISOString()
        const value = JSON.stringify(categories)
        await prisma.app_settings.upsert({
            where: { key: 'categories' },
            update: { value, updated_at: now },
            create: { key: 'categories', value, updated_at: now },
        })
        return { success: true, data: categories }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}
