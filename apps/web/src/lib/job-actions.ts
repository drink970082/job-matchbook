'use server'

import { prisma } from '@/lib/db'
import { Prisma } from '@prisma/client'
import { type Actor } from '@/lib/constants'
import { todayISO } from '@/lib/utils'
import { legacyScreenEvidence, SCREEN_OUTCOMES, standaloneScreenSummary, type ScreenOutcome } from '@/lib/screen-summary'
import { sourceLifecycleSummary } from '@/lib/source-lifecycle'
import { jobTriageSummary } from '@/lib/triage-summary'
import { applicationAudit, checkedActor, checkedDate, unlinkedApplications, writeInitialHistory, CATEGORY_FALLBACK } from '@/lib/action-helpers'
import { bestApplication } from '@/lib/application-match'
import { JOB_STAGES, type JobStage, type JobStageFilter } from '@/lib/job-stages'

export type { JobStage, JobStageFilter }

// The funnel stages and their meaning: lib/job-stages.ts.
export type JobSort = 'posted' // newest posted only (#207); no fit or fetched order
export type JobSearchScope = 'metadata' | 'all_text'

// 'for_you' (the default) is the Discovered Jobs view (#207); the funnel stages stay for
// the parity tests and the MCP routes' `{stage: 'all'}` scope.
export type JobView = JobStageFilter | 'for_you'

export interface JobPostingsFilter {
    stage?: JobView
    search?: string
    searchScope?: JobSearchScope
    screenOutcome?: ScreenOutcome
    postedSince?: string // YYYY-MM-DD, the viewer's local cutoff date (inclusive)
    page?: number
    size?: number
    sort?: JobSort
}

export type JobViewScope = Omit<JobPostingsFilter, 'page' | 'size'>

const JOB_SORTS: readonly JobSort[] = ['posted']
const JOB_SEARCH_SCOPES: readonly JobSearchScope[] = ['metadata', 'all_text']
const JOB_FILTER_KEYS = new Set(['stage', 'search', 'searchScope', 'screenOutcome', 'postedSince', 'page', 'size', 'sort'])
const MAX_JOB_SEARCH_CHARS = 200

function validateJobPostingsFilter(filter: unknown, allowPaging = true): asserts filter is JobPostingsFilter {
    if (!filter || typeof filter !== 'object' || Array.isArray(filter)) {
        throw new Error('A job view and filter scope is required')
    }
    const value = filter as Record<string, unknown>
    for (const key of Object.keys(value)) {
        if (!JOB_FILTER_KEYS.has(key)) throw new Error(`Unsupported job filter: ${key}`)
        if (!allowPaging && (key === 'page' || key === 'size')) {
            throw new Error('Page and size are not valid mutation scope filters')
        }
    }
    if (value.stage !== undefined && value.stage !== 'all' && value.stage !== 'for_you'
        && !(JOB_STAGES as readonly unknown[]).includes(value.stage)) {
        throw new Error('Unsupported job stage')
    }
    if (value.postedSince !== undefined && (typeof value.postedSince !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value.postedSince))) {
        throw new Error('postedSince must be a YYYY-MM-DD date')
    }
    if (value.sort !== undefined && (typeof value.sort !== 'string' || !JOB_SORTS.includes(value.sort as JobSort))) {
        throw new Error('Unsupported job sort')
    }
    if (value.searchScope !== undefined && (typeof value.searchScope !== 'string' || !JOB_SEARCH_SCOPES.includes(value.searchScope as JobSearchScope))) {
        throw new Error('Search scope must be metadata or all_text')
    }
    if (value.search !== undefined && typeof value.search !== 'string') throw new Error('Search must be text')
    checkedSearch(value.search as string | undefined)
    if (value.screenOutcome !== undefined && !(SCREEN_OUTCOMES as readonly unknown[]).includes(value.screenOutcome)) {
        throw new Error('Unsupported standalone screen outcome')
    }
    if (value.page !== undefined && (typeof value.page !== 'number' || !Number.isFinite(value.page))) {
        throw new Error('Page must be a finite number')
    }
    if (value.size !== undefined && (typeof value.size !== 'number' || !Number.isFinite(value.size))) {
        throw new Error('Page size must be a finite number')
    }
}

