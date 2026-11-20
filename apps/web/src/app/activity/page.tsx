import { getActivityStatus, getActivityTimeline } from '@/lib/activity-actions'
import { AppShell } from '@/components/AppShell'
import { ActivityTab } from '@/components/ActivityTab'

export const dynamic = 'force-dynamic'

export default async function ActivityPage() {
    const [status, initial] = await Promise.all([getActivityStatus(), getActivityTimeline()])
    return (
        <AppShell active="/activity">
            <ActivityTab status={status} initial={initial} loadMore={getActivityTimeline} />
        </AppShell>
    )
}
