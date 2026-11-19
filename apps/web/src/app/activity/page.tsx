import { getRecentActivity } from '@/lib/activity-actions'
import { AppShell } from '@/components/AppShell'
import { ActivityTab } from '@/components/ActivityTab'
import { QuotaBar } from '@/components/QuotaBar'

export const dynamic = 'force-dynamic'

export default async function ActivityPage() {
    return (
        <AppShell active="/activity">
            {/* Moved from Discovered Jobs (#207); #210 builds the status strip around it. */}
            <div className="mb-6"><QuotaBar /></div>
            <ActivityTab activity={await getRecentActivity()} />
        </AppShell>
    )
}
