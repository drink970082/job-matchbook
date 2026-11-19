'use server'

import { prisma } from '@/lib/db'

// The Activity tab (#158): recent writes and who made them (actor web | mcp), newest
// first. Three lists, because the sources share no write-time key: applications have
// no creation stamp (id order), status_history.timestamp is the date the change
// happened, audit_log.at is the write time.
export async function getRecentActivity(limit = 15) {
    const take = Number.isInteger(limit) ? Math.min(Math.max(limit, 1), 100) : 15
    const [applications, statusChanges, changes] = await Promise.all([
        prisma.applications.findMany({
            orderBy: { id: 'desc' }, take,
            select: { id: true, company_name: true, job_title: true, date_applied: true, actor: true },
        }),
        prisma.status_history.findMany({
            orderBy: { id: 'desc' }, take,
            select: { id: true, status: true, timestamp: true, actor: true,
                applications: { select: { company_name: true, job_title: true } } },
        }),
        prisma.audit_log.findMany({ orderBy: { id: 'desc' }, take }),
    ])
    return {
        applications,
        statusChanges: statusChanges.map(({ applications: a, ...h }) => ({ ...h, company_name: a.company_name, job_title: a.job_title })),
        changes: changes.map(({ payload, ...c }) => ({ ...c, label: auditLabel(c.entity, payload) })),
    }
}

// One readable line per audit row; the payload is the row as written (or {before, after}).
function auditLabel(entity: string, payload: string): string {
    let p: any
    try { p = JSON.parse(payload) } catch { return entity }
    const row = p?.after ?? p
    switch (entity) {
        case 'watched_companies': return `${row?.name ?? '?'} (${row?.source}/${row?.slug})`
        case 'job_triage_overrides': return `job ${row?.job_posting_id ?? '?'}: ${row?.decision ?? '?'}`
        case 'candidate_preferences': return `hard requirements v${row?.version ?? '?'}`
        case 'jev_profile': return `JEV profile v${row?.version ?? '?'}`
        default: return entity
    }
}
