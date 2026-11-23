'use server'

import { prisma } from '@/lib/db'
import { Prisma } from '@prisma/client'
import { type Actor } from '@/lib/constants'
import { todayISO } from '@/lib/utils'
import { legacyScreenEvidence, SCREEN_OUTCOMES, standaloneScreenSummary, type ScreenOutcome } from '@/lib/screen-summary'
import { sourceLifecycleSummary } from '@/lib/source-lifecycle'
import { jobTriageSummary } from '@/lib/triage-summary'
import { applicationAudit, checkedActor, writeInitialHistory, CATEGORY_FALLBACK } from '@/lib/action-helpers'
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

const KNOWN_PIPELINE_STATUSES_SQL = ['new', 'scored', 'notified', 'applied', 'discarded', 'failed', 'removed', 'expired']
    .map((status) => `'${status}'`).join(',')
const CANDIDATE_PIPELINE_STATUSES_SQL = ['new', 'scored', 'notified']
    .map((status) => `'${status}'`).join(',')
const SUPPORTED_SCREEN_CHECKS_SQL = ['location', 'internships', 'employment_type', 'degree', 'authorization', 'clearance']
    .map((check) => `'${check}'`).join(',')
const DETERMINISTIC_SCREEN_CHECKS_SQL = ['location', 'internships', 'employment_type']
    .map((check) => `'${check}'`).join(',')
const MAX_SAFE_JSON_REVISION_SQL = '9007199254740991'

function triageCheckShapeSql(result: string, supportedChecks: string): string {
    return `json_type(${result}, '$.screen')='object'
        AND NOT EXISTS (
            SELECT screen_member.key FROM json_each(${result}, '$.screen') AS screen_member
            GROUP BY screen_member.key HAVING COUNT(*)>1
        )
        AND NOT EXISTS (
            SELECT 1 FROM json_each(${result}, '$.screen') AS triage_check
            WHERE triage_check.type!='object'
               OR triage_check.key NOT IN (${supportedChecks})
               OR CASE WHEN triage_check.type='object'
                       THEN COALESCE(json_type(triage_check.value, '$.pass'),'missing')
                            NOT IN ('true','false') ELSE 0 END
               OR CASE WHEN triage_check.type='object'
                       THEN (json_type(triage_check.value, '$.note') IS NOT NULL
                             AND json_type(triage_check.value, '$.note')!='text')
                       ELSE 0 END
               OR CASE WHEN triage_check.type='object' THEN EXISTS (
                    SELECT 1 FROM json_each(triage_check.value) AS triage_field
                    WHERE triage_field.key NOT IN ('pass','note')
               ) ELSE 0 END
               OR CASE WHEN triage_check.type='object' THEN EXISTS (
                    SELECT triage_field.key FROM json_each(triage_check.value) AS triage_field
                    GROUP BY triage_field.key HAVING COUNT(*)>1
               ) ELSE 0 END
        )`
}

function triageValidResultSql(result: string, disqualified: boolean): string {
    const flag = disqualified ? "'true'" : "'false'"
    const passCheck = disqualified ? "json_type(triage_check.value, '$.pass')='false'"
        : "json_type(triage_check.value, '$.pass')='true'"
    const allChecks = triageCheckShapeSql(result, SUPPORTED_SCREEN_CHECKS_SQL)
    const noFailure = disqualified ? '1=1' : `NOT EXISTS (
        SELECT 1 FROM json_each(${result}, '$.screen') AS triage_check
        WHERE CASE WHEN triage_check.type='object'
                   THEN json_type(triage_check.value, '$.pass')='false' ELSE 0 END
    )`
    return `s.state='complete' AND json_valid(s.result_json)=1
        AND json_type(${result}, '$')='object'
        AND json_type(${result}, '$.disqualified')=${flag}
        AND (json_type(${result}, '$.disqualification_reason') IS NULL
             OR json_type(${result}, '$.disqualification_reason')='text')
        AND NOT EXISTS (
            SELECT triage_root_field.key FROM json_each(${result}) AS triage_root_field
            GROUP BY triage_root_field.key HAVING COUNT(*)>1
        )
        AND NOT EXISTS (SELECT 1 FROM json_each(${result}) AS triage_root_field
                        WHERE triage_root_field.key NOT IN
                            ('screen','disqualified','disqualification_reason'))
        AND ${allChecks}
        AND EXISTS (SELECT 1 FROM json_each(${result}, '$.screen') AS triage_check
                    WHERE CASE WHEN triage_check.type='object' THEN ${passCheck} ELSE 0 END)
        AND ${noFailure}`
}

