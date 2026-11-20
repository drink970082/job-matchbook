'use server'

import { prisma } from '@/lib/db'

// The Activity tab (#210): a system status strip and one merged timeline of who wrote
// what (actor web | mcp), newest first.

const DAY = 86_400_000
const iso = (msAgo: number) => new Date(Date.now() - msAgo).toISOString()

// "Is it running, what did it cost": all from existing columns (no run table exists, so
// a failing pass shows only through these numbers).
export async function getActivityStatus() {
    const [latest, new24h, new7d, assessed24h, failures24h, spend] = await Promise.all([
        prisma.job_postings.aggregate({ _max: { created_at: true } }),
        prisma.job_postings.count({ where: { created_at: { gte: iso(DAY) } } }),
        prisma.job_postings.count({ where: { created_at: { gte: iso(7 * DAY) } } }),
        prisma.job_jev_assessments.count({ where: { state: 'complete', last_attempted_at: { gte: iso(DAY) } } }),
        prisma.job_jev_assessments.count({ where: { state: 'provider_error', last_attempted_at: { gte: iso(DAY) } } }),
        prisma.job_jev_assessments.findMany({ where: { last_attempted_at: { gte: iso(7 * DAY) }, cost_usd: { not: null } },
            select: { cost_usd: true } }),
    ])
    const spend7d = spend.reduce((n, r) => n + (Number(r.cost_usd) || 0), 0)
    return {
        lastFetchedAt: latest._max.created_at, new24h, new7d, assessed24h, failures24h,
        spend7dUsd: Math.round(spend7d * 10_000) / 10_000,
    }
}

export interface ActivityItem { key: string; at: string; text: string; actor: string }

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
        prisma.audit_log.findMany({ orderBy: [{ at: 'desc' }, { id: 'desc' }], take }),
    ])
    const jobIds = audits.filter((a) => a.entity === 'job_triage_overrides').map((a) => a.entity_id)
    const jobs = new Map((jobIds.length ? await prisma.job_postings.findMany({ where: { id: { in: jobIds } },
        select: { id: true, company_name: true, job_title: true } }) : []).map((j) => [j.id, `${j.company_name} - ${j.job_title}`]))

    const items: ActivityItem[] = [
        ...applications.map((a) => ({ key: `a${a.id}`, at: a.date_applied, actor: a.actor,
            text: `Applied to ${a.company_name} - ${a.job_title}` })),
        ...statusChanges.map((h) => ({ key: `h${h.id}`, at: h.timestamp, actor: h.actor,
            text: `${h.applications.company_name} - ${h.applications.job_title} -> ${h.status}` })),
        ...audits.map((c) => ({ key: `c${c.id}`, at: c.at, actor: c.actor, text: auditText(c, jobs) })),
    ].sort((x, y) => (x.at < y.at ? 1 : x.at > y.at ? -1 : y.key.localeCompare(x.key)))
    return { items: items.slice(off, off + lim), hasMore: items.length > off + lim && off + lim < MAX_TAKE }
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
        case 'candidate_preferences': return 'Updated hard requirements'
        case 'jev_profile': return 'Updated the JEV profile'
        default: return `${c.action} ${c.entity}`
    }
}
