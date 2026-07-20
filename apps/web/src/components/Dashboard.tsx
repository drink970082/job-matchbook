
'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
    getApplications,
    addApplication,
    updateApplicationStatus,
    deleteApplication,
    getApplicationHistory,
    getKPIs,
    deleteHistoryItem,
    getStatusFlow,
    getTimelineData,
    getCategoryData,
    updateApplicationDetails,
    exportApplicationsCSV,
    importApplicationsCSV,
    getJobPostings,
    markJobApplied,
    discardJobPosting,
    reopenJobPosting,
    bulkRemove,
    bulkReopen,
    removeAllInView,
    getWatchedCompanies,
    addWatchedCompany,
    removeWatchedCompany,
} from '@/lib/actions'
import { getPromotionSuggestions, dismissPromotion } from '@/lib/promotion-actions'
import { getUnresolvedFeeds } from '@/lib/unresolved-actions'
import { ApplicationsTab } from './ApplicationsTab'
import { DiscoveredJobsTab } from './DiscoveredJobsTab'
import { WatchlistTab } from './WatchlistTab'
import { UnresolvedTab } from './UnresolvedTab'
import { JobDetailModal } from './JobDetailModal'
import { ApplyCategoryDialog } from './ApplyCategoryDialog'
import { KPIGrid } from './KPIGrid'
import { StatusHistoryModal } from './StatusHistoryModal'
import { Button } from '@/components/ui/button'
import { Download, Upload } from 'lucide-react'
import { toast } from 'sonner'

// Page size for the Discovered Jobs table (must match page.tsx's initial load,
// which calls getJobPostings with the action's default size).
const JOB_PAGE_SIZE = 25

interface DashboardProps {
    initialApps: any[]
    initialKpis: any
    totalApps: number
    initialStatusFlow: any[]
    initialTimeline: any[]
    initialCategories: any[]
    initialJobPostings?: any[]
    totalJobPostings?: number
}

