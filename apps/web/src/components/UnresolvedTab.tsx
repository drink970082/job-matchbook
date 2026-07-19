
'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { UnresolvedFeedsTable } from './UnresolvedFeedsTable'
import type { UnresolvedFeedGroup } from '@/lib/unresolved-actions'

interface UnresolvedTabProps {
    data: UnresolvedFeedGroup[]
}

export function UnresolvedTab({ data }: UnresolvedTabProps) {
    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="text-lg">Unresolved feed listings</CardTitle>
                <p className="text-sm text-muted-foreground">
                    Feed listings whose apply URL couldn&apos;t be mapped to a supported
                    board — the backlog for expanding feed coverage.
                </p>
            </CardHeader>
            <CardContent>
                <UnresolvedFeedsTable data={data} />
            </CardContent>
        </Card>
    )
}
