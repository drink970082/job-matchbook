'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { QuotaBar } from './QuotaBar'
import type { ActivityItem, getActivityStatus } from '@/lib/activity-actions'
import { reasonText, STAGE_LABEL, type FunnelWindow } from '@/lib/intake-funnel'
import { describePass } from '@/lib/pass-record'

export type ActivityStatus = Awaited<ReturnType<typeof getActivityStatus>>

// "3h ago" for an ISO time or a YYYY-MM-DD date.
export function ago(at: string | null, now = Date.now()): string {
    const t = at ? Date.parse(at) : NaN
    if (Number.isNaN(t)) return at ?? ''
    const m = Math.max(0, Math.floor((now - t) / 60_000))
    return m < 60 ? `${m}m ago` : m < 1440 ? `${Math.floor(m / 60)}h ago` : `${Math.floor(m / 1440)}d ago`
}

function Stat({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
    return (
        <div className="rounded-md border px-3 py-2">
            <div className="text-xs text-muted-foreground">{label}</div>
            {/* Relative times use the clock; the server and browser render a moment apart. */}
            <div className={`text-sm font-medium ${warn ? 'text-amber-600' : ''}`} suppressHydrationWarning>{value}</div>
        </div>
    )
}

// One window of the intake funnel (#248): what came in, what each stage removed, what is left.
export function Funnel({ title, window: w }: { title: string; window: FunnelWindow }) {
    const count = (v: number) => v.toLocaleString('en-US')
    return (
        <table className="w-full text-sm">
            <caption className="pb-1 text-left font-medium">{title}</caption>
            <tbody>
                <tr><th scope="row" className="text-left font-normal">Listings seen</th><td className="text-right">{count(w.stages[0].input)}</td></tr>
                {w.stages.map((s) => (
                    <tr key={s.stage} className={s.reasons.unaccounted ? 'text-amber-600' : 'text-muted-foreground'}>
                        <th scope="row" className="text-left font-normal">
                            {STAGE_LABEL[s.stage]}
                            {reasonText(s) && <span className="block text-xs">{reasonText(s)}</span>}
                        </th>
                        <td className="text-right align-top">{count(0 - s.removed)}</td>
                    </tr>
                ))}
                <tr><th scope="row" className="text-left font-medium">Open and eligible</th><td className="text-right font-medium">{count(w.open)}</td></tr>
            </tbody>
        </table>
    )
}

type Page = { items: ActivityItem[]; hasMore: boolean; nextOffset: number; capped: boolean }

interface Props {
    status: ActivityStatus
    initial: Page
    loadMore: (offset: number) => Promise<Page>
}

// Activity (#210): is the system running, what did it cost, and what changed.
export function ActivityTab({ status, initial, loadMore }: Props) {
    const [items, setItems] = useState(initial.items)
    const [hasMore, setHasMore] = useState(initial.hasMore)
    const [capped, setCapped] = useState(initial.capped)
    // The server's offset, not items.length: writes made while the page is open shift
    // the merge, and the dedupe below would otherwise stall Load more on the same page.
    const [offset, setOffset] = useState(initial.nextOffset)
    const [loading, setLoading] = useState(false)
    const pass = describePass(status.lastPass, Date.now(), status.lastFailure)

    const more = async () => {
        setLoading(true)
        try {
            const next = await loadMore(offset)
            setItems([...items, ...next.items.filter((n) => !items.some((i) => i.key === n.key))])
            setHasMore(next.hasMore)
            setCapped(next.capped)
            setOffset(next.nextOffset)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="space-y-6">
            <Card>
                <CardHeader className="pb-2"><CardTitle className="text-base">System status</CardTitle></CardHeader>
                <CardContent className="space-y-4">
                    {/* The latest pass record (#249): what it did and what it ran with. Settings shows the configured values. */}
                    <div className="space-y-1 text-sm">
                        <div className="flex flex-wrap items-baseline gap-2">
                            <span className="font-medium">Last pass</span>
                            {status.lastPass && (
                                <span className="text-muted-foreground" title={status.lastPass.startedAt} suppressHydrationWarning>
                                    {ago(status.lastPass.startedAt)}
                                </span>
                            )}
                            <span className={pass.problem ? 'text-amber-600' : ''} suppressHydrationWarning>{pass.state}</span>
                        </div>
                        {pass.problem && <p className="text-xs text-amber-600" suppressHydrationWarning>{pass.problem}</p>}
                        {pass.ranWith && <p className="text-xs text-muted-foreground">Ran with: {pass.ranWith}</p>}
                        {pass.lines.length > 0 && (
                            <ul className="space-y-0.5 text-xs">
                                {pass.lines.map((l) => (
                                    <li key={l.text} className={l.warn ? 'text-amber-600' : ''}>{l.text}</li>
                                ))}
                            </ul>
                        )}
                    </div>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
                        <Stat label="New postings, 24h" value={String(status.new24h)} />
                        <Stat label="New postings, 7d" value={String(status.new7d)} />
                        <Stat label="Triage assessed, 24h" value={String(status.assessed24h)} />
                        <Stat label="Triage cost, 7d" value={`USD ${status.spend7dUsd.toFixed(status.spend7dUsd < 0.01 ? 4 : 2)}`} />
                        <Stat label="Triage failures, 24h" value={String(status.failures24h)} warn={status.failures24h > 0} />
                        <Stat label="Aged out unevaluated" value={`${status.agedOut7d} in 7d, ${status.agedOutTotal} total`} />
                    </div>
                    <QuotaBar />
                </CardContent>
            </Card>
            <Card>
                <CardHeader className="pb-2"><CardTitle className="text-base">Intake funnel</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                    {!status.funnel.latest_pass ? <p className="text-sm text-muted-foreground">No pass has recorded its intake yet.</p> : (
                        <div className="grid gap-6 md:grid-cols-2">
                            <Funnel title="Latest pass" window={status.funnel.latest_pass} />
                            <Funnel title={`Last 7 days, passes: ${status.funnel.last_7_days.passes}`} window={status.funnel.last_7_days} />
                        </div>
                    )}
                    {status.funnel.last_7_days.passes_without_intake > 0 && (
                        <p className="text-xs text-amber-600">
                            Passes not counted, stopped before recording their intake: {status.funnel.last_7_days.passes_without_intake}
                        </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                        A stored listing counts again in every pass that lists it. A posting can fail several requirements.
                        Later stages are the stored verdicts now; keep/skip overrides are not applied.
                    </p>
                </CardContent>
            </Card>
            <Card>
                <CardHeader className="pb-2"><CardTitle className="text-base">Timeline</CardTitle></CardHeader>
                <CardContent>
                    {items.length === 0 ? <p className="text-sm text-muted-foreground">Nothing yet.</p> : (
                        <ul className="space-y-1.5 text-sm">
                            {items.map((i) => (
                                <li key={i.key} className="flex flex-wrap items-baseline gap-2">
                                    <span className="w-24 shrink-0 text-muted-foreground" title={i.at}>{i.at.slice(0, 10)}</span>
                                    <span>{i.text}</span>
                                    {i.actor === 'mcp' && <span className="text-xs font-medium">via MCP</span>}
                                </li>
                            ))}
                        </ul>
                    )}
                    {capped && <p className="mt-3 text-xs text-muted-foreground">Older activity is not shown here; MCP reads the full audit log.</p>}
                    {hasMore && (
                        <Button variant="outline" size="sm" className="mt-4" onClick={more} disabled={loading}>Load more</Button>
                    )}
                </CardContent>
            </Card>
        </div>
    )
}
