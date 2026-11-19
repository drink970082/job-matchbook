import { getApplications } from '@/lib/application-actions'
import { getKPIs, getStatusFlow, getTimelineData, getCategoryData } from '@/lib/analytics-actions'
import { getCategories } from '@/lib/category-actions'
import { AppShell } from '@/components/AppShell'
import { ApplicationsView } from '@/components/ApplicationsView'

export const dynamic = 'force-dynamic'

export default async function ApplicationsPage() {
    const [{ data: apps, total }, kpis, statusFlow, timeline, categoryData, { categories }] = await Promise.all([
        getApplications({ page: 0, size: 10 }),
        getKPIs(),
        getStatusFlow(),
        getTimelineData(),
        getCategoryData(),
        getCategories(),
    ])
    return (
        <AppShell active="/applications">
            <ApplicationsView
                initialApps={apps}
                initialKpis={kpis}
                totalApps={total}
                initialStatusFlow={statusFlow.data || []}
                initialTimeline={timeline.data || []}
                initialCategories={categoryData.data || []}
                categoryOptions={categories}
            />
        </AppShell>
    )
}
