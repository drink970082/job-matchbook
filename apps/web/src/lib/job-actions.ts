'use server'

import { prisma } from '@/lib/db'
import { Prisma } from '@prisma/client'
import { type Actor, LOW_CONTEXT_MAX_DESCRIPTION_LENGTH } from '@/lib/constants'
import { todayISO } from '@/lib/utils'
import { legacyScreenEvidence, SCREEN_OUTCOMES, standaloneScreenSummary, type ScreenOutcome } from '@/lib/screen-summary'
import { sourceLifecycleSummary } from '@/lib/source-lifecycle'
import { jobTriageSummary, TRIAGE_STATUSES, type TriageStatus } from '@/lib/triage-summary'
import { checkedActor, searchClause, CATEGORY_FALLBACK } from '@/lib/action-helpers'

// Pipeline statuses still "live" in the discovered queue (scored, not yet applied
// or discarded). Score then sorts them into the Matched vs Discarded buckets.
const ACTIVE_PIPELINE_STATUSES = ['scored', 'notified'] as const

// Discovered Jobs collapses to score-aware buckets (we're testing scoring). Every
// non-lowcontext bucket is mutually exclusive of the derived low-context id set.
// The KEEP half of the fit verdicts requires seniority=match — a seniority miss is
// disqualifying, not partial — and then splits on domain. These verdicts are the
// retired fit scorer's stored output; nothing writes new ones.
//   matched    — live (scored|notified) + seniority=match AND domain=match AND NOT
//                insufficient_context (the actionable set; see matchedIds)
//   belowbar   — live + seniority=match AND domain=adjacent: the NEAR MISS, worth a
//                human glance (see belowBarIds)
//   discarded  — the audit view, two populations: hard-constraint screen failures
//                (pipeline_status='discarded' + disqualified:true) AND live rows the
//                fit verdicts rejected (too_junior/too_senior, or domain=mismatch).
//                Everything scored that is neither matched nor below bar lands here,
//                so nothing is ever orphaned.
//   lowcontext — live but the JD was too thin to score with confidence (derived)
//   failed     — pipeline failure, for monitoring
export type JobBucket = 'all' | 'matched' | 'belowbar' | 'discarded' | 'failed' | 'lowcontext'

// Within the Discarded (disqualified) audit view you can narrow to one hard-constraint
// cause. The worker writes `disqualification_reason` keyed like "degree: requires phd"
// / "authorization: no visa sponsorship offered" / "clearance: …" / "location: …" /
// "internship/co-op role" (multiple joined by "; "); each cause maps to a LIKE pattern.
export type DisqualifyCause = 'authorization' | 'location' | 'degree' | 'clearance' | 'internship' | 'prefilter'

// LIKE patterns that recognize each disqualification cause inside the (possibly
// "; "-joined) disqualification_reason string. See disqualifyCauseIds.
const DISQUALIFY_CAUSE_PATTERNS: Record<DisqualifyCause, string> = {
    authorization: '%authorization:%',
    location: '%location:%',
    degree: '%degree:%',
    clearance: '%clearance:%',
    internship: '%internship/co-op%',
    // Not a hard-constraint cause: the operator's own title/age filters, re-applied to
    // already-queued rows by the retired fit pass's free sweep. Without a cause these rows
    // are visible in the Discarded bucket (that filter keys on `disqualified`, not on
    // cause) but not selectable, so an operator cannot bulk-remove them — 1,504 rows as
    // of 2026-07-31.
    //
    // The worker writes two spellings and they do NOT both reach this filter, which is
    // worth stating because the prefix suggests otherwise. Measured 2026-07-31:
    //   "prefilter: title refused by the current filters"        1,504 rows, all discarded
    //   "prefilter: refused by the current title/age filters"        56 rows, all `new`
    // `disqualifyCauseIds` scopes to pipeline_status='discarded', so the second spelling
    // contributes zero here. The wildcard covers it only if those rows are ever
    // discarded; it is deliberately not narrowed to the first spelling so that stays true.
    prefilter: '%prefilter:%',
}

