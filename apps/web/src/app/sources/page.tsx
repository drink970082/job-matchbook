import { getWatchedCompanies } from '@/lib/watchlist-actions'
import { AppShell } from '@/components/AppShell'
import { SourcesTab } from '@/components/SourcesTab'

export const dynamic = 'force-dynamic'

export default async function SourcesPage() {
    const { data: sources } = await getWatchedCompanies()
    return (
        <AppShell active="/sources">
            <SourcesTab sources={sources} />
        </AppShell>
    )
}
