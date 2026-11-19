import { getJobPostings, getJobsMode } from '@/lib/job-actions'
import { getCategories } from '@/lib/category-actions'
import { AppShell } from '@/components/AppShell'
import { JobsView } from '@/components/JobsView'

export const dynamic = 'force-dynamic'

export default async function JobsPage() {
    const [{ data, total }, { categories }, mode] = await Promise.all([getJobPostings({}), getCategories(), getJobsMode()])
    return (
        <AppShell active="/jobs">
            <JobsView initialJobPostings={data} totalJobPostings={total} categoryOptions={categories} mode={mode} />
        </AppShell>
    )
}
