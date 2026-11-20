'use client'

import { useCallback, useState } from 'react'
import { getApplications, addApplication, updateApplicationStatus, deleteApplication, getApplicationHistory, deleteHistoryItem, updateApplicationDetails } from '@/lib/application-actions'
import { getKPIs, getStatusFlow, getTimelineData, getCategoryData } from '@/lib/analytics-actions'
import { exportApplicationsCSV, importApplicationsCSV } from '@/lib/csv-actions'
import { todayISO } from '@/lib/utils'
import { ApplicationsTab } from './ApplicationsTab'
import { KPIGrid } from './KPIGrid'
import { StatusHistoryModal } from './StatusHistoryModal'
import { ImportCSVDialog } from './ImportCSVDialog'
import { Button } from '@/components/ui/button'
import { Download, Upload } from 'lucide-react'
import { toast } from 'sonner'

interface ApplicationsViewProps {
    initialApps: any[]
    initialKpis: any
    totalApps: number
    initialStatusFlow: any[]
    initialTimeline: any[]
    initialCategories: any[]
    categoryOptions: string[]
}

// The /applications page: KPIs, CSV import/export, the table, form and charts.
export function ApplicationsView({
    initialApps,
    initialKpis,
    totalApps,
    initialStatusFlow,
    initialTimeline,
    initialCategories,
    categoryOptions,
}: ApplicationsViewProps) {
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
    const [importDialogOpen, setImportDialogOpen] = useState(false)

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
        a.download = `applications-${todayISO()}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        toast.success(`Exported ${result.count} application${result.count === 1 ? '' : 's'}`)
    }

    // Returns false so ImportCSVDialog stays open on failure (the file is still loaded,
    // so a re-try after fixing the header is one click).
    const handleImportCSV = async (text: string) => {
        const result = await importApplicationsCSV(text)
        if (!result.success) {
            toast.error(result.error || 'Import failed')
            return false
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
        return true
    }

    return (
        <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <KPIGrid stats={kpis} />
                <div className="ml-auto flex gap-2">
                    <Button variant="outline" size="sm" title="Export CSV" aria-label="Export CSV" onClick={handleExportCSV}>
                        <Download className="mr-1.5 h-4 w-4" /> Export
                    </Button>
                    <Button variant="outline" size="sm" title="Import CSV" aria-label="Import CSV" onClick={() => setImportDialogOpen(true)}>
                        <Upload className="mr-1.5 h-4 w-4" /> Import
                    </Button>
                </div>
            </div>
            <ApplicationsTab
                apps={apps}
                categoryOptions={categoryOptions}
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

            {selectedApp && (
                <StatusHistoryModal
                    isOpen={isHistoryOpen}
                    onClose={() => {
                        setIsHistoryOpen(false)
                        setSelectedApp(null)
                    }}
                    categories={categoryOptions}
                    application={selectedApp}
                    history={historyData}
                    onAddStatus={handleAddStatus}
                    onDeleteHistory={handleDeleteHistory}
                    onEditApplication={handleEditApplication}
                />
            )}

            <ImportCSVDialog
                open={importDialogOpen}
                onOpenChange={setImportDialogOpen}
                onImport={handleImportCSV}
            />
        </div>
    )
}
