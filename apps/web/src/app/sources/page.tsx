import { getWatchedCompanies } from '@/lib/watchlist-actions'
import { getUnresolvedFeeds } from '@/lib/unresolved-actions'
import { AppShell } from '@/components/AppShell'
import { SourcesTab } from '@/components/SourcesTab'

export const dynamic = 'force-dynamic'

export default async function SourcesPage() {
    const [{ data: sources }, { data: unresolved }] = await Promise.all([getWatchedCompanies(), getUnresolvedFeeds()])
    return (
        <AppShell active="/sources">
            <SourcesTab sources={sources} unresolved={unresolved} />
        </AppShell>
    )
}
