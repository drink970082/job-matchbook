'use server'

import { prisma } from '@/lib/db'
import { Prisma } from '@prisma/client'
import { type Actor, STATUSES } from '@/lib/constants'
import { applicationAudit, checkedActor, searchClause, CATEGORY_FALLBACK } from '@/lib/action-helpers'

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
}, actor: Actor = 'web') {
    try {
        checkedActor(actor)
        if (!data.company_name || !data.job_title || !data.date_applied) {
            return { success: false, error: 'Missing required fields' }
        }

        const status = (STATUSES as readonly string[]).includes(data.status ?? '') ? data.status! : 'Applied'
        const category = data.category?.trim() || CATEGORY_FALLBACK

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
            await tx.audit_log.create({ data: applicationAudit(actor, 'add', row.id, row) })
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
            const before = await tx.applications.findUnique({ where: { id } })
            if (!before) return false
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

        // Determine timestamp: use provided date (append noon UTC so it doesn't shift days in local timezones) or current time
        const timestamp = date ? new Date(`${date}T12:00:00Z`).toISOString() : new Date().toISOString()

        // The before snapshot and the no-op check are read in the write transaction.
        const refused = await prisma.$transaction(async (tx) => {
            const app = await tx.applications.findUnique({ where: { id } })
            if (!app) return 'Application not found'
            if (app.status === status) return `Application is already in '${status}' status`

            const after = await tx.applications.update({
                where: { id },
                data: { status, last_updated: new Date().toISOString() },
            })

            const history = await tx.status_history.create({
                data: {
                    application_id: id,
                    status,
                    timestamp,
                    actor,
                },
            })
            await tx.audit_log.create({ data: applicationAudit(actor, 'status', id, { before: app, after, history }) })
            return null
        })
        if (refused) return { success: false, error: refused }

        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

// The delete cascades status_history and nulls job_postings.application_id; in the same
// transaction each linked posting still 'applied' goes back to 'new' so it can be
// marked again (a posting the worker has since closed keeps its status). The audit
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
            orderBy: { timestamp: 'desc' },
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

            // Find the most recent history item after deletion
            const latestHistory = await tx.status_history.findFirst({
                where: { application_id: item.application_id },
                orderBy: { timestamp: 'desc' }
            })

            // Update application status to the most recent history, or 'Applied' if empty
            const newStatus = latestHistory ? latestHistory.status : 'Applied'
            const after = await tx.applications.update({
                where: { id: item.application_id },
                data: { status: newStatus }
            })
            await tx.audit_log.create({ data: applicationAudit(actor, 'remove_history', item.application_id,
                { before, after, removed: item }) })
        })

        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}