function triageRuleOnlySql(result: string): string {
    return `${triageCheckShapeSql(result, DETERMINISTIC_SCREEN_CHECKS_SQL)}
        AND json_type(${result}, '$.disqualified')='true'
        AND EXISTS (SELECT 1 FROM json_each(${result}, '$.screen') AS triage_check
                    WHERE CASE WHEN triage_check.type='object'
                               THEN json_type(triage_check.value, '$.pass')='false' ELSE 0 END)`
}

// This SQL expression is the query-time counterpart of jobTriageSummary. Keep all
// JSON validation here so unsupported rows remain visible as needs_review and the
// filter/count run before LIMIT/OFFSET.
const TRIAGE_STATUS_SQL = (() => {
    const result = "CASE WHEN json_valid(s.result_json) THEN s.result_json ELSE '{}' END"
    const legacy = "CASE WHEN json_valid(p.score_detail) THEN p.score_detail ELSE '{}' END"
    const standaloneDisqualified = triageValidResultSql(result, true)
    const standaloneCandidate = triageValidResultSql(result, false)
    const ruleOnly = triageRuleOnlySql(result)
    const legacyRuleOnly = triageRuleOnlySql(legacy)
    const legacyRootShape = `json_type(${legacy}, '$')='object'
        AND json_type(${legacy}, '$.disqualified')='true'
        AND (json_type(${legacy}, '$.disqualification_reason') IS NULL
             OR json_type(${legacy}, '$.disqualification_reason')='text')
        AND (json_type(${legacy}, '$.source_content_revision') IS NULL
             OR json_type(${legacy}, '$.source_content_revision')='null'
             OR (json_type(${legacy}, '$.source_content_revision') IN ('integer','real')
                 AND json_extract(${legacy}, '$.source_content_revision')>0
                 AND json_extract(${legacy}, '$.source_content_revision')<=${MAX_SAFE_JSON_REVISION_SQL}
                 AND json_extract(${legacy}, '$.source_content_revision')=
                     CAST(json_extract(${legacy}, '$.source_content_revision') AS INTEGER)))
        AND NOT EXISTS (
            SELECT legacy_field.key FROM json_each(${legacy}) AS legacy_field
            GROUP BY legacy_field.key HAVING COUNT(*)>1
        )
        AND NOT EXISTS (SELECT 1 FROM json_each(${legacy}) AS legacy_field
                        WHERE legacy_field.key NOT IN
                            ('screen','disqualified','disqualification_reason','source_content_revision'))`
    return `CASE
        WHEN p.pipeline_status IS NULL OR p.pipeline_status NOT IN (${KNOWN_PIPELINE_STATUSES_SQL})
            THEN 'needs_review'
        WHEN s.id IS NOT NULL AND (${standaloneDisqualified}) AND (${ruleOnly})
            THEN 'rule_disqualified'
        WHEN s.id IS NOT NULL AND (${standaloneDisqualified})
            THEN 'screen_disqualified'
        WHEN s.id IS NOT NULL AND (${standaloneCandidate})
             AND p.pipeline_status IN (${CANDIDATE_PIPELINE_STATUSES_SQL}) THEN 'candidate'
        WHEN s.id IS NULL AND p.pipeline_status='discarded'
             AND json_valid(p.score_detail)=1 AND (${legacyRootShape})
             AND (${legacyRuleOnly}) THEN 'rule_disqualified'
        ELSE 'needs_review'
    END`
})()

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

// --- JEV status: a port of worker/mcp/read_repository.py, kept identical ------------
// The override applies while it was set on the posting's current content (NULL counts
// as revision 1, as in the worker); otherwise the model status stands. Stale = the
// source changed, or the verdict predates the latest pass's recorded policy.
const OVERRIDE_APPLIES_SQL = `(o.id IS NOT NULL AND o.decision IN ('keep','skip')
    AND COALESCE(o.source_content_revision,1)=COALESCE(p.source_content_revision,1))`
const JEV_MODEL_STATUS_SQL = `CASE WHEN j.id IS NULL THEN 'unassessed' WHEN j.state<>'complete' THEN 'failed'
    WHEN j.source_content_revision IS NOT p.source_content_revision THEN 'stale'
    WHEN j.policy_sha256 IS NOT COALESCE((SELECT value FROM app_settings
        WHERE key='jev_current_policy_sha256'), j.policy_sha256) THEN 'stale'
    WHEN j.verdict IN ('keep','skip') THEN j.verdict ELSE 'failed' END`
const JEV_STATUS_SQL = `CASE WHEN ${OVERRIDE_APPLIES_SQL} THEN o.decision ELSE ${JEV_MODEL_STATUS_SQL} END`
const JEV_JOIN_SQL = `LEFT JOIN job_jev_assessments j ON j.job_posting_id=p.id
    LEFT JOIN job_triage_overrides o ON o.job_posting_id=p.id`

