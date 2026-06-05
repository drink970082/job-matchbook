'use client'

import { useMemo, useState } from 'react'

interface TimelineHeatmapProps {
    data: { date: string; count: number }[]
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function getColor(count: number, max: number): string {
    if (count === 0) return '#e5e7eb'
    const ratio = count / max
    if (ratio <= 0.25) return '#a7f3d0'
    if (ratio <= 0.5) return '#34d399'
    if (ratio <= 0.75) return '#10b981'
    return '#047857'
}

export function TimelineHeatmap({ data }: TimelineHeatmapProps) {
    const [tooltip, setTooltip] = useState<{ x: number; y: number; date: string; count: number } | null>(null)

    const { weeks, monthLabels, maxCount } = useMemo(() => {
        const countMap = new Map<string, number>()
        let maxCount = 1
        for (const d of data) {
            countMap.set(d.date, d.count)
            if (d.count > maxCount) maxCount = d.count
        }

        // Use a fixed reference: today's date as YYYY-MM-DD (avoids hydration mismatch)
        const now = new Date()
        const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
        const today = new Date(todayStr + 'T00:00:00')

        const startDate = new Date(today)
        startDate.setFullYear(startDate.getFullYear() - 1)
        startDate.setDate(startDate.getDate() - startDate.getDay())

        const weeks: { dateStr: string; dayOfWeek: number; count: number }[][] = []
        const monthLabels: { label: string; weekIndex: number }[] = []
        let currentWeek: { dateStr: string; dayOfWeek: number; count: number }[] = []
        let lastMonth = -1

        const cursor = new Date(startDate)
        let weekIndex = 0

        while (cursor <= today) {
            const y = cursor.getFullYear()
            const m = String(cursor.getMonth() + 1).padStart(2, '0')
            const d = String(cursor.getDate()).padStart(2, '0')
            const dateStr = `${y}-${m}-${d}`
            const count = countMap.get(dateStr) || 0
            currentWeek.push({ dateStr, dayOfWeek: cursor.getDay(), count })

            if (cursor.getMonth() !== lastMonth) {
                monthLabels.push({ label: MONTHS[cursor.getMonth()], weekIndex })
                lastMonth = cursor.getMonth()
            }

            if (cursor.getDay() === 6) {
                weeks.push(currentWeek)
                currentWeek = []
                weekIndex++
            }

            cursor.setDate(cursor.getDate() + 1)
        }
        if (currentWeek.length > 0) weeks.push(currentWeek)

        return { weeks, monthLabels, maxCount }
    }, [data])

    const CELL = 10
    const GAP = 2
    const LEFT = 28
    const TOP = 16
    const svgW = LEFT + weeks.length * (CELL + GAP)
    const svgH = TOP + 7 * (CELL + GAP) + 20

    return (
        <div className="w-full relative" suppressHydrationWarning>
            <div className="overflow-x-auto">
                <svg width={svgW} height={svgH} className="block" suppressHydrationWarning>
                    {/* Month labels */}
                    {monthLabels.map((m, i) => (
                        <text key={`${m.label}-${i}`} x={LEFT + m.weekIndex * (CELL + GAP)} y={11} fill="#9ca3af" fontSize={9}>
                            {m.label}
                        </text>
                    ))}
                    {/* Day labels */}
                    {['Mon', 'Wed', 'Fri'].map((d, i) => (
                        <text key={d} x={0} y={TOP + (i * 2 + 1) * (CELL + GAP) + CELL - 1} fill="#9ca3af" fontSize={9}>
                            {d}
                        </text>
                    ))}
                    {/* Cells */}
                    {weeks.map((week, wi) =>
                        week.map((day) => (
                            <rect
                                key={`${wi}-${day.dayOfWeek}`}
                                x={LEFT + wi * (CELL + GAP)}
                                y={TOP + day.dayOfWeek * (CELL + GAP)}
                                width={CELL}
                                height={CELL}
                                rx={2}
                                fill={getColor(day.count, maxCount)}
                                style={{ cursor: 'pointer' }}
                                onMouseEnter={(e) => {
                                    const rect = e.currentTarget.getBoundingClientRect()
                                    const parent = e.currentTarget.closest('.relative')?.getBoundingClientRect()
                                    if (parent) {
                                        setTooltip({
                                            x: rect.left - parent.left + rect.width / 2,
                                            y: rect.top - parent.top - 4,
                                            date: day.dateStr,
                                            count: day.count,
                                        })
                                    }
                                }}
                                onMouseLeave={() => setTooltip(null)}
                            />
                        ))
                    )}
                    {/* Legend */}
                    <text x={LEFT} y={svgH - 4} fill="#9ca3af" fontSize={9}>Less</text>
                    {['#e5e7eb', '#a7f3d0', '#34d399', '#10b981', '#047857'].map((c, i) => (
                        <rect key={c} x={LEFT + 28 + i * 14} y={svgH - 14} width={10} height={10} rx={2} fill={c} />
                    ))}
                    <text x={LEFT + 28 + 5 * 14 + 4} y={svgH - 4} fill="#9ca3af" fontSize={9}>More</text>
                </svg>
            </div>
            {/* Tooltip */}
            {tooltip && (
                <div
                    className="absolute pointer-events-none bg-popover text-popover-foreground border border-border rounded-md px-2 py-1 shadow-md text-xs whitespace-nowrap z-50"
                    style={{
                        left: tooltip.x,
                        top: tooltip.y,
                        transform: 'translate(-50%, -100%)',
                    }}
                >
                    <span className="font-medium">{tooltip.date}</span>
                    <span className="text-muted-foreground ml-1.5">{tooltip.count} app{tooltip.count !== 1 ? 's' : ''}</span>
                </div>
            )}
        </div>
    )
}