export function Dashboard({
    initialApps,
    initialKpis,
    totalApps,
    initialStatusFlow,
    initialTimeline,
    initialCategories,
    initialJobPostings = [],
    totalJobPostings = 0,
}: DashboardProps) {
    const [activeTab, setActiveTab] = useState<'applications' | 'discovered' | 'watchlist' | 'unresolved'>('applications')

    // Watchlist + promotion-suggestion + unresolved-feed state (loaded client-side)
    const [watchlist, setWatchlist] = useState<any[]>([])
    const [promotions, setPromotions] = useState<any[]>([])
    const [unresolved, setUnresolved] = useState<any[]>([])

    // Discovered Jobs state
    const [jobPostings, setJobPostings] = useState<any[]>(initialJobPostings)
    const [totalJobs, setTotalJobs] = useState(totalJobPostings)
    const [jobFilters, setJobFilters] = useState<any>({})
    const [jobPage, setJobPage] = useState(0)
    const [selectedJob, setSelectedJob] = useState<any>(null)
    const [isJobDetailOpen, setIsJobDetailOpen] = useState(false)
    const [applyJob, setApplyJob] = useState<any>(null)
    const [apps, setApps] = useState(initialApps)
    const [kpis, setKpis] = useState(initialKpis)
    const [total, setTotal] = useState(totalApps)
    const [page, setPage] = useState(0)
    const [filters, setFilters] = useState({})

    const [statusFlow, setStatusFlow] = useState(initialStatusFlow)
    const [timeline, setTimeline] = useState(initialTimeline)
    const [categories, setCategories] = useState(initialCategories)

    const [selectedApp, setSelectedApp] = useState<any>(null)
    const [historyData, setHistoryData] = useState<any[]>([])
    const [isHistoryOpen, setIsHistoryOpen] = useState(false)
    const fileInputRef = useRef<HTMLInputElement>(null)

    // Light tier: apps + KPIs + status flow only. A status edit can't move
    // date_applied or category, so re-fetching the timeline/category charts on
    // a status-only mutation would be pure waste — use this from handlers that
    // only touch status/history.
    const refreshStatusData = async () => {
        const { data, total } = await getApplications({ page, size: 10, ...filters })
        setApps(data)
        setTotal(total)

        const newKpis = await getKPIs()
        setKpis(newKpis)

        const flowRes = await getStatusFlow()
        if (flowRes.data) setStatusFlow(flowRes.data)
    }

    // Full tier: the light core plus the timeline/category charts. Use this
    // from handlers that can change date_applied, category, or row count.
    const refreshData = async () => {
        await refreshStatusData()

        const [timeRes, catRes] = await Promise.all([
            getTimelineData(),
            getCategoryData(),
        ])
        if (timeRes.data) setTimeline(timeRes.data)
        if (catRes.data) setCategories(catRes.data)
    }

    const handleFilterChange = useCallback(async (newFilters: any) => {
        setFilters(newFilters)
        setPage(0)
        const { data, total } = await getApplications({ page: 0, size: 10, ...newFilters })
        setApps(data)
        setTotal(total)
    }, [])

    const handlePageChange = async (newPage: number) => {
        setPage(newPage)
        const { data, total } = await getApplications({ page: newPage, size: 10, ...filters })
        setApps(data)
        setTotal(total)
    }

    const handleAddApplication = async (data: any) => {
        const result = await addApplication(data)
        if (result.success) {
            toast.success(`Added ${data.company_name} — ${data.job_title}`)
            refreshData()
        } else {
            toast.error(result.error)
        }
    }

    const handleStatusChange = async (id: number, newStatus: string) => {
        const result = await updateApplicationStatus(id, newStatus)
        if (result.success) {
            toast.success('Status updated')
            refreshStatusData()
        } else {
            toast.error(result.error)
        }
    }

    const handleDeleteApplication = async (id: number) => {
        if (confirm('Are you sure you want to delete this application?')) {
            const result = await deleteApplication(id)
            if (result.success) {
                toast.success('Application deleted')
                refreshData()
            } else {
                toast.error(result.error)
            }
        }
    }

    const handleViewHistory = async (id: number) => {
        const app = apps.find((a: any) => a.id === id)
        if (app) {
            setSelectedApp(app)
            const result = await getApplicationHistory(id)
            if (result.success) {
                setHistoryData(result.data ?? [])
                setIsHistoryOpen(true)
            } else {
                toast.error(result.error)
            }
        }
    }

    const handleAddStatus = async (data: { status: string; date: string }) => {
        if (selectedApp) {
            const result = await updateApplicationStatus(selectedApp.id, data.status, data.date)
            if (result.success) {
                toast.success('Status updated')
                const historyResult = await getApplicationHistory(selectedApp.id)
                if (historyResult.success) setHistoryData(historyResult.data ?? [])
                refreshStatusData()
            } else {
                toast.error(result.error)
            }
        }
    }

    const handleDeleteHistory = async (historyId: number) => {
        const result = await deleteHistoryItem(historyId)
        if (result.success) {
            toast.success('History entry deleted')
            const historyResult = await getApplicationHistory(selectedApp.id)
            if (historyResult.success) setHistoryData(historyResult.data ?? [])
            refreshStatusData()
        } else {
            toast.error(result.error)
        }
    }

    const handleEditApplication = async (
        id: number,
        data: {
            company_name: string
            job_title: string
            category: string
            application_url: string
            date_applied: string
            notes: string
        }
    ) => {
        const result = await updateApplicationDetails(id, data)
        if (result.success) {
            toast.success('Application updated')
            setSelectedApp({ ...selectedApp, ...data })
            refreshData()
        } else {
            toast.error(result.error)
        }
    }

    const handleExportCSV = async () => {
        const result = await exportApplicationsCSV()
        if (!result.success || !result.csv) {
            toast.error(result.error || 'Export failed')
            return
        }
        const blob = new Blob([result.csv], { type: 'text/csv;charset=utf-8;' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `applications-${new Date().toISOString().split('T')[0]}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        toast.success(`Exported ${result.count} application${result.count === 1 ? '' : 's'}`)
    }

    const handleImportCSV = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        e.target.value = ''
        if (!file) return

        const text = await file.text()
        const result = await importApplicationsCSV(text)
        if (!result.success) {
            toast.error(result.error || 'Import failed')
            return
        }

        const added = result.added ?? 0
        const skipped = result.skipped ?? 0
        const errors = result.errors ?? []
        const parts = [`${added} added`]
        if (skipped > 0) parts.push(`${skipped} skipped`)
        if (errors.length > 0) parts.push(`${errors.length} error${errors.length === 1 ? '' : 's'}`)
        toast.success(`Import complete: ${parts.join(', ')}`)
        if (errors.length > 0) {
            console.warn('CSV import errors:', errors)
        }
        refreshData()
    }

    const refreshJobPostings = async (filters = jobFilters, page = jobPage) => {
        const { data, total } = await getJobPostings({ ...filters, page, size: JOB_PAGE_SIZE })
        setJobPostings(data)
        setTotalJobs(total)
    }

    const refreshWatchlist = async () => {
        const { data } = await getWatchedCompanies()
        setWatchlist(data)
    }

    const refreshPromotions = async () => {
        const { data } = await getPromotionSuggestions()
        setPromotions(data)
    }

    const refreshUnresolved = async () => {
        const { data } = await getUnresolvedFeeds()
        setUnresolved(data)
    }

    // Load the watchlist, promotion suggestions, and unresolved backlog on mount.
    useEffect(() => {
        refreshWatchlist()
        refreshPromotions()
        refreshUnresolved()
    }, [])

    const handleAddWatched = async (c: { source: string; slug: string; name: string; recipe?: string }) => {
        const result = await addWatchedCompany(c)
        if (result.success) {
            toast.success(`Watching ${c.name}`)
            refreshWatchlist()
        } else {
            toast.error(result.error)
        }
    }

    const handleRemoveWatched = async (id: number) => {
        const result = await removeWatchedCompany(id)
        if (result.success) {
            toast.success('Removed from watchlist')
            refreshWatchlist()
        } else {
            toast.error(result.error)
        }
    }

    // Approve a suggestion = add it to the watchlist (reuses addWatchedCompany);
    // it then drops out of suggestions (now watchlisted).
    const handleApproveSuggestion = async (c: { source: string; slug: string; name: string }) => {
        const result = await addWatchedCompany(c)
        if (result.success) {
            toast.success(`Promoted ${c.name} to the watchlist`)
            await Promise.all([refreshWatchlist(), refreshPromotions()])
        } else {
            toast.error(result.error)
        }
    }

    const handleDismissSuggestion = async (source: string, slug: string) => {
        const result = await dismissPromotion(source, slug)
        if (result.success) {
            refreshPromotions()
        } else {
            toast.error(result.error)
        }
    }

    const handleJobFilterChange = useCallback(async (newFilters: any) => {
        setJobFilters(newFilters)
        setJobPage(0)
        const { data, total } = await getJobPostings({ ...newFilters, page: 0, size: JOB_PAGE_SIZE })
        setJobPostings(data)
        setTotalJobs(total)
    }, [])

    const handleJobPageChange = async (newPage: number) => {
        setJobPage(newPage)
        await refreshJobPostings(jobFilters, newPage)
    }

    const handleViewJD = (id: number) => {
        const job = jobPostings.find((j: any) => j.id === id)
        if (job) {
            setSelectedJob(job)
            setIsJobDetailOpen(true)
        }
    }

    // Mark Applied now opens a dialog to pick the application category (instead of
    // always defaulting to 'Others'). The actual apply happens on confirm.
    const handleMarkApplied = (id: number) => {
        const job = jobPostings.find((j: any) => j.id === id) || { id }
        setApplyJob(job)
        setIsJobDetailOpen(false)
    }

    const handleConfirmApply = async (category: string) => {
        if (!applyJob) return
        const result = await markJobApplied(applyJob.id, category)
        if (result.success) {
            toast.success('Marked as applied')
            setApplyJob(null)
            setSelectedJob(null)
            await refreshJobPostings()
            await refreshData()
        } else {
            toast.error(result.error)
        }
    }

    const handleDiscardJob = async (id: number) => {
        const result = await discardJobPosting(id)
        if (result.success) {
            toast.success('Job discarded')
            setIsJobDetailOpen(false)
            setSelectedJob(null)
            await refreshJobPostings()
        } else {
            toast.error(result.error)
        }
    }

    const handleReopenJob = async (id: number) => {
        const result = await reopenJobPosting(id)
        if (result.success) {
            toast.success('Job reopened')
            setIsJobDetailOpen(false)
            setSelectedJob(null)
            await refreshJobPostings()
        } else {
            toast.error(result.error)
        }
    }

    const handleBulkRemove = async (jobIds: number[]) => {
        // ponytail: native confirm — same pattern as handleDeleteApplication.
        if (!confirm(`Remove ${jobIds.length} job${jobIds.length === 1 ? '' : 's'}? They'll be hidden from all tabs.`)) return
        const result = await bulkRemove(jobIds)
        if (result.success) {
            toast.success(`Removed ${result.count} job${result.count === 1 ? '' : 's'}`)
            await refreshJobPostings()
        } else {
            toast.error(result.error)
        }
    }

    const handleBulkReopen = async (jobIds: number[]) => {
        const result = await bulkReopen(jobIds)
        if (result.success) {
            toast.success(`Reopened ${result.count} job${result.count === 1 ? '' : 's'}`)
            await refreshJobPostings()
        } else {
            toast.error(result.error)
        }
    }

    const handleRemoveAllInView = async (filter: any) => {
        if (!confirm(`Remove all ${totalJobs} job${totalJobs === 1 ? '' : 's'} in this view? They'll be hidden from all tabs.`)) return
        const result = await removeAllInView(filter)
        if (result.success) {
            toast.success(`Removed ${result.count} job${result.count === 1 ? '' : 's'}`)
            await refreshJobPostings()
        } else {
            toast.error(result.error)
        }
    }

    return (
        <div className="space-y-6">
            {/* Header + KPIs */}
            <div>
                <div className="flex items-center justify-between mb-3 gap-3">
                    <h1 className="text-2xl font-bold tracking-tight">Application Tracker</h1>
                    <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={handleExportCSV}>
                            <Download className="mr-2 h-4 w-4" /> Export CSV
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
                            <Upload className="mr-2 h-4 w-4" /> Import CSV
                        </Button>
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".csv,text/csv"
                            onChange={handleImportCSV}
                            className="hidden"
                        />
                    </div>
                </div>
                <KPIGrid stats={kpis} />
            </div>

            {/* Tab toggle */}
            <div className="inline-flex items-center gap-1 rounded-lg border bg-muted/40 p-1">
                <button
                    type="button"
                    onClick={() => setActiveTab('applications')}
                    className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
                        activeTab === 'applications'
                            ? 'bg-background shadow-sm text-foreground'
                            : 'text-muted-foreground hover:text-foreground'
                    }`}
                >
                    Applications
                </button>
                <button
                    type="button"
                    onClick={() => setActiveTab('discovered')}
                    className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
                        activeTab === 'discovered'
                            ? 'bg-background shadow-sm text-foreground'
                            : 'text-muted-foreground hover:text-foreground'
                    }`}
                >
                    Discovered Jobs
                    {totalJobs > 0 && (
                        <span className="ml-2 px-1.5 py-0.5 rounded-full text-[10px] bg-primary text-primary-foreground">
                            {totalJobs}
                        </span>
                    )}
                </button>
                <button
                    type="button"
                    onClick={() => setActiveTab('watchlist')}
                    className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
                        activeTab === 'watchlist'
                            ? 'bg-background shadow-sm text-foreground'
                            : 'text-muted-foreground hover:text-foreground'
                    }`}
                >
                    Watchlist
                    {watchlist.length > 0 && (
                        <span className="ml-2 px-1.5 py-0.5 rounded-full text-[10px] bg-primary text-primary-foreground">
                            {watchlist.length}
                        </span>
                    )}
                    {promotions.length > 0 && (
                        <span className="ml-1 px-1.5 py-0.5 rounded-full text-[10px] bg-emerald-600 text-white" title={`${promotions.length} promotion suggestion(s)`}>
                            +{promotions.length}
                        </span>
                    )}
                </button>
                <button
                    type="button"
                    onClick={() => setActiveTab('unresolved')}
                    className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
                        activeTab === 'unresolved'
                            ? 'bg-background shadow-sm text-foreground'
                            : 'text-muted-foreground hover:text-foreground'
                    }`}
                >
                    Unresolved
                </button>
            </div>

            {activeTab === 'discovered' ? (
                <DiscoveredJobsTab
                    data={jobPostings}
                    total={totalJobs}
                    page={jobPage}
                    size={JOB_PAGE_SIZE}
                    onPageChange={handleJobPageChange}
                    onFilterChange={handleJobFilterChange}
                    onMarkApplied={handleMarkApplied}
                    onDiscard={handleDiscardJob}
                    onReopen={handleReopenJob}
                    onViewJD={handleViewJD}
                    onBulkRemove={handleBulkRemove}
                    onBulkReopen={handleBulkReopen}
                    onRemoveAllInView={handleRemoveAllInView}
                />
            ) : activeTab === 'watchlist' ? (
                <WatchlistTab
                    promotions={promotions}
                    watchlist={watchlist}
                    onApprove={handleApproveSuggestion}
                    onDismiss={handleDismissSuggestion}
                    onAdd={handleAddWatched}
                    onRemove={handleRemoveWatched}
                />
            ) : activeTab === 'unresolved' ? (
                <UnresolvedTab data={unresolved} />
            ) : (
                <ApplicationsTab
                    apps={apps}
                    total={total}
                    page={page}
                    timeline={timeline}
                    categories={categories}
                    statusFlow={statusFlow}
                    onAddApplication={handleAddApplication}
                    onPageChange={handlePageChange}
                    onFilterChange={handleFilterChange}
                    onStatusChange={handleStatusChange}
                    onDelete={handleDeleteApplication}
                    onHistory={handleViewHistory}
                />
            )}

            {/* Job Detail Modal */}
            {selectedJob && (
                <JobDetailModal
                    isOpen={isJobDetailOpen}
                    onClose={() => {
                        setIsJobDetailOpen(false)
                        setSelectedJob(null)
                    }}
                    job={selectedJob}
                    onMarkApplied={handleMarkApplied}
                    onDiscard={handleDiscardJob}
                    onReopen={handleReopenJob}
                />
            )}

            {/* Apply category picker */}
            <ApplyCategoryDialog
                open={!!applyJob}
                companyName={applyJob?.company_name}
                jobTitle={applyJob?.job_title}
                onConfirm={handleConfirmApply}
                onClose={() => setApplyJob(null)}
            />

            {/* History Modal */}
            {selectedApp && (
                <StatusHistoryModal
                    isOpen={isHistoryOpen}
                    onClose={() => {
                        setIsHistoryOpen(false)
                        setSelectedApp(null)
                    }}
                    application={selectedApp}
                    history={historyData}
                    onAddStatus={handleAddStatus}
                    onDeleteHistory={handleDeleteHistory}
                    onEditApplication={handleEditApplication}
                />
            )}
        </div>
    )
}
