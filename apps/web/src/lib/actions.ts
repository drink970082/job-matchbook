'use server'

import { prisma } from '@/lib/db'
import { Prisma } from '@prisma/client'
import { STATUSES, CATEGORIES } from '@/lib/constants'

export async function getApplications(params: {
    page?: number
    size?: number
    status?: string
    historicalStatus?: string
    category?: string
    search?: string
}) {
    const page = params.page || 0
    const size = params.size || 10
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

// Pipeline statuses that make up the actionable "discovered jobs" queue.
const ACTIONABLE_PIPELINE_STATUSES = ['scored', 'tailored', 'notified'] as const

export async function getJobPostings(params: {
    minScore?: number
    status?: string
    search?: string
}) {
    const minScore = params.minScore
    const search = params.search || ''

    // Default: show only the actionable queue (scored/tailored/notified).
    // An explicit status filters to that one status; 'all' removes the filter.
    let statusFilter: Prisma.job_postingsWhereInput = {}
    if (params.status === 'all') {
        statusFilter = {}
    } else if (params.status) {
        statusFilter = { pipeline_status: params.status }
    } else {
        statusFilter = { pipeline_status: { in: [...ACTIONABLE_PIPELINE_STATUSES] } }
    }

    const where: Prisma.job_postingsWhereInput = {
        AND: [
            statusFilter,
            minScore !== undefined && minScore !== null ? { score: { gte: minScore } } : {},
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
        prisma.job_postings.findMany({
            where,
            orderBy: [{ score: 'desc' }, { id: 'asc' }],
        }),
        prisma.job_postings.count({ where }),
    ])

    return { data, total }
}

export async function discardJobPosting(id: number) {
    try {
        await prisma.job_postings.update({
            where: { id },
            data: { pipeline_status: 'discarded', updated_at: new Date().toISOString() },
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

export async function markJobApplied(id: number) {
    try {
        const posting = await prisma.job_postings.findUnique({ where: { id } })
        if (!posting) {
            return { success: false, error: 'Job posting not found' }
        }

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
                    category: 'Others',
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

        const existing = await prisma.applications.findFirst({
            where: {
                company_name: data.company_name,
                job_title: data.job_title,
            },
        })

        if (existing) {
            return {
                success: false,
                error: `Application for ${data.company_name} - ${data.job_title} already exists`,
            }
        }

        const newApp = await prisma.applications.create({
            data: {
                company_name: data.company_name,
                job_title: data.job_title,
                date_applied: data.date_applied,
                category: data.category || 'Others',
                status: data.status || 'Applied',
                application_url: data.application_url || '',
                notes: data.notes || '',
                last_updated: new Date().toISOString(),
            },
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
        await prisma.applications.update({
            where: { id },
            data: {
                company_name: data.company_name,
                job_title: data.job_title,
                category: data.category,
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

export async function updateApplicationStatus(id: number, status: string, date?: string, notes?: string) {
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

        await prisma.status_history.delete({
            where: { id },
        })

        // Find the most recent history item after deletion
        const latestHistory = await prisma.status_history.findFirst({
            where: { application_id: item.application_id },
            orderBy: { timestamp: 'desc' }
        })

        // Update application status to the most recent history, or 'Applied' if empty
        const newStatus = latestHistory ? latestHistory.status : 'Applied'
        await prisma.applications.update({
            where: { id: item.application_id },
            data: { status: newStatus }
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
    const s = String(value)
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
        const categorySet = new Set<string>(CATEGORIES as readonly string[])

        let added = 0
        let skipped = 0
        const errors: string[] = []

        for (let i = 0; i < dataRows.length; i++) {
            const row = dataRows[i]
            const rowNum = i + 2

            const get = (col: string) => {
                const idx = colIndex(col)
                return idx === -1 ? '' : (row[idx] ?? '').trim()
            }

            const company_name = get('company_name')
            const job_title = get('job_title')
            const date_applied = get('date_applied')

            if (!company_name || !job_title || !date_applied) {
                errors.push(`Row ${rowNum}: missing required field`)
                continue
            }

            const existing = await prisma.applications.findFirst({
                where: { company_name, job_title },
            })
            if (existing) {
                skipped++
                continue
            }

            const rawStatus = get('status') || 'Applied'
            const status = statusSet.has(rawStatus) ? rawStatus : 'Applied'
            const rawCategory = get('category') || 'Others'
            const category = categorySet.has(rawCategory) ? rawCategory : 'Others'

            await prisma.applications.create({
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
            added++
        }

        return { success: true, added, skipped, errors }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}
