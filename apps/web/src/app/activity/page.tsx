import { getRecentActivity } from '@/lib/activity-actions'
import { AppShell } from '@/components/AppShell'
import { ActivityTab } from '@/components/ActivityTab'

export const dynamic = 'force-dynamic'

export default async function ActivityPage() {
    return (
        <AppShell active="/activity">
            <ActivityTab activity={await getRecentActivity()} />
        </AppShell>
    )
}