// Mirrors the approved Batch 1 summary predicate. Guard every JSON access with a safe
// JSON value so malformed stored output classifies as unknown rather than breaking the
// inventory query. Keep this expression in lockstep with worker/mcp/read_repository.py.
const SAFE_SCREEN_JSON_SQL = "CASE WHEN json_valid(s.result_json) THEN s.result_json ELSE '{}' END"
const SCREEN_OUTCOME_SQL = `CASE
    WHEN s.id IS NULL THEN 'not_screened'
    WHEN s.state='provider_error' THEN 'provider_error'
    WHEN s.state!='complete' OR json_valid(s.result_json)=0 THEN 'unknown'
    WHEN json_type(${SAFE_SCREEN_JSON_SQL}, '$')!='object' THEN 'unknown'
    WHEN json_type(${SAFE_SCREEN_JSON_SQL}, '$.disqualified')='true'
         AND json_type(${SAFE_SCREEN_JSON_SQL}, '$.screen')='object'
         AND EXISTS (SELECT 1 FROM json_each(${SAFE_SCREEN_JSON_SQL}, '$.screen') AS screen_check
             WHERE screen_check.type='object'
               AND CASE WHEN screen_check.type='object'
                   THEN json_type(screen_check.value, '$.pass')='false' ELSE 0 END)
        THEN 'disqualified'
    WHEN json_type(${SAFE_SCREEN_JSON_SQL}, '$.disqualified')='false'
         AND json_type(${SAFE_SCREEN_JSON_SQL}, '$.screen')='object'
         AND EXISTS (SELECT 1 FROM json_each(${SAFE_SCREEN_JSON_SQL}, '$.screen') AS screen_check
             WHERE screen_check.type='object'
               AND CASE WHEN screen_check.type='object'
                   THEN json_type(screen_check.value, '$.pass')='true' ELSE 0 END)
         AND NOT EXISTS (SELECT 1 FROM json_each(${SAFE_SCREEN_JSON_SQL}, '$.screen') AS screen_check
             WHERE screen_check.type='object'
               AND CASE WHEN screen_check.type='object'
                   THEN json_type(screen_check.value, '$.pass')='false' ELSE 0 END)
        THEN 'no_disqualifier_found'
    ELSE 'unknown'
END`

function escapeLikeLiteral(value: string): string {
    return `%${value.replace(/[!%_]/g, (char) => `!${char}`)}%`
}

function checkedSearch(value: string | undefined): string {
    const search = value ?? ''
    if (search.length > MAX_JOB_SEARCH_CHARS) {
        throw new Error(`Search must be ${MAX_JOB_SEARCH_CHARS} characters or fewer`)
    }
    return search
}

function checkedScreenOutcome(value: ScreenOutcome | undefined): ScreenOutcome | undefined {
    if (value !== undefined && !(SCREEN_OUTCOMES as readonly string[]).includes(value)) {
        throw new Error('Unsupported standalone screen outcome')
    }
    return value
}

// --- Effective status (#226): one CASE, the same as worker/mcp/read_repository.py's
// _STATUS_SQL, both pinned by worker/tests/fixtures/effective-status-cases.json. The
// operator's override wins if one exists (not bound to the content revision: nothing
// else re-evaluates on a content change either), else the stored verdict.
const STATUS_SQL = `CASE WHEN o.decision IN ('keep','skip') THEN o.decision ELSE p.verdict END`
// The profile version the verdict was judged under: triage's when it completed, else
// the requirements stage's.
const PROFILE_VERSION_SQL = `CASE WHEN j.state='complete' THEN j.profile_version ELSE s.profile_version END`
// The funnel stage (lib/job-stages.ts): closed first, then `other` once a posting left
// `new`, else its effective status.
const STAGE_SQL = `CASE WHEN p.source_state='closed' THEN 'closed' WHEN p.pipeline_status<>'new' THEN 'other'
    ELSE ${STATUS_SQL} END`
// "Postings for you" (#207): the keep stage. Without triage the worker stores keep once
// the hard requirements pass, so one rule serves both modes.
const FOR_YOU_SQL = `(${STAGE_SQL})='keep'`

// Which line the list shows above "for you": triage is configured in the profile (a
// target role or a custom context).
export async function getJobsMode(): Promise<'jev' | 'screen'> {
    const profile = await prisma.candidate_profile.findUnique({
        where: { id: 1 }, select: { target_roles: true, custom_triage_context: true },
    })
    let roles: unknown = []
    try {
        roles = JSON.parse(profile?.target_roles ?? '[]')
    } catch {
        roles = []
    }
    return profile && ((Array.isArray(roles) && roles.length > 0) || profile.custom_triage_context != null)
        ? 'jev' : 'screen'
}

