'use client'

import { useCallback, useRef, useState } from 'react'
import { clearTriageOverride, getJobPostings, markJobApplied, setTriageOverride } from '@/lib/job-actions'
import type { JobViewScope } from '@/lib/job-actions'
import { linkApplication } from '@/lib/link-actions'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DiscoveredJobsTable, type AppliedMatch, type JobTableFilters } from './DiscoveredJobsTable'
import { JobDetailModal } from './JobDetailModal'
import { ApplyCategoryDialog } from './ApplyCategoryDialog'
import { toast } from 'sonner'

// Page size for the Discovered Jobs table (must match the /jobs page's initial load,
// which calls getJobPostings with the action's default size).
const JOB_PAGE_SIZE = 25
const DEFAULT_JOB_FILTERS: JobTableFilters = { search: '', searchScope: 'metadata' }

interface JobsViewProps {
    initialJobPostings: any[]
    totalJobPostings: number
    categoryOptions: string[]
    mode: 'jev' | 'screen'
}

// The /jobs page: the Discovered Jobs table, JD modal and the Mark-applied flow.
export function JobsView({ initialJobPostings, totalJobPostings, categoryOptions, mode }: JobsViewProps) {
    const [jobPostings, setJobPostings] = useState<any[]>(initialJobPostings)
    const [totalJobs, setTotalJobs] = useState(totalJobPostings)
    const [jobsLoading, setJobsLoading] = useState(false)
    const [jobsError, setJobsError] = useState(false)
    const [jobFilters, setJobFilters] = useState<JobTableFilters>(DEFAULT_JOB_FILTERS)
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
            // The last row of a later page was hidden or applied: step back to the new last page.
            const last = Math.max(0, Math.ceil(total / JOB_PAGE_SIZE) - 1)
            if (data.length === 0 && page > last) {
                jobViewRef.current = { filters, page: last }
                setJobPage(last)
                return requestJobPostings(filters, last)
            }
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

    const finishApply = async (result: { success: boolean; error?: string }, done: string) => {
        if (result.success) {
            toast.success(done)
            setSelectedJob(null)
        } else {
            // E.g. the first JEV pass changed which postings are "for you" since this loaded.
            toast.error(result.error)
        }
        setApplyJob(null)
        await refreshJobPostings()
    }

    const handleConfirmApply = async (category: string, date: string, createNew: boolean) => {
        if (!applyJob) return
        const result = await markJobApplied(applyJob.id, category, applyJob.__viewScope, 'web', { date, createNew })
        // An application was recorded since this list loaded: offer linking it (#241).
        const match: AppliedMatch | undefined = 'match' in result ? result.match : undefined
        if (match) return setApplyJob({ ...applyJob, applied_match: match })
        await finishApply(result, 'Marked as applied')
    }

    const handleLinkApplied = async (applicationId: number) => {
        if (!applyJob) return
        await finishApply(await linkApplication(applicationId, applyJob.id), `Linked to application #${applicationId}`)
    }

    // Not interested (#207): a triage skip override, actor web, with Undo.
    // Undo restores the override that was there before (e.g. an MCP keep), else clears it.
    const hiding = useRef(new Set<number>())
    const handleNotInterested = async (id: number) => {
        if (hiding.current.has(id)) return
        hiding.current.add(id)
        const before = jobPostings.find((j: any) => j.id === id)?.jev?.override
        try {
            const result = await setTriageOverride(id, 'skip', 'Not interested (web)')
            if (!result.success) return toast.error(result.error)
            await refreshJobPostings()
        } finally {
            hiding.current.delete(id)
        }
        toast.success('Hidden: not interested', {
            action: { label: 'Undo', onClick: async () => {
                const undo = before
                    ? await setTriageOverride(id, before.decision, before.reason ?? undefined)
                    : await clearTriageOverride(id)
                if (!undo.success) return toast.error(undo.error)
                await refreshJobPostings()
            } },
        })
    }

    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="text-lg">Discovered Jobs</CardTitle>
                <p className="text-sm text-muted-foreground">
                    {mode === 'jev'
                        ? 'Postings triage marked keep. Triage assesses postings from the last 7 days only, so older ones are not listed.'
                        : 'Triage is not set up: showing postings that passed your hard requirements.'}
                </p>
            </CardHeader>
            <CardContent>
            <DiscoveredJobsTable
                data={jobPostings}
                total={totalJobs}
                page={jobPage}
                size={JOB_PAGE_SIZE}
                filters={jobFilters}
                loading={jobsLoading}
                loadError={jobsError}
                onPageChange={handleJobPageChange}
                onFilterChange={handleJobFilterChange}
                onMarkApplied={handleMarkApplied}
                onViewJD={handleViewJD}
                onNotInterested={handleNotInterested}
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
                match={applyJob?.applied_match}
                onConfirm={handleConfirmApply}
                onLink={handleLinkApplied}
                onClose={() => setApplyJob(null)}
            />
            </CardContent>
        </Card>
    )
}