const JOB_BUCKETS: readonly JobBucket[] = ['all', 'matched', 'belowbar', 'discarded', 'failed', 'lowcontext']
const JOB_SORTS: readonly JobSort[] = ['score', 'posted', 'created']
const JOB_SEARCH_SCOPES: readonly JobSearchScope[] = ['metadata', 'all_text']
const DISQUALIFY_CAUSES: readonly DisqualifyCause[] = [
    'authorization', 'location', 'degree', 'clearance', 'internship', 'prefilter',
]
const JOB_FILTER_KEYS = new Set(['bucket', 'search', 'searchScope', 'screenOutcome', 'triageStatus', 'page', 'size', 'minScore', 'cause', 'sort'])

function validateJobPostingsFilter(filter: unknown, requireBucket = false, allowPaging = true): asserts filter is JobPostingsFilter {
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
    if (requireBucket && (typeof value.bucket !== 'string' || !JOB_BUCKETS.includes(value.bucket as JobBucket))) {
        throw new Error('A supported job bucket is required for this action')
    }
    if (value.bucket !== undefined && (typeof value.bucket !== 'string' || !JOB_BUCKETS.includes(value.bucket as JobBucket))) {
        throw new Error('Unsupported job bucket')
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
    if (value.triageStatus !== undefined && !(TRIAGE_STATUSES as readonly unknown[]).includes(value.triageStatus)) {
        throw new Error('Unsupported job triage status')
    }
    if (value.cause !== undefined && (typeof value.cause !== 'string' || !DISQUALIFY_CAUSES.includes(value.cause as DisqualifyCause))) {
        throw new Error('Unsupported disqualification cause')
    }
    if (value.minScore !== undefined && (typeof value.minScore !== 'number' || !Number.isFinite(value.minScore) || value.minScore < 0 || value.minScore > 100)) {
        throw new Error('Minimum score must be between 0 and 100')
    }
    if (value.page !== undefined && (typeof value.page !== 'number' || !Number.isFinite(value.page))) {
        throw new Error('Page must be a finite number')
    }
    if (value.size !== undefined && (typeof value.size !== 'number' || !Number.isFinite(value.size))) {
        throw new Error('Page size must be a finite number')
    }
}

// Sort for the discovered queue: best match (score) or freshest posting.
export type JobSort = 'score' | 'posted' | 'created'
export type JobSearchScope = 'metadata' | 'all_text'

export interface JobPostingsFilter {
    bucket?: JobBucket
    search?: string
    searchScope?: JobSearchScope
    screenOutcome?: ScreenOutcome
    triageStatus?: TriageStatus
    page?: number
    size?: number
    minScore?: number
    cause?: DisqualifyCause
    sort?: JobSort
}

export type JobViewScope = Omit<JobPostingsFilter, 'page' | 'size'> & { bucket: JobBucket }

const MAX_JOB_SEARCH_CHARS = 200

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
const SUPPORTED_SCREEN_CHECKS_SQL = ['location', 'internships', 'degree', 'authorization', 'clearance']
    .map((check) => `'${check}'`).join(',')
const DETERMINISTIC_SCREEN_CHECKS_SQL = ['location', 'internships']
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

function allJobsWhereSql(filter: JobPostingsFilter): Prisma.Sql {
    validateJobPostingsFilter(filter)
    if (filter.cause) throw new Error('Disqualification cause is only supported in the Discarded view')
    const search = checkedSearch(filter.search)
    const searchScope = filter.searchScope ?? 'metadata'
    if (searchScope !== 'metadata' && searchScope !== 'all_text') {
        throw new Error('Search scope must be metadata or all_text')
    }
    const screenOutcome = checkedScreenOutcome(filter.screenOutcome)
    const triageStatus = filter.triageStatus
    const clauses: Prisma.Sql[] = [Prisma.sql`p.pipeline_status <> 'removed'`]
    if (filter.minScore != null) clauses.push(Prisma.sql`p.score >= ${filter.minScore}`)
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
    if (triageStatus) {
        clauses.push(Prisma.sql`(${Prisma.raw(TRIAGE_STATUS_SQL)}) = ${triageStatus}`)
    }
    return Prisma.join(clauses, ' AND ')
}

function buildJobWhere(params: {
    bucket?: JobBucket
    search?: string
    minScore?: number
}, matchIds: number[], belowIds: number[]): Prisma.job_postingsWhereInput {
    const bucket = params.bucket ?? 'matched'
    const search = params.search || ''
    const minScore = params.minScore

    let bucketFilter: Prisma.job_postingsWhereInput
    if (bucket === 'failed') {
        bucketFilter = { pipeline_status: 'failed' }
    } else if (bucket === 'discarded') {
        // Two populations, OR'd. (1) Hard-constraint screen failures: status
        // 'discarded' + disqualified:true — substring-matched on the score_detail JSON,
        // tolerating json.dumps spacing ("disqualified": true) and compact
        // ("disqualified":true). (2) Fit-verdict rejects: live rows in neither the
        // matched nor the below-bar set — a seniority miss (too_junior/too_senior) or
        // domain=mismatch. Guarded like the lowIds `notIn`: an empty keep set must NOT
        // emit `NOT IN ()` (which SQLite/Prisma would treat as excluding nothing rather
        // than excluding everything) — with nothing kept, every live row IS a reject.
        const keepIds = [...matchIds, ...belowIds]
        bucketFilter = {
            OR: [
                {
                    pipeline_status: 'discarded',
                    OR: [
                        { score_detail: { contains: '"disqualified": true' } },
                        { score_detail: { contains: '"disqualified":true' } },
                    ],
                },
                {
                    pipeline_status: { in: [...ACTIVE_PIPELINE_STATUSES] },
                    ...(keepIds.length > 0 ? { id: { notIn: keepIds } } : {}),
                },
            ],
        }
    } else if (bucket === 'belowbar') {
        // The near miss: seniority=match AND domain=adjacent. An empty belowIds
        // correctly yields `id IN ()` → no rows, so no guard is needed here.
        bucketFilter = {
            pipeline_status: { in: [...ACTIVE_PIPELINE_STATUSES] },
            id: { in: belowIds },
        }
    } else {
        // matched — seniority=match AND domain=match AND NOT insufficient_context. An empty
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
            searchClause(search),
        ],
    }
}