function jevReasons(raw: unknown): string[] {
    try {
        const parsed = typeof raw === 'string' ? JSON.parse(raw) : null
        return Array.isArray(parsed) ? parsed.filter((r): r is string => typeof r === 'string').slice(0, 8) : []
    } catch {
        return []
    }
}

const FROM_SQL = `FROM job_postings p
    LEFT JOIN job_screenings s ON s.job_posting_id=p.id
    LEFT JOIN job_jev_assessments j ON j.job_posting_id=p.id
    LEFT JOIN job_triage_overrides o ON o.job_posting_id=p.id`

function jobsWhereSql(filter: JobPostingsFilter): Prisma.Sql {
    validateJobPostingsFilter(filter)
    const search = checkedSearch(filter.search)
    const searchScope = filter.searchScope ?? 'metadata'
    const screenOutcome = checkedScreenOutcome(filter.screenOutcome)
    const stage = filter.stage ?? 'for_you'
    const clauses: Prisma.Sql[] = [Prisma.sql`p.pipeline_status <> 'removed'`]
    if (stage === 'for_you') clauses.push(Prisma.raw(FOR_YOU_SQL))
    else if (stage !== 'all') clauses.push(Prisma.sql`(${Prisma.raw(STAGE_SQL)}) = ${stage}`)
    if (filter.postedSince) clauses.push(Prisma.sql`p.posted_at >= ${filter.postedSince}`)
    if (search) {
        const pattern = escapeLikeLiteral(search)
        const bodyClause = searchScope === 'all_text'
            ? Prisma.sql` OR p.description LIKE ${pattern} ESCAPE '!'`
            : Prisma.empty
        clauses.push(Prisma.sql`(
            p.job_title LIKE ${pattern} ESCAPE '!'
            OR p.company_name LIKE ${pattern} ESCAPE '!'
            OR COALESCE(p.location, '') LIKE ${pattern} ESCAPE '!'
            ${bodyClause}
        )`)
    }
    if (screenOutcome) {
        clauses.push(Prisma.sql`(${Prisma.raw(SCREEN_OUTCOME_SQL)}) = ${screenOutcome}`)
    }
    return Prisma.join(clauses, ' AND ')
}

type RawInventoryPosting = Prisma.job_postingsGetPayload<{}> & {
    screening_id: number | null
    screening_state: string | null
    screening_result_json: string | null
    screening_error_message: string | null
    screening_backend: string | null
    screening_model: string | null
    screening_effort: string | null
    screening_evaluator_version: string | null
    screening_updated_at: string | null
    screening_source_content_revision: number | null
    stage: JobStage
    status: string
    profile_version: number | bigint | null
    jev_state: string | null
    jev_reasons_json: string | null
    override_decision: string | null
    override_reason: string | null
    override_actor: string | null
    override_set_at: string | null
}

