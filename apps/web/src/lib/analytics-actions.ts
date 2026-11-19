'use server'

import { prisma } from '@/lib/db'
import { CATEGORY_FALLBACK } from '@/lib/action-helpers'

// Active = not Offer/Accepted/Rejected/Withdrew and something happened in the last 60
// days (latest status-history date, else date_applied): with Ghosted gone (#205), an
// application that went silent stops counting. Not `last_updated`: that is the write
// time, so a CSV import or a backdated add would read as recent.
const ACTIVE_WINDOW_DAYS = 60

export async function getKPIs() {
    const apps = await prisma.applications.findMany({ select: { status: true, date_applied: true,
        status_history: { select: { timestamp: true }, orderBy: { timestamp: 'desc' }, take: 1 } } })
    const since = new Date(Date.now() - ACTIVE_WINDOW_DAYS * 86_400_000).toISOString().slice(0, 10)
    const stats = { total: apps.length, active: 0, screening: 0, interviewing: 0, rejected: 0, offer: 0 }
    for (const app of apps) {
        if (app.status === 'Screening') stats.screening += 1
        else if (app.status === 'Interviewing') stats.interviewing += 1
        else if (app.status === 'Rejected') stats.rejected += 1
        else if (app.status === 'Offer' || app.status === 'Accepted') stats.offer += 1
        const terminal = ['Offer', 'Accepted', 'Rejected', 'Withdrew'].includes(app.status)
        const last = [app.date_applied, app.status_history?.[0]?.timestamp ?? ''].sort().at(-1)!.slice(0, 10)
        if (!terminal && last >= since) stats.active += 1
    }
    return stats
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
            const cat = app.category || CATEGORY_FALLBACK
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
