'use client'

import { useState, useCallback, useEffect } from 'react'
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import { Trash2, History } from 'lucide-react'
import { STATUSES, CATEGORIES, getStatusColor } from '@/lib/constants'

interface Application {
    id: number
    company_name: string
    job_title: string
    status: string
    category: string
    date_applied: string
    notes: string
}

interface ApplicationTableProps {
    data: Application[]
    total: number
    page: number
    size: number
    onPageChange: (page: number) => void
    onFilterChange: (filters: { status?: string; historicalStatus?: string; category?: string; search?: string }) => void
    onStatusChange: (id: number, status: string) => void
    onDelete: (id: number) => void
    onHistory: (id: number) => void
}

export function ApplicationTable({
    data,
    total,
    page,
    size,
    onPageChange,
    onFilterChange,
    onStatusChange,
    onDelete,
    onHistory,
}: ApplicationTableProps) {
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('all')
    const [historicalStatusFilter, setHistoricalStatusFilter] = useState('all')
    const [categoryFilter, setCategoryFilter] = useState('all')

    const stableFilterChange = useCallback(onFilterChange, [])

    // Debounce search
    useEffect(() => {
        const timer = setTimeout(() => {
            stableFilterChange({ search, status: statusFilter, historicalStatus: historicalStatusFilter, category: categoryFilter })
        }, 300)
        return () => clearTimeout(timer)
    }, [search, statusFilter, historicalStatusFilter, categoryFilter, stableFilterChange])

    const totalPages = Math.ceil(total / size)

    return (
        <div className="space-y-4">
            <div className="flex flex-col sm:flex-row gap-4">
                <div className="flex-1">
                    <Input
                        placeholder="Search companies or job titles..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                    />
                </div>
                <Select value={statusFilter} onValueChange={setStatusFilter}>
                    <SelectTrigger className="w-[160px]">
                        <SelectValue placeholder="Current Status" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">All Current</SelectItem>
                        {STATUSES.map((s) => (
                            <SelectItem key={s} value={s}>{s}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Select value={historicalStatusFilter} onValueChange={setHistoricalStatusFilter}>
                    <SelectTrigger className="w-[160px]">
                        <SelectValue placeholder="Any History" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">Any History</SelectItem>
                        {STATUSES.map((s) => (
                            <SelectItem key={s} value={s}>{s}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                <Select value={categoryFilter} onValueChange={setCategoryFilter}>
                    <SelectTrigger className="w-[140px]">
                        <SelectValue placeholder="Category" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">All Category</SelectItem>
                        {CATEGORIES.map((c) => (
                            <SelectItem key={c} value={c}>{c}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>

            <div className="rounded-md border overflow-hidden">
                <Table className="table-fixed w-full">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[18%] whitespace-normal">Company</TableHead>
                            <TableHead className="w-[26%] whitespace-normal">Job Title</TableHead>
                            <TableHead className="w-[14%] whitespace-normal">Category</TableHead>
                            <TableHead className="w-[10%] whitespace-normal">Date</TableHead>
                            <TableHead className="w-[18%] whitespace-normal">Status</TableHead>
                            <TableHead className="w-[14%] whitespace-normal text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {data.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={6} className="h-24 text-center text-muted-foreground">
                                    No results.
                                </TableCell>
                            </TableRow>
                        ) : (
                            data.map((app) => {
                                const color = getStatusColor(app.status)
                                return (
                                    <TableRow key={app.id}>
                                        <TableCell className="whitespace-normal font-medium text-sm" title={app.company_name}>
                                            {app.company_name}
                                        </TableCell>
                                        <TableCell className="whitespace-normal text-sm text-muted-foreground" title={app.job_title}>
                                            {app.job_title}
                                        </TableCell>
                                        <TableCell>
                                            <span 
                                                className="text-[11px] truncate max-w-full inline-block font-medium px-1.5 py-0.5 rounded bg-secondary text-secondary-foreground" 
                                                title={app.category}
                                            >
                                                {app.category}
                                            </span>
                                        </TableCell>
                                        <TableCell className="text-muted-foreground text-xs">
                                            {new Date(app.date_applied + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex items-center gap-1">
                                                <span className={`h-2 w-2 rounded-full shrink-0 ${color.dot}`} />
                                                <select
                                                    value={app.status}
                                                    onChange={(e) => onStatusChange(app.id, e.target.value)}
                                                    className={`text-xs font-medium px-1 py-0.5 rounded border-0 cursor-pointer ${color.bg} ${color.text} focus:ring-1 focus:ring-ring focus:outline-none w-full`}
                                                >
                                                    {STATUSES.map((s) => (
                                                        <option key={s} value={s}>{s}</option>
                                                    ))}
                                                </select>
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-right">
                                            <div className="flex justify-end gap-0.5">
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => onHistory(app.id)}
                                                    title="History"
                                                    className="h-7 w-7"
                                                >
                                                    <History className="h-3.5 w-3.5" />
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => onDelete(app.id)}
                                                    title="Delete"
                                                    className="h-7 w-7 text-destructive hover:text-destructive"
                                                >
                                                    <Trash2 className="h-3.5 w-3.5" />
                                                </Button>
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                )
                            })
                        )}
                    </TableBody>
                </Table>
            </div>

            <div className="flex items-center justify-between py-4">
                <div className="text-sm text-muted-foreground">
                    Showing {page * size + 1}–{Math.min((page + 1) * size, total)} of {total}
                </div>
                <div className="flex gap-2">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onPageChange(page - 1)}
                        disabled={page <= 0}
                    >
                        Previous
                    </Button>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onPageChange(page + 1)}
                        disabled={page >= totalPages - 1}
                    >
                        Next
                    </Button>
                </div>
            </div>
        </div>
    )
}
