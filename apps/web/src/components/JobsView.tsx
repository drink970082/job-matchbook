'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { getJobPostings, getJobStageCounts, markJobApplied } from '@/lib/job-actions'
import type { JobViewScope } from '@/lib/job-actions'
import { DiscoveredJobsTab } from './DiscoveredJobsTab'
import type { JobTableFilters } from './DiscoveredJobsTable'
import { JobDetailModal } from './JobDetailModal'
import { ApplyCategoryDialog } from './ApplyCategoryDialog'
import { toast } from 'sonner'

// Page size for the Discovered Jobs table (must match the /jobs page's initial load,
// which calls getJobPostings with the action's default size).
const JOB_PAGE_SIZE = 25
const DEFAULT_JOB_FILTERS: JobTableFilters = {
    stage: 'keep',
    search: '',
    searchScope: 'metadata',
    sort: 'created',
}

interface JobsViewProps {
    initialJobPostings: any[]
    totalJobPostings: number
    categoryOptions: string[]
}

// The /jobs page: the Discovered Jobs table, JD modal and the Mark-applied flow.
export function JobsView({ initialJobPostings, totalJobPostings, categoryOptions }: JobsViewProps) {
    const [jobPostings, setJobPostings] = useState<any[]>(initialJobPostings)
    const [totalJobs, setTotalJobs] = useState(totalJobPostings)
    const [jobsLoading, setJobsLoading] = useState(false)
    const [jobsError, setJobsError] = useState(false)
    const [jobFilters, setJobFilters] = useState<JobTableFilters>(DEFAULT_JOB_FILTERS)
    const [jobCounts, setJobCounts] = useState<Record<string, number> | undefined>(undefined)
    const [jobPage, setJobPage] = useState(0)
    const [selectedJob, setSelectedJob] = useState<any>(null)
    const [isJobDetailOpen, setIsJobDetailOpen] = useState(false)
    const [applyJob, setApplyJob] = useState<any>(null)
    const jobRequestVersion = useRef(0)
    const jobViewRef = useRef({ filters: DEFAULT_JOB_FILTERS, page: 0 })

    const requestJobPostings = useCallback(async (filters: JobTableFilters, page: number) => {
        const version = ++jobRequestVersion.current
        setJobsLoading(true)
        setJobsError(false)
        setJobPostings([])
        setTotalJobs(0)
        try {
            const { data, total } = await getJobPostings({ ...filters, page, size: JOB_PAGE_SIZE })
            if (version !== jobRequestVersion.current) return
            setJobPostings(data)
            setTotalJobs(total)
            setJobsLoading(false)
        } catch {
            if (version === jobRequestVersion.current) {
                setJobPostings([])
                setTotalJobs(0)
                setJobsError(true)
                setJobsLoading(false)
                toast.error('Could not load jobs')
            }
        }
    }, [])

    const refreshJobPostings = async (filters?: JobTableFilters, page?: number) => {
        const current = jobViewRef.current
        await requestJobPostings(filters ?? current.filters, page ?? current.page)
    }

    useEffect(() => {
        getJobStageCounts().then(setJobCounts).catch(() => {})
    }, [])

    const handleJobFilterChange = useCallback((newFilters: JobTableFilters) => {
        jobViewRef.current = { filters: newFilters, page: 0 }
        setJobFilters(newFilters)
        setJobPage(0)
        void requestJobPostings(newFilters, 0)
    }, [requestJobPostings])

    const handleJobPageChange = (newPage: number) => {
        jobViewRef.current = { filters: jobViewRef.current.filters, page: newPage }
        setJobPage(newPage)
        void requestJobPostings(jobViewRef.current.filters, newPage)
    }

    const handleViewJD = (id: number, scope: JobViewScope = jobFilters) => {
        const job = jobPostings.find((j: any) => j.id === id)
        if (job) {
            setSelectedJob({ ...job, __viewScope: scope })
            setIsJobDetailOpen(true)
        }
    }

    // Mark Applied now opens a dialog to pick the application category (instead of
    // always defaulting to 'Others'). The actual apply happens on confirm.
    const handleMarkApplied = (id: number, scope?: JobViewScope) => {
        const job = jobPostings.find((j: any) => j.id === id) || { id }
        setApplyJob({ ...job, __viewScope: scope ?? selectedJob?.__viewScope ?? jobFilters })
        setIsJobDetailOpen(false)
    }

    const handleConfirmApply = async (category: string) => {
        if (!applyJob) return
        const result = await markJobApplied(applyJob.id, category, applyJob.__viewScope)
        if (result.success) {
            toast.success('Marked as applied')
            getJobStageCounts().then(setJobCounts).catch(() => {})
            setApplyJob(null)
            setSelectedJob(null)
            await refreshJobPostings()
        } else {
            toast.error(result.error)
        }
    }

    return (
        <div className="space-y-6">
            <DiscoveredJobsTab
                data={jobPostings}
                total={totalJobs}
                page={jobPage}
                size={JOB_PAGE_SIZE}
                filters={jobFilters}
                loading={jobsLoading}
                loadError={jobsError}
                onPageChange={handleJobPageChange}
                onFilterChange={handleJobFilterChange}
                counts={jobCounts}
                onMarkApplied={handleMarkApplied}
                onViewJD={handleViewJD}
            />

            {selectedJob && (
                <JobDetailModal
                    isOpen={isJobDetailOpen}
                    onClose={() => {
                        setIsJobDetailOpen(false)
                        setSelectedJob(null)
                    }}
                    job={selectedJob}
                    onMarkApplied={handleMarkApplied}
                />
            )}

            <ApplyCategoryDialog
                open={!!applyJob}
                categories={categoryOptions}
                companyName={applyJob?.company_name}
                jobTitle={applyJob?.job_title}
                onConfirm={handleConfirmApply}
                onClose={() => setApplyJob(null)}
            />
        </div>
    )
}
