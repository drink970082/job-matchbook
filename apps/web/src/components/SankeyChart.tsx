'use client'

import { useMemo, useState } from 'react'

interface SankeyChartProps {
    data: { from: string; to: string; value: number }[]
}

// Muted, low-saturation palette — every hue sits around L≈62% S≈22% so they read
// as quiet variants of the same family rather than competing accents.
const TONE = {
    slate:    'rgb(148, 163, 184)', // neutral / default
    sky:      'rgb(140, 165, 184)', // start (Applied)
    indigo:   'rgb(151, 145, 184)', // assessments / screens
    amber:    'rgb(184, 165, 130)', // interviewing
    gold:     'rgb(184, 156, 110)', // final round
    emerald:  'rgb(140, 178, 152)', // offer / accepted
    rose:     'rgb(184, 145, 145)', // rejected
    stone:    'rgb(168, 160, 150)', // withdrew / ghosted / no-response
}

const STATUS_TONE: Record<string, keyof typeof TONE> = {
    'Applied': 'sky',
    'Online Assessment': 'indigo',
    'Phone Screen': 'indigo',
    'Interviewing: 1st round': 'amber',
    'Interviewing: 2nd round': 'amber',
    'Interviewing: 3rd round': 'amber',
    'Interviewing: 4th round': 'amber',
    'Interviewing: 5th round': 'amber',
    'Final Round': 'gold',
    'Offer': 'emerald',
    'Accepted': 'emerald',
    'Rejected': 'rose',
    'Withdrew': 'stone',
    'Ghosted': 'stone',
    'No Response': 'stone',
}

// Order determines column position — earlier stages first
const STAGE_ORDER: string[] = [
    'Applied',
    'Online Assessment',
    'Phone Screen',
    'No Response',
    'Interviewing: 1st round',
    'Interviewing: 2nd round',
    'Interviewing: 3rd round',
    'Interviewing: 4th round',
    'Interviewing: 5th round',
    'Final Round',
    'Rejected',
    'Withdrew',
    'Ghosted',
    'Offer',
    'Accepted',
]

function getColor(name: string): string {
    return TONE[STATUS_TONE[name] ?? 'slate']
}

function getNodeColumn(name: string, allNodes: Set<string>, data: { from: string; to: string }[]): number {
    // Build a depth map by BFS from "Applied"
    const adj = new Map<string, Set<string>>()
    for (const d of data) {
        if (!adj.has(d.from)) adj.set(d.from, new Set())
        adj.get(d.from)!.add(d.to)
    }
    
    const depth = new Map<string, number>()
    depth.set('Applied', 0)
    const queue = ['Applied']
    while (queue.length > 0) {
        const current = queue.shift()!
        const children = adj.get(current)
        if (children) {
            for (const child of children) {
                if (!depth.has(child)) {
                    depth.set(child, depth.get(current)! + 1)
                    queue.push(child)
                }
            }
        }
    }

    return depth.get(name) ?? 1
}