// The `where` for every bucket EXCEPT lowcontext: buildJobWhere's clauses, then the
// discarded-only cause sub-filter, then the low-context exclusion that keeps the tabs
// mutually exclusive (a thin-JD scored row shows only under Low-context). Appended as
// peer clauses so buildJobWhere's flat AND shape survives, and the exclusion is guarded
// because an empty set must NOT emit `NOT IN ()` — SQLite reads that as excluding
// nothing rather than everything.
//
// Shared by getJobPostings and removeAllInView, which had built it separately: a bulk
// remove must sweep exactly the rows the view is showing, and that only holds while
// the two agree by construction.
//
// NOTE it has no lowcontext case, because buildJobWhere has none — that bucket falls
// through to `matched`. Nothing calls this with `bucket: 'lowcontext'`;
// jobWhereForBucket below is the entry point and peels that bucket off first.
async function jobWhereExcludingLowContext(
    filter: { bucket?: JobBucket; search?: string; minScore?: number; cause?: DisqualifyCause },
    matchIds: number[],
    belowIds: number[],
    lowIds: number[],
): Promise<Prisma.job_postingsWhereInput> {
    const base = buildJobWhere(filter, matchIds, belowIds)
    const causeClause =
        filter.bucket === 'discarded' && filter.cause
            ? [{ id: { in: await disqualifyCauseIds(filter.cause) } }]
            : []
    return {
        AND: [
            ...(base.AND as Prisma.job_postingsWhereInput[]),
            ...causeClause,
            ...(lowIds.length > 0 ? [{ id: { notIn: lowIds } }] : []),
        ],
    }
}

// The `where` for ANY bucket — the single place a bucket becomes a query. getJobPostings
// and removeAllInView both go through here so a bulk remove sweeps exactly the rows the
// view is showing, for EVERY bucket rather than for all but one.
//
// The lowcontext bucket is peeled off first because buildJobWhere has no case for it and
// would fall through to `matched`: before this was shared, a removeAllInView on that
// bucket would have swept the MATCHED rows instead. Latent (the button renders only on
// the discarded bucket) but one branch away from real, so it is closed by construction
// instead of by that button never moving.
async function jobWhereForBucket(
    filter: { bucket?: JobBucket; search?: string; minScore?: number; cause?: DisqualifyCause },
    matchIds: number[],
    belowIds: number[],
    lowIds: number[],
): Promise<Prisma.job_postingsWhereInput> {
    if (filter.bucket === 'lowcontext') {
        // The low-context bucket IS the thin-JD id set, plus the shared search/minScore
        // filters. It does not exclude itself, and the discarded-only cause sub-filter
        // does not apply.
        return {
            AND: [
                { id: { in: lowIds } },
                filter.minScore != null ? { score: { gte: filter.minScore } } : {},
                searchClause(filter.search || ''),
            ],
        }
    }
    return jobWhereExcludingLowContext(filter, matchIds, belowIds, lowIds)
}