// Simple CASE (operand evaluated once): the triage and JEV expressions are the costly
// parts, and the searched form would evaluate each twice per row.
const STAGE_AFTER_TRIAGE_SQL = `CASE WHEN p.pipeline_status<>'new' THEN 'other'
    ELSE CASE (${JEV_STATUS_SQL}) WHEN 'keep' THEN 'keep' WHEN 'skip' THEN 'jev_skip' ELSE 'unassessed' END END`
const STAGE_SQL = `CASE WHEN p.source_state='closed' THEN 'closed' ELSE CASE (${TRIAGE_STATUS_SQL})
    WHEN 'rule_disqualified' THEN 'rule_rejected'
    WHEN 'screen_disqualified' THEN 'screen_rejected'
    WHEN 'needs_review' THEN CASE WHEN p.pipeline_status='discarded' THEN 'screen_rejected'
        ELSE ${STAGE_AFTER_TRIAGE_SQL} END
    ELSE ${STAGE_AFTER_TRIAGE_SQL} END END`

// "Postings for you" (#207): not applied, not closed at the source, not marked not
// interested; then triage keep when triage is configured (a target role or a custom
// context, the rule of profileView's triage_configured, so new postings will be assessed)
// and has run at least once, else passed the hard requirements, so an install without
// triage does not see an empty page. The mode subqueries are uncorrelated, so SQLite runs
// them once.
const JEV_MODE_SQL = `(EXISTS (SELECT 1 FROM candidate_profile WHERE id=1
        AND (json_array_length(target_roles) > 0 OR custom_triage_context IS NOT NULL))
    AND EXISTS (SELECT 1 FROM job_jev_assessments))`
const FOR_YOU_SQL = `(p.pipeline_status='new' AND p.source_state<>'closed'
    AND NOT (${OVERRIDE_APPLIES_SQL} AND o.decision='skip')
    AND CASE WHEN ${JEV_MODE_SQL} THEN (${STAGE_SQL})='keep'
        ELSE (${TRIAGE_STATUS_SQL})='candidate' END)`

// Which "for you" mode is active, for the one line above the list.
export async function getJobsMode(): Promise<'jev' | 'screen'> {
    const rows = await prisma.$queryRaw<Array<{ jev: number | bigint }>>(Prisma.sql`SELECT ${Prisma.raw(JEV_MODE_SQL)} AS jev`)
    return Number(rows[0]?.jev ?? 0) ? 'jev' : 'screen'
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
    ${JEV_JOIN_SQL}`

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
    jev_status: string
    jev_model_status: string
    jev_reasons_json: string | null
    override_applies: number | bigint | null
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
                   (${Prisma.raw(JEV_STATUS_SQL)}) AS jev_status,
                   (${Prisma.raw(JEV_MODEL_STATUS_SQL)}) AS jev_model_status,
                   j.reasons_json AS jev_reasons_json,
                   ${Prisma.raw(OVERRIDE_APPLIES_SQL)} AS override_applies,
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
    const data = rows.map((row) => {
        const {
            screening_id, screening_state, screening_result_json, screening_error_message,
            screening_backend, screening_model, screening_effort, screening_evaluator_version,
            screening_updated_at, screening_source_content_revision,
            jev_status, jev_model_status, jev_reasons_json,
            override_applies, override_decision, override_reason, override_actor, override_set_at,
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
            triage_summary: jobTriageSummary(posting.pipeline_status, score_detail, screening),
            source_lifecycle: sourceLifecycleSummary({ ...posting, score_detail }, screening),
            jev: {
                status: jev_status,
                model_status: jev_model_status,
                reasons: jev_model_status === 'keep' || jev_model_status === 'skip' ? jevReasons(jev_reasons_json) : [],
                override: override_decision == null ? null : {
                    decision: override_decision, reason: override_reason, actor: override_actor,
                    set_at: override_set_at, applies: Boolean(Number(override_applies ?? 0)),
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

export async function markJobApplied(id: number, category: string | undefined, scope: JobViewScope, actor: Actor = 'web') {
    try {
        checkedActor(actor)
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
            const today = todayISO()

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

// --- Triage override (#155): the operator's keep/skip over JEV's verdict --------
// One row per posting; it applies while the posting's source_content_revision is the
// one recorded here (the MCP read side decides that). Every set/replace/clear is
// audited, and a replace or clear keeps the row it overwrote.

const MAX_OVERRIDE_REASON = 500

export async function setTriageOverride(jobId: number, decision: string, reason: string | undefined, actor: Actor = 'web') {
    checkedActor(actor)
    if (decision !== 'keep' && decision !== 'skip') return { success: false, error: 'decision must be keep or skip' }
    const why = reason?.trim() || null
    if (why && why.length > MAX_OVERRIDE_REASON) return { success: false, error: `reason is over ${MAX_OVERRIDE_REASON} characters` }
    try {
        // The revision is read in the write transaction so a concurrent refresh cannot
        // leave the override pinned to content it was never set on.
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