export function SankeyChart({ data }: SankeyChartProps) {
    const [hoveredLink, setHoveredLink] = useState<number | null>(null)

    const { nodePositions, links, svgWidth, svgHeight } = useMemo(() => {
        if (!data || data.length === 0) return { nodePositions: new Map(), links: [], svgWidth: 500, svgHeight: 300 }

        const nodeSet = new Set<string>()
        for (const d of data) {
            nodeSet.add(d.from)
            nodeSet.add(d.to)
        }

        // Assign columns by BFS depth from Applied
        const nodeColumns = new Map<string, number>()
        for (const n of nodeSet) {
            nodeColumns.set(n, getNodeColumn(n, nodeSet, data))
        }

        // Group by column
        const columns = new Map<number, string[]>()
        for (const [n, col] of nodeColumns) {
            if (!columns.has(col)) columns.set(col, [])
            columns.get(col)!.push(n)
        }

        // Sort columns by stage order for consistent vertical ordering
        for (const [, nodes] of columns) {
            nodes.sort((a, b) => {
                const ai = STAGE_ORDER.indexOf(a)
                const bi = STAGE_ORDER.indexOf(b)
                return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi)
            })
        }

        const numCols = Math.max(...columns.keys()) + 1
        const nodeW = 160
        const colGap = 60
        const padding = 14
        const minH = 28
        const maxH = 70

        // Throughput per node
        const nodeThroughput = new Map<string, number>()
        for (const d of data) {
            nodeThroughput.set(d.from, (nodeThroughput.get(d.from) || 0) + d.value)
            nodeThroughput.set(d.to, (nodeThroughput.get(d.to) || 0) + d.value)
        }
        const totalFlow = Math.max(...nodeThroughput.values(), 1)

        // Calculate chart height
        let maxColHeight = 0
        for (const [, colNodes] of columns) {
            let colH = 0
            for (const n of colNodes) {
                const t = nodeThroughput.get(n) || 1
                const h = Math.max(minH, Math.min(maxH, (Math.log(t + 1) / Math.log(totalFlow + 1)) * maxH * 1.5))
                colH += h + padding
            }
            maxColHeight = Math.max(maxColHeight, colH)
        }
        const chartH = Math.max(250, maxColHeight + 40)
        const chartW = numCols * (nodeW + colGap) + 40

        // Position nodes
        const nodePositions = new Map<string, { x: number; y: number; w: number; h: number; label: string; value: number }>()
        for (const [col, colNodes] of columns) {
            const x = col * (nodeW + colGap) + 20
            const totalH = colNodes.reduce((sum, n) => {
                const t = nodeThroughput.get(n) || 1
                return sum + Math.max(minH, Math.min(maxH, (Math.log(t + 1) / Math.log(totalFlow + 1)) * maxH * 1.5)) + padding
            }, -padding)

            let y = (chartH - totalH) / 2
            for (const n of colNodes) {
                const t = nodeThroughput.get(n) || 1
                const h = Math.max(minH, Math.min(maxH, (Math.log(t + 1) / Math.log(totalFlow + 1)) * maxH * 1.5))
                nodePositions.set(n, { x, y, w: nodeW, h, label: n, value: t })
                y += h + padding
            }
        }

        // Allocate slots for links
        const totalOut = new Map<string, number>()
        const totalIn = new Map<string, number>()
        for (const d of data) {
            totalOut.set(d.from, (totalOut.get(d.from) || 0) + d.value)
            totalIn.set(d.to, (totalIn.get(d.to) || 0) + d.value)
        }

        const sourceSlots = new Map<string, number>()
        const targetSlots = new Map<string, number>()
        for (const n of nodeSet) {
            sourceSlots.set(n, 0)
            targetSlots.set(n, 0)
        }

        const sortedData = [...data].sort((a, b) => b.value - a.value)

        const links = sortedData.map((d) => {
            const src = nodePositions.get(d.from)
            const tgt = nodePositions.get(d.to)
            if (!src || !tgt) return null

            const srcTotal = totalOut.get(d.from) || 1
            const tgtTotal = totalIn.get(d.to) || 1

            const srcUsed = sourceSlots.get(d.from) || 0
            const tgtUsed = targetSlots.get(d.to) || 0

            const srcFrac = d.value / srcTotal
            const tgtFrac = d.value / tgtTotal

            const thickness = Math.max(2, srcFrac * (src.h - 4))

            const srcY = src.y + 2 + (srcUsed / srcTotal) * (src.h - 4) + (srcFrac * (src.h - 4)) / 2
            const tgtY = tgt.y + 2 + (tgtUsed / tgtTotal) * (tgt.h - 4) + (tgtFrac * (tgt.h - 4)) / 2

            sourceSlots.set(d.from, srcUsed + d.value)
            targetSlots.set(d.to, tgtUsed + d.value)

            const srcX = src.x + src.w
            const tgtX = tgt.x
            const midX = (srcX + tgtX) / 2

            const path = `M ${srcX} ${srcY - thickness / 2}
                C ${midX} ${srcY - thickness / 2}, ${midX} ${tgtY - thickness / 2}, ${tgtX} ${tgtY - thickness / 2}
                L ${tgtX} ${tgtY + thickness / 2}
                C ${midX} ${tgtY + thickness / 2}, ${midX} ${srcY + thickness / 2}, ${srcX} ${srcY + thickness / 2}
                Z`

            return { path, color: getColor(d.to), value: d.value, from: d.from, to: d.to }
        }).filter(Boolean) as { path: string; color: string; value: number; from: string; to: string }[]

        return { nodePositions, links, svgWidth: chartW, svgHeight: chartH }
    }, [data])

    if (!data || data.length === 0) {
        return <div className="flex items-center justify-center h-[240px] text-muted-foreground text-sm">No status flow data</div>
    }

    return (
        <div className="w-full overflow-x-auto">
            <svg width="100%" height={svgHeight} viewBox={`0 0 ${svgWidth} ${svgHeight}`} preserveAspectRatio="xMidYMid meet">
                {/* Links */}
                {links.map((link, i) => (
                    <path
                        key={i}
                        d={link.path}
                        fill={link.color}
                        opacity={hoveredLink === i ? 0.45 : 0.14}
                        style={{ cursor: 'pointer', transition: 'opacity 0.15s' }}
                        onMouseEnter={() => setHoveredLink(i)}
                        onMouseLeave={() => setHoveredLink(null)}
                    >
                        <title>{`${link.from} → ${link.to}: ${link.value}`}</title>
                    </path>
                ))}

                {/* Nodes */}
                {Array.from(nodePositions.entries()).map(([name, pos]) => {
                    const color = getColor(name)
                    const SHORT_NAMES: Record<string, string> = {
                        'Interviewing: 1st round': 'Interview: 1st',
                        'Interviewing: 2nd round': 'Interview: 2nd',
                        'Interviewing: 3rd round': 'Interview: 3rd',
                        'Interviewing: 4th round': 'Interview: 4th',
                        'Interviewing: 5th round': 'Interview: 5th',
                    }
                    const shortName = SHORT_NAMES[name] || name
                    return (
                        <g key={name}>
                            <rect
                                x={pos.x}
                                y={pos.y}
                                width={pos.w}
                                height={pos.h}
                                rx={3}
                                fill={color}
                                fillOpacity={0.18}
                                stroke={color}
                                strokeOpacity={0.7}
                                strokeWidth={1}
                            >
                                <title>{name}: {pos.value}</title>
                            </rect>
                            <text
                                x={pos.x + 10}
                                y={pos.y + pos.h / 2}
                                dominantBaseline="central"
                                fill="rgba(226, 232, 240, 0.85)"
                                fontSize={11}
                                fontWeight={400}
                                letterSpacing={0.2}
                            >
                                {shortName}
                            </text>
                            <text
                                x={pos.x + pos.w - 10}
                                y={pos.y + pos.h / 2}
                                textAnchor="end"
                                dominantBaseline="central"
                                fill="rgba(148, 163, 184, 0.7)"
                                fontSize={10}
                                fontWeight={400}
                                fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
                            >
                                {pos.value}
                            </text>
                        </g>
                    )
                })}

                {/* Hovered link label */}
                {hoveredLink !== null && links[hoveredLink] && (
                    <text
                        x={svgWidth / 2}
                        y={svgHeight - 4}
                        textAnchor="middle"
                        fill="rgba(148, 163, 184, 0.7)"
                        fontSize={10}
                        fontWeight={400}
                        letterSpacing={0.3}
                    >
                        {links[hoveredLink].from} → {links[hoveredLink].to} · {links[hoveredLink].value}
                    </text>
                )}
            </svg>
        </div>
    )
}