async function jobWhereForFilter(filter: JobPostingsFilter): Promise<Prisma.job_postingsWhereInput> {
    validateJobPostingsFilter(filter)
    const bucket = filter.bucket ?? 'all'
    if (bucket === 'all') {
        throw new Error('All jobs uses a bound SQL inventory query, not a fit-bucket where clause')
    }
    if (filter.screenOutcome) {
        throw new Error('Standalone screen outcome filters are only supported in All jobs')
    }
    if (filter.triageStatus) {
        throw new Error('Job triage filters are only supported in All jobs')
    }
    if (filter.searchScope === 'all_text') {
        throw new Error('All-text search is only supported in All jobs')
    }
    if (filter.cause && bucket !== 'discarded') {
        throw new Error('Disqualification cause is only supported in the Discarded view')
    }
    checkedSearch(filter.search)
    const [lowIds, matchIds, belowIds] = await Promise.all([
        lowContextIds(), matchedIds(), belowBarIds(),
    ])
    return jobWhereForBucket({ ...filter, bucket }, matchIds, belowIds, lowIds)
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

// Ids of "matched" postings: seniority=match AND domain=match AND NOT
// insufficient_context, over the retired fit scorer's stored verdicts. Score alone is a rubric-band-quantized number that flips run-to-run near
// the old threshold; the verdicts are stable (see PROGRESS.md). Prisma's typed
// `where` can't reach into the score_detail JSON, so — mirroring lowContextIds — we
// fetch the matching ids once with a raw query and layer them onto the matched/
// belowbar bucket queries — id `in` for BOTH. `notIn` belongs to the discarded
// bucket, which excludes the union of the two keep sets. Scope: only rows that
// actually received a fit score (scored|notified).
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

// Ids of "below bar" postings — the NEAR MISS: seniority=match AND domain=adjacent
// (and not flagged insufficient_context). Same raw-query shape as matchedIds, and the
// two sets together are the whole KEEP half of the fit verdicts: domain=match is
// actionable (Matched), domain=adjacent is worth a glance (Below bar). A seniority
// miss never reaches either — the fit rubric treated seniority as disqualifying
// rather than partial — so those rows fall through to the Discarded audit view.
async function belowBarIds(): Promise<number[]> {
    const rows = await prisma.$queryRaw<Array<{ id: number | bigint }>>`
        SELECT id FROM job_postings
        WHERE pipeline_status IN ('scored', 'notified')
          AND json_extract(score_detail, '$.assessment.seniority.verdict') = 'match'
          AND json_extract(score_detail, '$.assessment.domain.verdict') = 'adjacent'
          AND COALESCE(json_extract(score_detail, '$.insufficient_context'), 0) <> 1
    `
    return rows.map((r) => Number(r.id))
}

type ScreenedJobPosting = Prisma.job_postingsGetPayload<{}> & {
    job_screening: {
        id: number
        state: string
        result_json: string | null
        error_message: string | null
        backend: string
        model: string | null
        effort: string | null
        evaluator_version: string
        updated_at: string | null
        source_content_revision: number | null
    } | null
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
}

function enrichJobPosting(posting: ScreenedJobPosting) {
    const { job_screening, score_detail, ...job } = posting
    return {
        ...job,
        score_detail,
        screen_summary: standaloneScreenSummary(job_screening),
        legacy_screen_evidence: legacyScreenEvidence(score_detail),
        triage_summary: jobTriageSummary(job.pipeline_status, score_detail, job_screening),
        source_lifecycle: sourceLifecycleSummary({ ...job, score_detail }, job_screening),
    }
}

async function getAllJobPostings(params: JobPostingsFilter, page: number, size: number) {
    const where = allJobsWhereSql(params)
    const sort = params.sort ?? 'created'
    const orderSql = sort === 'score'
        ? Prisma.raw('p.score DESC, p.id ASC')
        : sort === 'posted'
            ? Prisma.raw('p.posted_at DESC, p.id DESC')
            : Prisma.raw('p.created_at DESC, p.id DESC')
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
                   s.source_content_revision AS screening_source_content_revision
            FROM job_postings p
            LEFT JOIN job_screenings s ON s.job_posting_id=p.id
            WHERE ${where}
            ORDER BY ${orderSql}
            LIMIT ${size} OFFSET ${page * size}
        `),
        prisma.$queryRaw<Array<{ total: number | bigint }>>(Prisma.sql`
            SELECT COUNT(*) AS total
            FROM job_postings p
            LEFT JOIN job_screenings s ON s.job_posting_id=p.id
            WHERE ${where}
        `),
    ])
    const data = rows.map((row) => {
        const {
            screening_id,
            screening_state,
            screening_result_json,
            screening_error_message,
            screening_backend,
            screening_model,
            screening_effort,
            screening_evaluator_version,
            screening_updated_at,
            screening_source_content_revision,
            score_detail,
            ...posting
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
        }
    })
    return { data, total: Number(countRows[0]?.total ?? 0) }
}

export async function getJobPostings(params: JobPostingsFilter = {}) {
    validateJobPostingsFilter(params)
    const page = Math.max(0, Math.floor(params.page ?? 0))
    const size = Math.min(100, Math.max(1, Math.floor(params.size ?? 25)))
    const bucket = params.bucket ?? 'all'
    if (bucket === 'all') return getAllJobPostings({ ...params, bucket }, page, size)
    const where = await jobWhereForFilter({ ...params, bucket })

    const orderBy: Prisma.job_postingsOrderByWithRelationInput[] =
        params.sort === 'created'
            ? [{ created_at: 'desc' }, { id: 'desc' }]
            : params.sort === 'posted'
                ? [{ posted_at: 'desc' }, { id: 'desc' }]
                : [{ score: 'desc' }, { id: 'asc' }]

    const [data, total] = await Promise.all([
        prisma.job_postings.findMany({
            where,
            orderBy,
            skip: page * size,
            take: size,
            include: {
                job_screening: {
                    select: {
                        id: true,
                        state: true,
                        result_json: true,
                        error_message: true,
                        backend: true,
                        model: true,
                        effort: true,
                        evaluator_version: true,
                        updated_at: true,
                        source_content_revision: true,
                    },
                },
            },
        }),
        prisma.job_postings.count({ where }),
    ])

    return { data: data.map((posting) => enrichJobPosting(posting as ScreenedJobPosting)), total }
}

type JobScopeClient = Pick<Prisma.TransactionClient, 'job_postings' | '$queryRaw'>

async function findPostingInView(client: JobScopeClient, id: number, scope: JobViewScope) {
    validateJobPostingsFilter(scope, true, false)
    if (scope.bucket === 'all') {
        const where = allJobsWhereSql(scope)
        const matches = await client.$queryRaw<Array<{ id: number | bigint }>>(Prisma.sql`
            SELECT p.id
            FROM job_postings p
            LEFT JOIN job_screenings s ON s.job_posting_id=p.id
            WHERE p.id=${id} AND ${where}
            LIMIT 1
        `)
        if (matches.length === 0) return null
        return client.job_postings.findUnique({ where: { id } })
    }
    const where = await jobWhereForFilter(scope)
    return client.job_postings.findFirst({ where: { AND: [where, { id }] } })
}

// The one place a posting's pipeline_status is moved by hand, single-row and bulk.
// The same list predicate must be sent back with a mutation so a crafted/stale request
// cannot broaden a filter or act on a row outside the view that offered the action.
function scopedWhere(where: Prisma.job_postingsWhereInput, ids: number[]): Prisma.job_postingsWhereInput {
    return { AND: [where, { id: { in: ids } }] }
}

function uniquePostingIds(ids: number[]): number[] {
    return [...new Set(ids.filter((id) => Number.isSafeInteger(id) && id > 0))]
}

async function setPipelineStatusInView(
    id: number,
    status: 'removed' | 'scored',
    scope: JobViewScope,
): Promise<{ success: boolean; error?: string }> {
    try {
        validateJobPostingsFilter(scope, true, false)
        const result = await prisma.$transaction(async (tx) => {
            const posting = await findPostingInView(tx, id, scope)
            if (!posting) return { success: false, error: 'Job is outside the requested view and filters' }
            if (status === 'removed' && posting.pipeline_status === 'applied') {
                return { success: false, error: 'Applied postings cannot be removed from the inventory' }
            }
            if (status === 'scored' && posting.pipeline_status !== 'discarded') {
                return { success: false, error: 'Only discarded postings can be reopened' }
            }
            const statusGuard: Prisma.job_postingsWhereInput = status === 'removed'
                ? { pipeline_status: { notIn: ['applied', 'removed'] } }
                : { pipeline_status: 'discarded' }
            const updated = await tx.job_postings.updateMany({
                where: { AND: [{ id }, statusGuard] },
                data: { pipeline_status: status, updated_at: new Date().toISOString() },
            })
            return updated.count === 1
                ? { success: true }
                : { success: false, error: 'Job is no longer eligible in the requested view and filters' }
        })
        return result
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

async function setPipelineStatusManyInView(
    ids: number[],
    status: 'removed' | 'scored',
    scope: JobViewScope,
): Promise<{ success: boolean; error?: string; count?: number }> {
    try {
        validateJobPostingsFilter(scope, true, false)
        if (scope.bucket === 'all') {
            return { success: false, error: 'Bulk lifecycle actions are not supported in All jobs' }
        }
        if (status === 'scored' && scope.bucket !== 'discarded') {
            return { success: false, error: 'Bulk reopen is only supported in the Discarded view' }
        }
        const postingIds = uniquePostingIds(ids)
        if (postingIds.length === 0) return { success: true, count: 0 }
        if (postingIds.length > 100) return { success: false, error: 'Bulk actions are limited to 100 jobs' }

        const where = await jobWhereForFilter(scope)
        const constrainedWhere = scopedWhere(where, postingIds)
        const eligibleCount = await prisma.job_postings.count({ where: constrainedWhere })
        if (eligibleCount !== postingIds.length) {
            return { success: false, error: 'One or more jobs are outside the requested view and filters' }
        }
        const statusGuard: Prisma.job_postingsWhereInput = status === 'removed'
            ? { pipeline_status: { notIn: ['applied', 'removed'] } }
            : {}
        const result = await prisma.job_postings.updateMany({
            where: { AND: [constrainedWhere, statusGuard] },
            data: { pipeline_status: status, updated_at: new Date().toISOString() },
        })
        return { success: true, count: result.count }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

// Per-row dismiss. Writes 'removed' (hidden from every bucket, like bulk Remove) — NOT
// 'discarded'. The Discarded bucket is reserved for the screen's auto-disqualifications,
// so a hand-dismissed row must not masquerade as one (it would also be unreopenable,
// matching no bucket). Reopen a genuine disqualification from the Discarded view instead.
export async function discardJobPosting(id: number, scope: JobViewScope) {
    return setPipelineStatusInView(id, 'removed', scope)
}

// Reverse a discard (whether user-initiated or an LLM disqualification): send the
// posting back into the actionable queue. The stored score_detail — including any
// disqualification_reason — is kept, so the override stays explainable.
export async function reopenJobPosting(id: number, scope: JobViewScope) {
    return setPipelineStatusInView(id, 'scored', scope)
}

// Terminal hide: a 'removed' posting is invisible to every bucket query and inert
// to the worker (ingest is ON CONFLICT DO NOTHING; the pipeline only selects by
// explicit status), so it never re-scores/re-notifies. See the design spec.
export async function bulkRemove(ids: number[], scope: JobViewScope) {
    return setPipelineStatusManyInView(ids, 'removed', scope)
}

export async function bulkReopen(ids: number[], scope: JobViewScope) {
    return setPipelineStatusManyInView(ids, 'scored', scope)
}

// Clear the whole current Discarded view in one click, using the exact predicate the
// list action uses. Inventory is intentionally excluded from bulk lifecycle actions.
export async function removeAllInView(filter: JobViewScope) {
    try {
        validateJobPostingsFilter(filter, true, false)
        if (filter.bucket === 'all') {
            return { success: false, error: 'Bulk lifecycle actions are not supported in All jobs' }
        }
        if (filter.bucket !== 'discarded') {
            return { success: false, error: 'Remove all is only supported in the Discarded view' }
        }
        const where = await jobWhereForFilter(filter)
        const res = await prisma.job_postings.updateMany({
            where: { AND: [where, { pipeline_status: { notIn: ['applied', 'removed'] } }] },
            data: { pipeline_status: 'removed', updated_at: new Date().toISOString() },
        })
        return { success: true, count: res.count }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function markJobApplied(id: number, category: string | undefined, scope: JobViewScope, actor: Actor = 'web') {
    try {
        checkedActor(actor)
        validateJobPostingsFilter(scope, true, false)
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
