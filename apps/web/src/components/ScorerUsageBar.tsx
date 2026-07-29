'use client'

import { useEffect, useState } from 'react'

// Fit-backend quota usage bar, fed by /api/scorer-usage (the snapshot the worker
// captures once per scoring pass from the provider's own usage endpoint). Reflects the
// LAST pass — a budget indicator, not a live meter. Polls the local route while
// mounted (free — reads a local file, never calls a provider). The snapshot names the
// backend it describes, so switching SCORE_BACKEND relabels the bar on the next pass
// rather than silently showing the other provider's numbers. See docs/SPEC.md §7.2.

export interface UsageLimit {
    key: string
    used_percent: number
    window_minutes: number | null
    resets_at: number | null // epoch seconds
}
export interface Usage {
    backend: string | null
    plan_type: string | null
    limits: UsageLimit[]
    as_of: string | null // ISO
}

// Which budget the numbers describe. `claude` reads the Claude Code SUBSCRIPTION quota,
// which is a different budget from the metered API key the claude scorer bills — the
// label has to say so rather than just "Claude". A null/unknown backend predates the
// backend field (or is a hand-written file); call it what it is.
const BACKEND_LABELS: Record<string, string> = { codex: 'Codex', claude: 'Claude Code' }
export function backendLabel(backend: string | null): string {
    return (backend && BACKEND_LABELS[backend]) || 'Scorer'
}

// codex reports window_minutes, not a name — map the common ones to a friendly label.
// Claude can return TWO rows in the same window (`weekly_all` 72% beside a
// model-scoped `weekly_scoped (Fable)` 2%), so a bare "weekly" on both would read as a
// contradiction; the worker parks the model name in the key's parenthetical and it is
// carried through here.
export function windowLabel(l: Pick<UsageLimit, 'window_minutes' | 'key'>): string {
    const base =
        l.window_minutes === 10080 ? 'weekly'
        : l.window_minutes === 300 ? '5h'
        : l.window_minutes ? `${l.window_minutes}m`
        : 'usage'
    const scope = /\(([^)]+)\)\s*$/.exec(l.key ?? '')
    return scope ? `${base} · ${scope[1]}` : base
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

export function ScorerUsageBar({ pollMs = 60000 }: { pollMs?: number }) {
    const [usage, setUsage] = useState<Usage | null>(null)

    useEffect(() => {
        let alive = true
        const load = () => {
            // try/catch guards a missing `fetch` (SSR / test env) — that throws
            // synchronously, before the promise chain's .catch can see it.
            try {
                fetch('/api/scorer-usage')
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
        return <div className="text-xs text-muted-foreground">No scorer usage recorded yet.</div>
    }

    const asOf = usage.as_of ? new Date(usage.as_of).toLocaleString() : ''
    const who = backendLabel(usage.backend)
    return (
        <div className="space-y-2 mb-4">
            {usage.limits.map((l) => {
                const pct = Math.min(100, Math.max(0, l.used_percent))
                return (
                    <div key={l.key} className="space-y-1">
                        <div className="flex justify-between text-xs text-muted-foreground">
                            <span>{who}{usage.plan_type ? ` (${usage.plan_type})` : ''} · {windowLabel(l)}</span>
                            <span>{pct.toFixed(0)}%{formatResetsIn(l.resets_at) ? ` · ${formatResetsIn(l.resets_at)}` : ''}</span>
                        </div>
                        <div className="h-2 w-full rounded bg-muted overflow-hidden">
                            <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
                        </div>
                    </div>
                )
            })}
            {usage.backend === 'claude' && (
                // Say it plainly rather than let the bar imply it. `make_claude_scorer`
                // bills ANTHROPIC_API_KEY (metered, no percent-of-quota endpoint exists);
                // what this meter reads is the Claude Code SUBSCRIPTION. Both are real
                // numbers — they are just not the same budget, and a bare percentage
                // sitting where the codex weekly budget used to be would read as one.
                <div className="text-[10px] text-muted-foreground">
                    Claude Code subscription quota — scoring bills ANTHROPIC_API_KEY
                    separately (metered, not metered here).
                </div>
            )}
            {asOf && <div className="text-[10px] text-muted-foreground">as of {asOf}</div>}
        </div>
    )
}
