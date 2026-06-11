
'use client'

import { useRef, useState } from 'react'
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
} from '@/lib/actions'
import { ApplicationTable } from './ApplicationTable'
import { DiscoveredJobsTable } from './DiscoveredJobsTable'
import { JobDetailModal } from './JobDetailModal'
import { KPIGrid } from './KPIGrid'
import { AddApplicationForm } from './AddApplicationForm'
import { StatusHistoryModal } from './StatusHistoryModal'
import { StatusFunnel } from './StatusFunnel'
import { TimelineHeatmap } from './TimelineHeatmap'
import { CategoryDonut } from './CategoryDonut'
import { SankeyChart } from './SankeyChart'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Download, Upload } from 'lucide-react'
import { toast } from 'sonner'

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
    const [activeTab, setActiveTab] = useState<'applications' | 'discovered'>('applications')

    // Discovered Jobs state
    const [jobPostings, setJobPostings] = useState<any[]>(initialJobPostings)
    const [totalJobs, setTotalJobs] = useState(totalJobPostings)
    const [jobFilters, setJobFilters] = useState<any>({})
    const [selectedJob, setSelectedJob] = useState<any>(null)
    const [isJobDetailOpen, setIsJobDetailOpen] = useState(false)
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

    const refreshData = async () => {
        const { data, total } = await getApplications({ page, size: 10, ...filters })
        setApps(data)
        setTotal(total)

        const newKpis = await getKPIs()
        setKpis(newKpis)

        const [flowRes, timeRes, catRes] = await Promise.all([
            getStatusFlow(),
            getTimelineData(),
            getCategoryData(),
        ])
        if (flowRes.data) setStatusFlow(flowRes.data)
        if (timeRes.data) setTimeline(timeRes.data)
        if (catRes.data) setCategories(catRes.data)
    }

    const handleFilterChange = async (newFilters: any) => {
        setFilters(newFilters)
        setPage(0)
        const { data, total } = await getApplications({ page: 0, size: 10, ...newFilters })
        setApps(data)
        setTotal(total)
    }

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
            refreshData()
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

    const handleAddStatus = async (data: { status: string; notes: string; date: string }) => {
        if (selectedApp) {
            const result = await updateApplicationStatus(selectedApp.id, data.status, data.date, data.notes)
            if (result.success) {
                toast.success('Status updated')
                const historyResult = await getApplicationHistory(selectedApp.id)
                if (historyResult.success) setHistoryData(historyResult.data ?? [])
                refreshData()
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
            refreshData()
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

    const refreshJobPostings = async (filters = jobFilters) => {
        const { data, total } = await getJobPostings(filters)
        setJobPostings(data)
        setTotalJobs(total)
    }

    const handleJobFilterChange = async (newFilters: any) => {
        setJobFilters(newFilters)
        const { data, total } = await getJobPostings(newFilters)
        setJobPostings(data)
        setTotalJobs(total)
    }

    const handleViewJD = (id: number) => {
        const job = jobPostings.find((j: any) => j.id === id)
        if (job) {
            setSelectedJob(job)
            setIsJobDetailOpen(true)
        }
    }

    const handleMarkApplied = async (id: number) => {
        const result = await markJobApplied(id)
        if (result.success) {
            toast.success('Marked as applied')
            setIsJobDetailOpen(false)
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
            </div>

            {activeTab === 'discovered' ? (
                <Card>
                    <CardHeader className="pb-3">
                        <CardTitle className="text-lg">Discovered Jobs</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <DiscoveredJobsTable
                            data={jobPostings}
                            total={totalJobs}
                            onFilterChange={handleJobFilterChange}
                            onMarkApplied={handleMarkApplied}
                            onDiscard={handleDiscardJob}
                            onReopen={handleReopenJob}
                            onViewJD={handleViewJD}
                        />
                    </CardContent>
                </Card>
            ) : (
            <>
            {/* Form (4) + Table (8) side by side */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                {/* Add Application Form */}
                <div className="lg:col-span-4">
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="text-lg">Add Application</CardTitle>
                        </CardHeader>
                        <CardContent>
                            <AddApplicationForm onSubmit={handleAddApplication} />
                        </CardContent>
                    </Card>
                </div>

                {/* Table */}
                <div className="lg:col-span-8">
                    <ApplicationTable
                        data={apps}
                        total={total}
                        page={page}
                        size={10}
                        onPageChange={handlePageChange}
                        onFilterChange={handleFilterChange}
                        onStatusChange={handleStatusChange}
                        onDelete={handleDeleteApplication}
                        onHistory={handleViewHistory}
                    />
                </div>
            </div>

            {/* Charts */}
            <div className="grid gap-6 lg:grid-cols-2">
                <Card>
                    <CardHeader className="pb-3">
                        <CardTitle className="text-lg">Application Timeline</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <TimelineHeatmap data={timeline} />
                    </CardContent>
                </Card>

                <Card>
                    <CardHeader className="pb-3">
                        <CardTitle className="text-lg">Categories</CardTitle>
                    </CardHeader>
                    <CardContent>
                        <CategoryDonut data={categories} />
                    </CardContent>
                </Card>
            </div>

            <Card>
                <CardHeader className="pb-3">
                    <CardTitle className="text-lg">Status Funnel</CardTitle>
                </CardHeader>
                <CardContent>
                    <StatusFunnel data={statusFlow} />
                </CardContent>
            </Card>

            <Card>
                <CardHeader className="pb-3">
                    <CardTitle className="text-lg">Status Flow</CardTitle>
                </CardHeader>
                <CardContent>
                    <SankeyChart data={statusFlow} />
                </CardContent>
            </Card>
            </>
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
