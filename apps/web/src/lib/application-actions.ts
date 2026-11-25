'use server'

import { prisma } from '@/lib/db'
import { Prisma } from '@prisma/client'
import { type Actor, STATUSES } from '@/lib/constants'
import { todayISO } from '@/lib/utils'
import { duplicateKey } from '@/lib/application-match'
import { applicationAudit, checkedActor, duplicateError, findDuplicate, linkPosting, searchClause, syncStatusFromHistory, writeInitialHistory, CATEGORY_FALLBACK } from '@/lib/action-helpers'

// Header sort on the Applications table (#205): one column, server-side (paginated).
export type ApplicationSort = { sort: 'company' | 'date' | 'status'; dir: 'asc' | 'desc' }
const SORT_FIELD = { company: 'company_name', date: 'date_applied', status: 'status' } as const

export async function getApplications(params: {
    page?: number
    size?: number
    status?: string
    historicalStatus?: string
    category?: string
    search?: string
} & Partial<ApplicationSort>) {
    const page = Math.max(0, Math.floor(params.page || 0))
    const size = Math.min(100, Math.max(1, Math.floor(params.size || 10)))
    const status = params.status === 'all' ? undefined : params.status
    const historicalStatus = params.historicalStatus === 'all' ? undefined : params.historicalStatus
    const category = params.category === 'all' ? undefined : params.category
    const search = params.search || ''
    const sortKey = params.sort && Object.hasOwn(SORT_FIELD, params.sort) ? params.sort : 'date'
    const dir = params.dir === 'asc' ? 'asc' : 'desc'

    const where: Prisma.applicationsWhereInput = {
        AND: [
            status ? { status } : {},
            historicalStatus ? { status_history: { some: { status: historicalStatus } } } : {},
            category ? { category } : {},
            searchClause(search),
        ],
    }

    const [data, total] = await Promise.all([
        prisma.applications.findMany({
            where,
            skip: page * size,
            take: size,
            orderBy: [{ [SORT_FIELD[sortKey]]: dir }, { id: 'desc' }],
            include: { job_postings: { select: { id: true } } }, // linked or not (#241)
        }),
        prisma.applications.count({ where }),
    ])

    return { data, total }
}

