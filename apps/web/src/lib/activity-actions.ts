'use server'

import { prisma } from '@/lib/db'
import { funnelStarts, intakeFunnel, type IntakeFunnel } from '@/lib/intake-funnel'
import type { PassFailure, PassRecord } from '@/lib/pass-record'

// The Activity tab (#210): a system status strip and one merged timeline of who wrote
// what (actor web | mcp), newest first.

const DAY = 86_400_000
const iso = (msAgo: number) => new Date(Date.now() - msAgo).toISOString()

// "Is it running, what did it cost": the latest pass record (`worker_runs`, #249) plus
// posting and JEV counts from their own columns. `lib/pass-record.ts` turns the pass
// into the strip's lines.
export async function getActivityStatus() {
    const [run, new24h, new7d, assessed24h, failures24h, spend, agedOut7d, agedOutTotal] = await Promise.all([
        prisma.worker_runs.findFirst({ orderBy: [{ started_at: 'desc' }, { id: 'desc' }] }),
        prisma.job_postings.count({ where: { created_at: { gte: iso(DAY) } } }),
        prisma.job_postings.count({ where: { created_at: { gte: iso(7 * DAY) } } }),
        prisma.job_jev_assessments.count({ where: { state: 'complete', last_attempted_at: { gte: iso(DAY) } } }),
        prisma.job_jev_assessments.count({ where: { state: 'provider_error', last_attempted_at: { gte: iso(DAY) } } }),
        prisma.job_jev_assessments.findMany({ where: { last_attempted_at: { gte: iso(7 * DAY) }, cost_usd: { not: null } },
            select: { cost_usd: true } }),
        // Postings that left the evaluation window before every stage finished (#225).
        prisma.job_postings.count({ where: { verdict: 'not_evaluated', verdict_at: { gte: iso(7 * DAY) } } }),
        prisma.job_postings.count({ where: { verdict: 'not_evaluated' } }),
    ])
    const spend7d = spend.reduce((n, r) => n + (Number(r.cost_usd) || 0), 0)
    // A dead pass is marked failed only as the next one starts running, so the latest
    // row hides it: read the failures since the last ok pass separately.
    const lastOk = await prisma.worker_runs.findFirst({ where: { status: 'ok' }, orderBy: [{ started_at: 'desc' }, { id: 'desc' }],
        select: { started_at: true } })
    const failedSince = { status: 'failed', ...(lastOk ? { started_at: { gt: lastOk.started_at } } : {}) }
    const [failed, failedCount] = await Promise.all([
        prisma.worker_runs.findFirst({ where: failedSince, orderBy: [{ started_at: 'desc' }, { id: 'desc' }] }),
        prisma.worker_runs.count({ where: failedSince }),
    ])
    const funnel = await readIntakeFunnel()
    const lastFailure: PassFailure | null = failed
        && { startedAt: failed.started_at, errorCategory: failed.error_category, since: failedCount }
    const lastPass: PassRecord | null = run && {
        startedAt: run.started_at, finishedAt: run.finished_at, status: run.status, errorCategory: run.error_category,
        fetchOnly: run.fetch_only, jevEnabled: run.jev_enabled, config: parseObject(run.config_json),
        counts: parseObject(run.counts_json),
    }
    return {
        lastPass, lastFailure, new24h, new7d, assessed24h, failures24h,
        spend7dUsd: Math.round(spend7d * 10_000) / 10_000, agedOut7d, agedOutTotal, funnel,
    }
}

// The intake funnel (#248) of the latest pass and the last 7 days: lib/intake-funnel.ts.
async function readIntakeFunnel(): Promise<IntakeFunnel> {
    const now = Date.now()
    const runs = (await prisma.worker_runs.findMany({ orderBy: [{ started_at: 'asc' }, { id: 'asc' }],
        select: { started_at: true, status: true, counts_json: true } }))
        .map((r) => ({ started_at: r.started_at, status: r.status, counts: parseObject(r.counts_json) }))
    const starts = funnelStarts(runs, now)
    const rows = starts.length ? await prisma.job_postings.findMany({ where: { created_at: { in: starts } },
        select: { created_at: true, verdict: true, source_state: true,
            job_screening: { select: { state: true, result_json: true } } } }) : []
    return intakeFunnel(runs, rows.map(({ job_screening: s, ...p }) => ({ ...p,
        result_json: s?.state === 'complete' ? s.result_json : null })), now)
}

// The worker writes both JSON columns; a value it could not have written reads as empty.
function parseObject(raw: string): Record<string, any> {
    try {
        const v = JSON.parse(raw)
        return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
    } catch {
        return {}
    }
}

export interface ActivityItem { key: string; at: string; text: string; actor: string }
type Sortable = ActivityItem & { rank: number; id: number }

