
'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { WatchlistTable, type WatchedCompany } from './WatchlistTable'
import { PromotionSuggestions } from './PromotionSuggestions'
import type { PromotionSuggestion } from '@/lib/promotion-actions'

interface WatchlistTabProps {
    promotions: PromotionSuggestion[]
    watchlist: WatchedCompany[]
    onApprove: (c: { source: string; slug: string; name: string }) => void
    onDismiss: (source: string, slug: string) => void
    onAdd: (c: { source: string; slug: string; name: string; recipe?: string }) => void
    onRemove: (id: number) => void
}

export function WatchlistTab({
    promotions,
    watchlist,
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
        </div>
    )
}