// Newest posted first by default (no fit order, #207).
export async function getJobPostings(params: JobPostingsFilter = {}) {
    validateJobPostingsFilter(params)
    const page = Math.max(0, Math.floor(params.page ?? 0))
    const size = Math.min(100, Math.max(1, Math.floor(params.size ?? 25)))
    const where = jobsWhereSql(params)
    const orderSql = Prisma.raw('p.posted_at DESC, p.id DESC')
    const [rows, countRows] = await Promise.all([
        prisma.$queryRaw<RawInventoryPosting[]>(Prisma.sql`
            SELECT p.*,
                   s.id AS screening_id,
                   s.state AS screening_state,
                   s.result_json AS screening_result_json,
                   s.error_message AS screening_error_message,
                   s.backend AS screening_backend,
                   s.model AS screening_model,
                   s.effort AS screening_effort,
                   s.evaluator_version AS screening_evaluator_version,
                   s.updated_at AS screening_updated_at,
                   s.source_content_revision AS screening_source_content_revision,
                   (${Prisma.raw(STAGE_SQL)}) AS stage,
                   (${Prisma.raw(STATUS_SQL)}) AS status,
                   (${Prisma.raw(PROFILE_VERSION_SQL)}) AS profile_version,
                   j.state AS jev_state, j.reasons_json AS jev_reasons_json,
                   o.decision AS override_decision, o.reason AS override_reason,
                   o.actor AS override_actor, o.created_at AS override_set_at
            ${Prisma.raw(FROM_SQL)}
            WHERE ${where}
            ORDER BY ${orderSql}
            LIMIT ${size} OFFSET ${page * size}
        `),
        prisma.$queryRaw<Array<{ total: number | bigint }>>(Prisma.sql`
            SELECT COUNT(*) AS total ${Prisma.raw(FROM_SQL)} WHERE ${where}
        `),
    ])
    // A posting that matches an unlinked application (#241): shown, never linked.
    const open = rows.some((r) => r.application_id == null) ? await unlinkedApplications(prisma) : []
    const data = rows.map((row) => {
        const {
            screening_id, screening_state, screening_result_json, screening_error_message,
            screening_backend, screening_model, screening_effort, screening_evaluator_version,
            screening_updated_at, screening_source_content_revision,
            profile_version, jev_state, jev_reasons_json,
            override_decision, override_reason, override_actor, override_set_at,
            score_detail, ...posting
        } = row
        const screening = screening_id == null ? null : {
            id: screening_id,
            state: screening_state ?? 'unknown',
            result_json: screening_result_json,
            error_message: screening_error_message,
            backend: screening_backend ?? '',
            model: screening_model,
            effort: screening_effort,
            evaluator_version: screening_evaluator_version ?? '',
            updated_at: screening_updated_at,
            source_content_revision: screening_source_content_revision,
        }
        return {
            ...posting,
            score_detail,
            screen_summary: standaloneScreenSummary(screening),
            legacy_screen_evidence: legacyScreenEvidence(score_detail),
            triage_summary: jobTriageSummary(posting.pipeline_status, screening),
            source_lifecycle: sourceLifecycleSummary({ ...posting, score_detail }, screening),
            profile_version: profile_version == null ? null : Number(profile_version),
            applied_match: row.application_id == null ? bestApplication(row, open) : null,
            jev: {
                reasons: jev_state === 'complete' ? jevReasons(jev_reasons_json) : [],
                override: override_decision == null ? null : {
                    decision: override_decision, reason: override_reason, actor: override_actor,
                    set_at: override_set_at,
                },
            },
        }
    })
    return { data, total: Number(countRows[0]?.total ?? 0) }
}

// The Jobs nav badge: "postings for you" first fetched in the last 24h.
export async function getNewJobsCount() {
    const since = new Date(Date.now() - 86_400_000).toISOString()
    const rows = await prisma.$queryRaw<Array<{ n: number | bigint }>>(Prisma.sql`
        SELECT COUNT(*) AS n ${Prisma.raw(FROM_SQL)}
        WHERE ${Prisma.raw(FOR_YOU_SQL)} AND p.created_at >= ${since}
    `)
    return Number(rows[0]?.n ?? 0)
}

type JobScopeClient = Pick<Prisma.TransactionClient, 'job_postings' | '$queryRaw'>

// A mutation sends back the view that offered it, so a stale or crafted request cannot
// act on a row outside that view.
async function findPostingInView(client: JobScopeClient, id: number, scope: JobViewScope) {
    validateJobPostingsFilter(scope, false)
    const where = jobsWhereSql(scope)
    const matches = await client.$queryRaw<Array<{ id: number | bigint }>>(Prisma.sql`
        SELECT p.id ${Prisma.raw(FROM_SQL)} WHERE p.id=${id} AND ${where} LIMIT 1
    `)
    if (matches.length === 0) return null
    return client.job_postings.findUnique({ where: { id } })
}

