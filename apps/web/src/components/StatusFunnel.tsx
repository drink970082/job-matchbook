'use client'

import { useMemo } from 'react'

interface StatusFunnelProps {
    data: { from: string; to: string; value: number }[]
}

const STATUS_COLORS: Record<string, string> = {
    'Applied': '#3b82f6',
    'Online Assessment': '#8b5cf6',
    'Phone Screen': '#a78bfa',
    'Interviewing: 1st round': '#f59e0b',
    'Interviewing: 2nd round': '#eab308',
    'Interviewing: 3rd round': '#f97316',
    'Interviewing: 4th round': '#ea580c',
    'Interviewing: 5th round': '#dc2626',
    'Final Round': '#d97706',
    'Rejected': '#ef4444',
    'Offer': '#10b981',
    'Accepted': '#059669',
    'Withdrew': '#64748b',
    'Ghosted': '#94a3b8',
    'No Response': '#9ca3af',
}

function getColor(name: string): string {
    return STATUS_COLORS[name] || '#6b7280'
}

export function StatusFunnel({ data }: StatusFunnelProps) {
    const { stages, totalApplied } = useMemo(() => {
        if (!data || data.length === 0) return { stages: [], totalApplied: 0 }

        // Count how many apps reached each status (as destination)
        const statusCounts = new Map<string, number>()
        for (const d of data) {
            statusCounts.set(d.to, (statusCounts.get(d.to) || 0) + d.value)
        }
        // Applied is always the source
        let totalApplied = 0
        for (const d of data) {
            if (d.from === 'Applied') totalApplied += d.value
        }

        // Define stage order for funnel
        const stageOrder = [
            'Online Assessment',
            'Phone Screen',
            'Interviewing: 1st round',
            'Interviewing: 2nd round',
            'Interviewing: 3rd round',
            'Interviewing: 4th round',
            'Interviewing: 5th round',
            'Final Round',
            'Offer',
            'Accepted',
        ]

        // Terminal statuses shown separately
        const terminalStatuses = ['No Response', 'Rejected', 'Withdrew', 'Ghosted']

        const stages: { name: string; count: number; color: string; isTerminal: boolean }[] = []

        for (const name of stageOrder) {
            const count = statusCounts.get(name) || 0
            if (count > 0) {
                stages.push({ name, count, color: getColor(name), isTerminal: false })
            }
        }

        for (const name of terminalStatuses) {
            const count = statusCounts.get(name) || 0
            if (count > 0) {
                stages.push({ name, count, color: getColor(name), isTerminal: true })
            }
        }

        return { stages, totalApplied }
    }, [data])

    if (stages.length === 0) {
        return <div className="flex items-center justify-center h-[200px] text-muted-foreground text-sm">No status flow data</div>
    }

    const maxCount = totalApplied

    return (
        <div className="space-y-3">
            {/* Applied bar */}
            <div>
                <div className="flex justify-between items-center mb-1">
                    <span className="text-sm font-medium">Applied</span>
                    <span className="text-sm font-bold">{totalApplied}</span>
                </div>
                <div className="h-8 rounded-md w-full" style={{ backgroundColor: getColor('Applied') }} />
            </div>

            {/* Progression stages */}
            {stages.filter(s => !s.isTerminal).length > 0 && (
                <div className="space-y-2 pl-4 border-l-2 border-border">
                    {stages.filter(s => !s.isTerminal).map((stage) => {
                        const pct = (stage.count / maxCount) * 100
                        const conversionRate = ((stage.count / maxCount) * 100).toFixed(1)
                        return (
                            <div key={stage.name}>
                                <div className="flex justify-between items-center mb-0.5">
                                    <span className="text-xs text-muted-foreground">{stage.name}</span>
                                    <span className="text-xs font-semibold">
                                        {stage.count} <span className="text-muted-foreground font-normal">({conversionRate}%)</span>
                                    </span>
                                </div>
                                <div className="h-5 rounded bg-muted overflow-hidden">
                                    <div
                                        className="h-full rounded transition-all duration-500"
                                        style={{ width: `${Math.max(pct, 2)}%`, backgroundColor: stage.color }}
                                    />
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}

            {/* Terminal statuses */}
            {stages.filter(s => s.isTerminal).length > 0 && (
                <div className="space-y-2 pt-2 border-t border-border">
                    {stages.filter(s => s.isTerminal).map((stage) => {
                        const pct = (stage.count / maxCount) * 100
                        const conversionRate = ((stage.count / maxCount) * 100).toFixed(1)
                        return (
                            <div key={stage.name}>
                                <div className="flex justify-between items-center mb-0.5">
                                    <span className="text-xs text-muted-foreground">{stage.name}</span>
                                    <span className="text-xs font-semibold">
                                        {stage.count} <span className="text-muted-foreground font-normal">({conversionRate}%)</span>
                                    </span>
                                </div>
                                <div className="h-5 rounded bg-muted overflow-hidden">
                                    <div
                                        className="h-full rounded transition-all duration-500"
                                        style={{ width: `${Math.max(pct, 2)}%`, backgroundColor: stage.color }}
                                    />
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
