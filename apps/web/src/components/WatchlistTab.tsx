
'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { WatchlistTable, type WatchedCompany } from './WatchlistTable'
import { PromotionSuggestions } from './PromotionSuggestions'
import { Button } from '@/components/ui/button'
import type { PromotionSuggestion } from '@/lib/promotion-actions'

export interface WatchlistActivityItem {
    id: number
    at: string
    actor: string
    action: string
    payload: { source: string; slug: string; name: string; recipe: string | null }
}

interface WatchlistTabProps {
    promotions: PromotionSuggestion[]
    watchlist: WatchedCompany[]
    activity?: WatchlistActivityItem[]
    onApprove: (c: { source: string; slug: string; name: string }) => void
    onDismiss: (source: string, slug: string) => void
    onAdd: (c: { source: string; slug: string; name: string; recipe?: string }) => void
    onRemove: (id: number) => void
}

export function WatchlistTab({
    promotions,
    watchlist,
    activity = [],
    onApprove,
    onDismiss,
    onAdd,
    onRemove,
}: WatchlistTabProps) {
    return (
        <div className="space-y-6">
            {promotions.length > 0 && (
                <Card>
                    <CardHeader className="pb-3">
                        <CardTitle className="text-lg">Suggested companies</CardTitle>
                        <p className="text-sm text-muted-foreground">
                            Non-watchlisted companies whose feed-discovered roles keep
                            scoring well or getting applied to. Approve to track them in
                            full, or dismiss.
                        </p>
                    </CardHeader>
                    <CardContent>
                        <PromotionSuggestions
                            data={promotions}
                            onApprove={onApprove}
                            onDismiss={onDismiss}
                        />
                    </CardContent>
                </Card>
            )}
            <Card>
                <CardHeader className="pb-3">
                    <CardTitle className="text-lg">Watchlist</CardTitle>
                    <p className="text-sm text-muted-foreground">
                        Companies the worker fetches in full each run. Seeded once from
                        the worker config; manage it here.
                    </p>
                </CardHeader>
                <CardContent>
                    <WatchlistTable
                        data={watchlist}
                        onAdd={onAdd}
                        onRemove={onRemove}
                    />
                </CardContent>
            </Card>
            {activity.length > 0 && (
                <Card>
                    <CardHeader className="pb-3">
                        <CardTitle className="text-lg">Recent watchlist changes</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <ul className="space-y-2 text-sm">
                            {activity.map((a) => {
                                const p = a.payload
                                const watched = watchlist.some((w) => w.source === p.source && w.slug === p.slug)
                                return (
                                    <li key={a.id} className="flex items-center gap-2">
                                        <span className="text-muted-foreground">{a.at.slice(0, 10)}</span>
                                        <span>{a.action === 'remove' ? 'Removed' : 'Added'} {p.name} ({p.source}/{p.slug})</span>
                                        {a.actor === 'mcp' && <span className="text-xs text-muted-foreground">via MCP</span>}
                                        {a.action === 'remove' && !watched && (
                                            <Button size="sm" variant="outline" onClick={() => onAdd({
                                                source: p.source, slug: p.slug, name: p.name,
                                                ...(p.recipe ? { recipe: p.recipe } : {}),
                                            })}>Re-add</Button>
                                        )}
                                    </li>
                                )
                            })}
                        </ul>
                    </CardContent>
                </Card>
            )}
        </div>
    )
}
