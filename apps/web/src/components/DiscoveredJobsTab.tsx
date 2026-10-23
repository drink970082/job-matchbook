
'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DiscoveredJobsTable, type JobPosting } from './DiscoveredJobsTable'
import { ScorerUsageBar } from './ScorerUsageBar'
import type { JobViewScope } from '@/lib/actions'
import type { JobTableFilters } from './DiscoveredJobsTable'

interface DiscoveredJobsTabProps {
    data: JobPosting[]
    total: number
    page: number
    size: number
    filters: JobTableFilters
    loading: boolean
    loadError: boolean
    onPageChange: (page: number) => void
    onFilterChange: (filters: JobTableFilters) => void
    onMarkApplied: (id: number, scope: JobViewScope) => void
    onDiscard: (id: number, scope: JobViewScope) => void
    onReopen: (id: number, scope: JobViewScope) => void
    onViewJD: (id: number, scope: JobViewScope) => void
    onBulkRemove: (ids: number[], scope: JobViewScope) => void
    onBulkReopen: (ids: number[], scope: JobViewScope) => void
    onRemoveAllInView: (filter: JobViewScope) => void
}

export function DiscoveredJobsTab({
    data,
    total,
    page,
    size,
    filters,
    loading,
    loadError,
    onPageChange,
    onFilterChange,
    onMarkApplied,
    onDiscard,
    onReopen,
    onViewJD,
    onBulkRemove,
    onBulkReopen,
    onRemoveAllInView,
}: DiscoveredJobsTabProps) {
    return (
        <Card>
            <CardHeader className="pb-3">
                <CardTitle className="text-lg">Discovered Jobs</CardTitle>
            </CardHeader>
            <CardContent>
                <ScorerUsageBar />
                <DiscoveredJobsTable
                    data={data}
                    total={total}
                    page={page}
                    size={size}
                    filters={filters}
                    loading={loading}
                    loadError={loadError}
                    onPageChange={onPageChange}
                    onFilterChange={onFilterChange}
                    onMarkApplied={onMarkApplied}
                    onDiscard={onDiscard}
                    onReopen={onReopen}
                    onViewJD={onViewJD}
                    onBulkRemove={onBulkRemove}
                    onBulkReopen={onBulkReopen}
                    onRemoveAllInView={onRemoveAllInView}
                />
            </CardContent>
        </Card>
    )
}
