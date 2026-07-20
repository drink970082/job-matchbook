'use client'

import { AddApplicationForm } from './AddApplicationForm'
import { ApplicationTable } from './ApplicationTable'
import { TimelineHeatmap } from './TimelineHeatmap'
import { CategoryDonut } from './CategoryDonut'
import { StatusFunnel } from './StatusFunnel'
import { SankeyChart } from './SankeyChart'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface ApplicationsTabProps {
    apps: any[]
    categoryOptions: string[]
    total: number
    page: number
    timeline: any[]
    categories: any[]
    statusFlow: any[]
    onAddApplication: (data: any) => void
    onPageChange: (page: number) => void
    onFilterChange: (filters: any) => void
    onStatusChange: (id: number, newStatus: string) => void
    onDelete: (id: number) => void
    onHistory: (id: number) => void
}

export function ApplicationsTab({
    apps,
    categoryOptions,
    total,
    page,
    timeline,
    categories,
    statusFlow,
    onAddApplication,
    onPageChange,
    onFilterChange,
    onStatusChange,
    onDelete,
    onHistory,
}: ApplicationsTabProps) {
    return (
        <>
            {/* Form (4) + Table (8) side by side */}
            <div className="grid grid-cols-12 gap-6">
                {/* Add Application Form */}
                <div className="col-span-4">
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="text-lg">Add Application</CardTitle>
                        </CardHeader>
                        <CardContent>
                            <AddApplicationForm categories={categoryOptions} onSubmit={onAddApplication} />
                        </CardContent>
                    </Card>
                </div>

                {/* Table */}
                <div className="col-span-8">
                    <ApplicationTable
                        data={apps}
                        categories={categoryOptions}
                        total={total}
                        page={page}
                        size={10}
                        onPageChange={onPageChange}
                        onFilterChange={onFilterChange}
                        onStatusChange={onStatusChange}
                        onDelete={onDelete}
                        onHistory={onHistory}
                    />
                </div>
            </div>

            {/* Charts */}
            <div className="grid gap-6 grid-cols-2">
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
    )
}
