'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { QuotaBar } from './QuotaBar'
import type { ActivityItem, getActivityStatus } from '@/lib/activity-actions'

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
    const stale = !status.lastFetchedAt || Date.now() - Date.parse(status.lastFetchedAt) > 86_400_000

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
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
                        <Stat label="Last new posting" value={status.lastFetchedAt ? ago(status.lastFetchedAt) : 'never'} warn={stale} />
                        <Stat label="New postings, 24h" value={String(status.new24h)} />
                        <Stat label="New postings, 7d" value={String(status.new7d)} />
                        <Stat label="Triage assessed, 24h" value={String(status.assessed24h)} />
                        <Stat label="Triage cost, 7d" value={`USD ${status.spend7dUsd.toFixed(status.spend7dUsd < 0.01 ? 4 : 2)}`} />
                        <Stat label="Triage failures, 24h" value={String(status.failures24h)} warn={status.failures24h > 0} />
                    </div>
                    {stale && (
                        <p className="text-xs text-amber-600">No new posting in over a day: the worker may be stopped.</p>
                    )}
                    <QuotaBar />
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