// When an unlinked application already matches the posting (tier 1 or 2, #241), nothing is
// written: the answer carries that application as `match`, to link it or to mark again
// with `createNew`.
export async function markJobApplied(id: number, category: string | undefined, scope: JobViewScope, actor: Actor = 'web',
    opts: { date?: string; createNew?: boolean } = {}) {
    try {
        checkedActor(actor)
        const date = opts.date === undefined ? todayISO() : checkedDate(opts.date)
        validateJobPostingsFilter(scope, false)
        return await prisma.$transaction(async (tx) => {
            const posting = await findPostingInView(tx, id, scope)
            if (!posting) {
                const exists = await tx.job_postings.findUnique({ where: { id }, select: { id: true } })
                return { success: false, error: exists
                    ? 'Job is outside the requested view and filters'
                    : 'Job posting not found' }
            }
            if (posting.pipeline_status === 'applied' || posting.pipeline_status === 'removed') {
                return { success: false, error: 'Job is not eligible to mark applied' }
            }

            // Category is a free-form user label chosen at apply time; keep whatever's
            // given, falling back to 'Others' only when blank.
            const cat = category?.trim() || CATEGORY_FALLBACK

            // The whole duplicate check (#244): an unlinked application with the same company
            // and title is always a match here, and a linked one is another posting's.
            const match = opts.createNew ? null : bestApplication(posting, await unlinkedApplications(tx))
            if (match) {
                return { success: false, match, error: `Not marked: application #${match.id} (${match.date_applied}, not linked to a posting) `
                    + `looks like this job. Link it to job ${id}, or mark again as a new application.` }
            }

            const newApp = await tx.applications.create({
                data: {
                    company_name: posting.company_name,
                    job_title: posting.job_title,
                    application_url: posting.job_url || '',
                    date_applied: date,
                    category: cat,
                    status: 'Applied',
                    notes: '',
                    last_updated: new Date().toISOString(),
                    actor,
                },
            })
            await writeInitialHistory(tx, newApp)
            await tx.audit_log.create({ data: applicationAudit(actor, 'add', newApp.id, newApp) })

            const updated = await tx.job_postings.updateMany({
                where: { id, pipeline_status: { notIn: ['applied', 'removed'] } },
                data: {
                    pipeline_status: 'applied',
                    application_id: newApp.id,
                    updated_at: new Date().toISOString(),
                },
            })
            if (updated.count !== 1) throw new Error('Job is no longer eligible in the requested view and filters')

            return { success: true, data: newApp }
        })
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

// --- Triage override (#155): the operator's keep/skip over the stored verdict ------
// One row per posting, any verdict (keep rescues a requirements discard); it holds until
// cleared. The content revision is recorded as provenance only. Every set/replace/clear
// is audited, and a replace or clear keeps the row it overwrote.

const MAX_OVERRIDE_REASON = 500

export async function setTriageOverride(jobId: number, decision: string, reason: string | undefined, actor: Actor = 'web') {
    checkedActor(actor)
    if (decision !== 'keep' && decision !== 'skip') return { success: false, error: 'decision must be keep or skip' }
    const why = reason?.trim() || null
    if (why && why.length > MAX_OVERRIDE_REASON) return { success: false, error: `reason is over ${MAX_OVERRIDE_REASON} characters` }
    try {
        const data = await prisma.$transaction(async (tx) => {
            const job = await tx.job_postings.findUnique({
                where: { id: jobId }, select: { source_content_revision: true },
            })
            if (!job) return null
            const before = await tx.job_triage_overrides.findUnique({ where: { job_posting_id: jobId } })
            const fields = {
                decision, reason: why, actor, source_content_revision: job.source_content_revision,
                created_at: new Date().toISOString(),
            }
            const row = await tx.job_triage_overrides.upsert({
                where: { job_posting_id: jobId }, create: { job_posting_id: jobId, ...fields }, update: fields,
            })
            await tx.audit_log.create({ data: {
                at: fields.created_at, actor, action: before ? 'update' : 'add',
                entity: 'job_triage_overrides', entity_id: jobId,
                payload: JSON.stringify(before ? { before, after: row } : row),
            } })
            return row
        })
        if (!data) return { success: false, error: `Job ${jobId} not found` }
        return { success: true, data }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function clearTriageOverride(jobId: number, actor: Actor = 'web') {
    checkedActor(actor)
    try {
        const removed = await prisma.$transaction(async (tx) => {
            const row = await tx.job_triage_overrides.findUnique({ where: { job_posting_id: jobId } })
            if (!row) return null
            await tx.job_triage_overrides.delete({ where: { id: row.id } })
            await tx.audit_log.create({ data: {
                at: new Date().toISOString(), actor, action: 'remove',
                entity: 'job_triage_overrides', entity_id: jobId, payload: JSON.stringify(row),
            } })
            return row
        })
        if (!removed) return { success: false, error: `Job ${jobId} has no triage override` }
        return { success: true, data: removed }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}
