'use client'

import { useEffect, useState } from 'react'

// Codex quota usage bar, fed by /api/codex-usage (the snapshot the worker captures
// off each scoring call). Reflects the LAST scoring call — a budget indicator, not a
// live meter: a fresh reading would cost a codex message. Polls the local route while
// mounted (free — reads a local file, never calls codex). See docs/SPEC.md §7.2.

export interface UsageLimit {
    key: string
    used_percent: number
    window_minutes: number | null
    resets_at: number | null // epoch seconds
}
export interface Usage {
    plan_type: string | null
    limits: UsageLimit[]
    as_of: string | null // ISO
}

// codex reports window_minutes, not a name — map the common ones to a friendly label.
export function windowLabel(l: Pick<UsageLimit, 'window_minutes'>): string {
    if (l.window_minutes === 10080) return 'weekly'
    if (l.window_minutes === 300) return '5h'
    if (l.window_minutes) return `${l.window_minutes}m`
    return 'usage'
}

// `nowSec` is injectable so the formatting is deterministically testable.
export function formatResetsIn(resetsAt: number | null, nowSec = Date.now() / 1000): string {
    if (!resetsAt) return ''
    const secs = resetsAt - nowSec
    if (secs <= 0) return 'resetting'
    const d = Math.floor(secs / 86400)
    const h = Math.floor((secs % 86400) / 3600)
    return d > 0 ? `resets in ${d}d ${h}h` : `resets in ${h}h`
}

export function CodexUsageBar({ pollMs = 60000 }: { pollMs?: number }) {
    const [usage, setUsage] = useState<Usage | null>(null)

    useEffect(() => {
        let alive = true
        const load = () => {
            // try/catch guards a missing `fetch` (SSR / test env) — that throws
            // synchronously, before the promise chain's .catch can see it.
            try {
                fetch('/api/codex-usage')
                    .then((r) => r.json())
                    .then((d: Usage) => { if (alive) setUsage(d) })
                    .catch(() => { /* transient: keep the last-good snapshot */ })
            } catch { /* no fetch available — stay in the empty state */ }
        }
        load()
        const t = setInterval(load, pollMs)
        return () => { alive = false; clearInterval(t) }
    }, [pollMs])

    if (!usage || usage.limits.length === 0) {
        return <div className="text-xs text-muted-foreground">No codex usage recorded yet.</div>
    }

    const asOf = usage.as_of ? new Date(usage.as_of).toLocaleString() : ''
    return (
        <div className="space-y-2 mb-4">
            {usage.limits.map((l) => {
                const pct = Math.min(100, Math.max(0, l.used_percent))
                return (
                    <div key={l.key} className="space-y-1">
                        <div className="flex justify-between text-xs text-muted-foreground">
                            <span>Codex{usage.plan_type ? ` (${usage.plan_type})` : ''} · {windowLabel(l)}</span>
                            <span>{pct.toFixed(0)}%{formatResetsIn(l.resets_at) ? ` · ${formatResetsIn(l.resets_at)}` : ''}</span>
                        </div>
                        <div className="h-2 w-full rounded bg-muted overflow-hidden">
                            <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
                        </div>
                    </div>
                )
            })}
            {asOf && <div className="text-[10px] text-muted-foreground">as of {asOf}</div>}
        </div>
    )
}
