
import { getApplications } from '@/lib/application-actions'
import { getKPIs, getStatusFlow, getTimelineData, getCategoryData } from '@/lib/analytics-actions'
import { getJobPostings } from '@/lib/job-actions'
import { getCategories } from '@/lib/category-actions'
import { Dashboard } from '@/components/Dashboard'

export const dynamic = 'force-dynamic'

export default async function Page() {
  const [
    { data: apps, total },
    kpis,
    statusFlow,
    timelineData,
    categoryData,
    { data: jobPostings, total: totalJobPostings },
    { categories: categoryOptions, configured: categoriesConfigured },
  ] = await Promise.all([
    getApplications({ page: 0, size: 10 }),
    getKPIs(),
    getStatusFlow(),
    getTimelineData(),
    getCategoryData(),
    getJobPostings({}),
    getCategories(),
  ])

  return (
    <div className="container mx-auto py-10 px-4">
      <Dashboard
        initialApps={apps}
        initialKpis={kpis}
        totalApps={total}
        initialStatusFlow={statusFlow.data || []}
        initialTimeline={timelineData.data || []}
        initialCategories={categoryData.data || []}
        initialJobPostings={jobPostings}
        totalJobPostings={totalJobPostings}
        initialCategoryOptions={categoryOptions}
        initialCategoriesConfigured={categoriesConfigured}
      />
    </div>
  )
}
