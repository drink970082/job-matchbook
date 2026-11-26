'use client'

import { useState, useEffect } from 'react'
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
import { Trash2, FileText, Link2, ArrowUp, ArrowDown } from 'lucide-react'
import { Pagination } from './Pagination'
import { STATUSES, getStatusColor } from '@/lib/constants'
import { safeHref } from '@/lib/utils'
import type { ApplicationSort } from '@/lib/application-actions'

interface Application {
    id: number
    company_name: string
    job_title: string
    status: string
    category: string
    date_applied: string
    notes: string
    application_url?: string | null
    job_postings?: Array<{ id: number }>
}

type SortKey = ApplicationSort['sort']

// `Nov 3`, plus the year when it is not this year.
export function formatAppliedDate(iso: string, now = new Date()) {
    const d = new Date(iso + 'T00:00:00')
    return d.toLocaleDateString('en-US', d.getFullYear() === now.getFullYear()
        ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' })
}

interface ApplicationTableProps {
    data: Application[]
    categories: string[]
    total: number
    page: number
    size: number
    onPageChange: (page: number) => void
    onFilterChange: (filters: { status?: string; historicalStatus?: string; category?: string; search?: string } & Partial<ApplicationSort>) => void
    onStatusChange: (id: number, status: string) => void
    onDelete: (id: number) => void
    onHistory: (id: number) => void
    onLink: (id: number) => void
}

export function ApplicationTable({
    data,
    categories,
    total,
    page,
    size,
    onPageChange,
    onFilterChange,
    onStatusChange,
    onDelete,
    onHistory,
    onLink,
}: ApplicationTableProps) {
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('all')
    const [historicalStatusFilter, setHistoricalStatusFilter] = useState('all')
    const [categoryFilter, setCategoryFilter] = useState('all')
    const [sort, setSort] = useState<ApplicationSort>({ sort: 'date', dir: 'desc' })

    // Debounce search
    useEffect(() => {
        const timer = setTimeout(() => {
            onFilterChange({ search, status: statusFilter, historicalStatus: historicalStatusFilter, category: categoryFilter, ...sort })
        }, 300)
        return () => clearTimeout(timer)
    }, [search, statusFilter, historicalStatusFilter, categoryFilter, sort, onFilterChange])

    // Click a header: sort by it (asc first, date desc first), click again to flip.
    const SortHead = ({ k, label, className }: { k: SortKey; label: string; className: string }) => (
        <TableHead className={className} aria-sort={sort.sort === k ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}>
            <button type="button" className="inline-flex items-center gap-1 hover:text-foreground"
                onClick={() => setSort(sort.sort === k
                    ? { sort: k, dir: sort.dir === 'asc' ? 'desc' : 'asc' }
                    : { sort: k, dir: k === 'date' ? 'desc' : 'asc' })}>
                {label}
                {sort.sort === k && (sort.dir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
            </button>
        </TableHead>
    )

    return (
        <div className="space-y-4">
            <div className="flex flex-row gap-4">
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
                        {categories.map((c) => (
                            <SelectItem key={c} value={c}>{c}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>

            <div className="rounded-md border overflow-hidden">
                <Table className="table-fixed w-full">
                    <TableHeader>
                        <TableRow>
                            <SortHead k="company" label="Company" className="w-[18%] whitespace-normal" />
                            <TableHead className="w-[26%] whitespace-normal">Job Title</TableHead>
                            <TableHead className="w-[14%] whitespace-normal">Category</TableHead>
                            <SortHead k="date" label="Date" className="w-[12%] whitespace-normal" />
                            <SortHead k="status" label="Status" className="w-[16%] whitespace-normal" />
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
                                            {app.application_url && safeHref(app.application_url) !== '#' ? (
                                                <a href={safeHref(app.application_url)} target="_blank" rel="noopener noreferrer"
                                                    className="underline-offset-2 hover:underline">{app.job_title}</a>
                                            ) : app.job_title}
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
                                            {formatAppliedDate(app.date_applied)}
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
                                                {app.job_postings?.length === 0 && (
                                                    <Button variant="ghost" size="icon" className="h-7 w-7" title="Link to a posting"
                                                        aria-label={`Link to a posting: ${app.company_name} - ${app.job_title}`} onClick={() => onLink(app.id)}>
                                                        <Link2 className="h-3.5 w-3.5" />
                                                    </Button>
                                                )}
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => onHistory(app.id)}
                                                    title="Details"
                                                    aria-label="Details"
                                                    className="h-7 w-7"
                                                >
                                                    <FileText className="h-3.5 w-3.5" />
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

            <Pagination page={page} size={size} total={total} onPageChange={onPageChange} />
        </div>
    )
}