const MAX_TAKE = 500

// One list from three sources that share no key: applications (no creation stamp, so
// `date_applied`), status changes (`timestamp`, the date the change happened) and
// audit_log (`at`, write time). Offset paging over the merge: each source supplies its
// newest offset+limit rows, which always cover the merged page.
export async function getActivityTimeline(offset = 0, limit = 30) {
    const off = Number.isInteger(offset) ? Math.max(offset, 0) : 0
    const lim = Number.isInteger(limit) ? Math.min(Math.max(limit, 1), 100) : 30
    const take = Math.min(off + lim + 1, MAX_TAKE)
    const [applications, statusChanges, audits] = await Promise.all([
        prisma.applications.findMany({ orderBy: [{ date_applied: 'desc' }, { id: 'desc' }], take,
            select: { id: true, company_name: true, job_title: true, date_applied: true, actor: true } }),
        // "Applied" is the row an application starts with; the application line covers it.
        prisma.status_history.findMany({ where: { status: { not: 'Applied' } }, orderBy: [{ timestamp: 'desc' }, { id: 'desc' }], take,
            select: { id: true, status: true, timestamp: true, actor: true,
                applications: { select: { company_name: true, job_title: true } } } }),
        // An application add or status change is already its own line above.
        prisma.audit_log.findMany({ where: { NOT: { entity: 'applications', action: { in: ['add', 'status'] } } },
            orderBy: [{ at: 'desc' }, { id: 'desc' }], take }),
    ])
    const jobIds = audits.filter((a) => a.entity === 'job_triage_overrides').map((a) => a.entity_id)
    const jobs = new Map((jobIds.length ? await prisma.job_postings.findMany({ where: { id: { in: jobIds } },
        select: { id: true, company_name: true, job_title: true } }) : []).map((j) => [j.id, `${j.company_name} - ${j.job_title}`]))

    // Ties (same-day applications) break by source, then id desc: the order each query
    // fetched in, so a row cut off one source's `take` can never sort into the page.
    const items: Sortable[] = [
        ...applications.map((a) => ({ key: `a${a.id}`, rank: 0, id: a.id, at: a.date_applied, actor: a.actor,
            text: `Applied to ${a.company_name} - ${a.job_title}` })),
        ...statusChanges.map((h) => ({ key: `h${h.id}`, rank: 1, id: h.id, at: h.timestamp, actor: h.actor,
            text: `${h.applications.company_name} - ${h.applications.job_title} -> ${h.status}` })),
        ...audits.map((c) => ({ key: `c${c.id}`, rank: 2, id: c.id, at: c.at, actor: c.actor, text: auditText(c, jobs) })),
    ].sort((x, y) => (x.at < y.at ? 1 : x.at > y.at ? -1 : x.rank - y.rank || y.id - x.id))
    // Never page past MAX_TAKE: each source supplies at most that many rows, so deeper
    // positions could be missing rows. `capped` tells the UI older activity is not shown.
    const end = Math.min(off + lim, MAX_TAKE)
    const page = items.slice(off, end).map(({ rank: _r, id: _i, ...item }) => item)
    return { items: page, nextOffset: off + page.length,
        hasMore: items.length > end && end < MAX_TAKE, capped: end >= MAX_TAKE && items.length > end }
}

// One plain-English line per audit row; the payload is the row as written (or {before, after}).
function auditText(c: { entity: string; action: string; entity_id: number; payload: string }, jobs: Map<number, string>): string {
    let p: any
    try { p = JSON.parse(c.payload) } catch { p = null }
    const row = p?.after ?? p ?? {}
    switch (c.entity) {
        case 'watched_companies':
            return `${c.action === 'remove' ? 'Removed' : 'Added'} board ${row.name ?? `${row.source}/${row.slug}`}`
        case 'job_triage_overrides': {
            const job = jobs.get(c.entity_id) ?? `job ${c.entity_id}`
            if (c.action === 'remove') return `Cleared the keep/skip override on ${job}`
            return row.decision === 'skip' ? `Hid ${job}` : `Kept ${job}`
        }
        case 'applications': {
            const app = `${row.company_name} - ${row.job_title}`
            if (c.action === 'remove') return `Deleted the application ${app}`
            if (c.action === 'link') return `Linked ${app} to its posting`
            if (c.action === 'remove_history') return `Removed ${p.removed?.status} from the history of ${app}`
            return `Edited ${app}`
        }
        case 'candidate_preferences': return 'Updated hard requirements'
        case 'jev_profile': return 'Updated the JEV profile'
        case 'candidate_profile': return 'Updated the candidate profile'
        default: return `${c.action} ${c.entity}`
    }
}
