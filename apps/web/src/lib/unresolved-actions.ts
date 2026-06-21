'use server'

import { prisma } from '@/lib/db'

export interface UnresolvedFeedGroup {
    host: string
    reason: string
    count: number
}

/**
 * Read-only backlog viewer for the `feed_unresolved` table: feed listings whose
 * apply URL the resolver couldn't map to a supported board. Groups by (host,
 * reason) with a count, sorted by count descending.
 *
 * groupBy's `orderBy: { _count: ... }` is finicky on SQLite, so we sort in JS.
 */
export async function getUnresolvedFeeds(): Promise<{
    data: UnresolvedFeedGroup[]
    total: number
}> {
    const rows = await prisma.feed_unresolved.groupBy({
        by: ['host', 'reason'],
        _count: { _all: true },
    })

    const data: UnresolvedFeedGroup[] = rows
        .map((row) => ({
            host: row.host,
            reason: row.reason,
            count: row._count._all,
        }))
        .sort((a, b) => b.count - a.count)

    const total = data.reduce((sum, row) => sum + row.count, 0)

    return { data, total }
}