export async function addApplication(data: {
    company_name: string
    job_title: string
    date_applied: string
    category?: string
    status?: string
    application_url?: string
    notes?: string
    job_id?: number // the posting it was made for (#241); refused like any other link
}, actor: Actor = 'web') {
    try {
        checkedActor(actor)
        if (!data.company_name || !data.job_title || !data.date_applied) {
            return { success: false, error: 'Missing required fields' }
        }

        const status = (STATUSES as readonly string[]).includes(data.status ?? '') ? data.status! : 'Applied'
        const category = data.category?.trim() || CATEGORY_FALLBACK

        const newApp = await prisma.$transaction(async (tx) => {
            // Throw to roll back the transaction; surfaced as a failure below.
            const existing = await findDuplicate(tx, data, data.job_id !== undefined)
            if (existing) throw duplicateError(existing)

            const row = await tx.applications.create({
                data: {
                    company_name: data.company_name,
                    job_title: data.job_title,
                    date_applied: data.date_applied,
                    category,
                    status,
                    application_url: data.application_url || '',
                    notes: data.notes || '',
                    last_updated: new Date().toISOString(),
                    actor,
                },
            })
            await writeInitialHistory(tx, row)
            await tx.audit_log.create({ data: applicationAudit(actor, 'add', row.id, row) })
            if (data.job_id !== undefined) await linkPosting(tx, row.id, data.job_id, actor)
            return row
        })

        return { success: true, data: newApp }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function updateApplicationDetails(
    id: number,
    // A field left undefined is left unchanged (the API sends partial updates; the UI
    // sends every field). A blank category still falls back to CATEGORY_FALLBACK.
    data: {
        company_name?: string
        job_title?: string
        category?: string
        application_url?: string
        date_applied?: string
        notes?: string
    },
    actor: Actor = 'web',
) {
    try {
        checkedActor(actor)
        const category = data.category === undefined ? undefined : data.category.trim() || CATEGORY_FALLBACK

        const found = await prisma.$transaction(async (tx) => {
            const found = await tx.applications.findUnique({ where: { id }, include: { job_postings: { select: { id: true } } } })
            if (!found) return false
            const { job_postings, ...before } = found
            // Checked only when the edit makes it a different application: a pair stored
            // before this check existed can still have its notes or spelling edited.
            const names = { company_name: data.company_name ?? before.company_name, job_title: data.job_title ?? before.job_title }
            if (duplicateKey(names) !== duplicateKey(before)) {
                const dup = await findDuplicate(tx, names, job_postings.length > 0, id)
                if (dup) throw duplicateError(dup)
            }
            const after = await tx.applications.update({
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
            await tx.audit_log.create({ data: applicationAudit(actor, 'update', id, { before, after }) })
            return true
        })
        if (!found) return { success: false, error: 'Application not found' }
        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function updateApplicationStatus(id: number, status: string, date?: string, actor: Actor = 'web') {
    try {
        checkedActor(actor)
        if (!STATUSES.includes(status as any)) {
            return { success: false, error: 'Invalid status' }
        }

        // A past date is stamped noon UTC (no day shift in local timezones), never later
        // than now: a future stamp would outrank every later change until it passed. No
        // date, or today's server-local date (the modal's default), is stamped now so it
        // orders against other same-day writes by when they happened.
        const now = new Date().toISOString()
        const noon = date && date !== todayISO() ? new Date(`${date}T12:00:00Z`).toISOString() : now
        const timestamp = noon < now ? noon : now

        // The before snapshot and the no-op check are read in the write transaction. A
        // backdated row is recorded but only becomes current if it is the latest; the
        // caller gets both, so it can say so.
        const result = await prisma.$transaction(async (tx) => {
            const app = await tx.applications.findUnique({ where: { id } })
            if (!app) return { refused: 'Application not found' }
            if (app.status === status) return { refused: `Application is already in '${status}' status` }

            const history = await tx.status_history.create({
                data: {
                    application_id: id,
                    status,
                    timestamp,
                    actor,
                },
            })
            const after = await syncStatusFromHistory(tx, id, { last_updated: new Date().toISOString() })
            await tx.audit_log.create({ data: applicationAudit(actor, 'status', id, { before: app, after, history }) })
            return { current: after.status }
        })
        if (result.refused) return { success: false, error: result.refused }

        return { success: true, data: { status: result.current!, recorded: status } }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

// The delete cascades status_history and nulls job_postings.application_id; in the same
// transaction each linked posting still 'applied' goes back to 'new' so it can be
// marked again (other statuses and source_state are untouched). The audit
// payload is the row plus its history and the linked posting ids.
export async function deleteApplication(id: number, actor: Actor = 'web') {
    try {
        checkedActor(actor)
        const found = await prisma.$transaction(async (tx) => {
            const row = await tx.applications.findUnique({
                where: { id },
                include: { status_history: true, job_postings: { select: { id: true } } },
            })
            if (!row) return false
            const { job_postings, ...rest } = row
            await tx.job_postings.updateMany({
                where: { application_id: id, pipeline_status: 'applied' },
                data: { pipeline_status: 'new', updated_at: new Date().toISOString() },
            })
            await tx.applications.delete({ where: { id } })
            await tx.audit_log.create({ data: applicationAudit(actor, 'remove', id,
                { ...rest, job_posting_ids: job_postings.map((p) => p.id) }) })
            return true
        })
        if (!found) return { success: false, error: 'Application not found' }
        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function getApplicationHistory(id: number) {
    try {
        const history = await prisma.status_history.findMany({
            where: { application_id: id },
            orderBy: [{ timestamp: 'desc' }, { id: 'desc' }],
        })
        return { success: true, data: history }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function deleteHistoryItem(id: number, actor: Actor = 'web') {
    try {
        checkedActor(actor)
        const item = await prisma.status_history.findUnique({ where: { id } })

        if (!item) {
            return { success: false, error: 'History item not found' }
        }

        await prisma.$transaction(async (tx) => {
            const before = await tx.applications.findUniqueOrThrow({ where: { id: item.application_id } })
            await tx.status_history.delete({
                where: { id },
            })
            const after = await syncStatusFromHistory(tx, item.application_id)
            await tx.audit_log.create({ data: applicationAudit(actor, 'remove_history', item.application_id,
                { before, after, removed: item }) })
        })

        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}
