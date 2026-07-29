
'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DiscoveredJobsTable, type JobPosting } from './DiscoveredJobsTable'
import { ScorerUsageBar } from './ScorerUsageBar'
import type { JobBucket, DisqualifyCause, JobSort } from '@/lib/actions'

interface DiscoveredJobsTabProps {
    data: JobPosting[]
    total: number
    page: number
    size: number
    onPageChange: (page: number) => void
    onFilterChange: (filters: {
        bucket: JobBucket
        search: string
        minScore?: number
        cause?: DisqualifyCause
        sort: JobSort
    }) => void
    onMarkApplied: (id: number) => void
    onDiscard: (id: number) => void
    onReopen: (id: number) => void
    onViewJD: (id: number) => void
    onBulkRemove: (ids: number[]) => void
    onBulkReopen: (ids: number[]) => void
    onRemoveAllInView: (filter: { bucket: JobBucket; search: string; minScore?: number; cause?: DisqualifyCause }) => void
}

export function DiscoveredJobsTab({
    data,
    total,
    page,
    size,
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
