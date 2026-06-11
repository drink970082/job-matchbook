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
import { Badge } from '@/components/ui/badge'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import { FileText, Download, CheckCircle2, XCircle, AlertTriangle, RotateCcw } from 'lucide-react'

export interface JobPosting {
    id: number
    source: string
    company_name: string
    job_title: string
    location?: string | null
    job_url: string
    description?: string | null
    score?: number | null
    score_detail?: string | null
    resume_path?: string | null
    resume_pages?: number | null
    pipeline_status?: string
}

interface DiscoveredJobsTableProps {
    data: JobPosting[]
    total: number
    onFilterChange: (filters: { status?: string; minScore?: number; search?: string }) => void
    onMarkApplied: (id: number) => void
    onDiscard: (id: number) => void
    onReopen: (id: number) => void
    onViewJD: (id: number) => void
}

// Pipeline statuses surfaced in the filter dropdown.
const PIPELINE_STATUSES = ['scored', 'tailored', 'notified', 'new', 'applied', 'discarded', 'failed'] as const

function scoreVariant(score?: number | null): 'default' | 'secondary' | 'destructive' | 'outline' {
    if (score == null) return 'outline'
    if (score >= 80) return 'default'
    if (score >= 60) return 'secondary'
    return 'destructive'
}

export function DiscoveredJobsTable({
    data,
    total,
    onFilterChange,
    onMarkApplied,
    onDiscard,
    onReopen,
    onViewJD,
}: DiscoveredJobsTableProps) {
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState('queue')
    const [minScoreFilter, setMinScoreFilter] = useState('all')

    const stableFilterChange = useCallback(onFilterChange, [])

    useEffect(() => {
        const timer = setTimeout(() => {
            stableFilterChange({
                search,
                // 'queue' = default actionable queue (omit status so the action applies its default)
                status: statusFilter === 'queue' ? undefined : statusFilter,
                minScore: minScoreFilter === 'all' ? undefined : Number(minScoreFilter),
            })
        }, 300)
        return () => clearTimeout(timer)
    }, [search, statusFilter, minScoreFilter, stableFilterChange])

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
                <Select value={minScoreFilter} onValueChange={setMinScoreFilter}>
                    <SelectTrigger className="w-[140px]">
                        <SelectValue placeholder="Min Score" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">Any Score</SelectItem>
                        <SelectItem value="90">90+</SelectItem>
                        <SelectItem value="80">80+</SelectItem>
                        <SelectItem value="70">70+</SelectItem>
                        <SelectItem value="50">50+</SelectItem>
                    </SelectContent>
                </Select>
                <Select value={statusFilter} onValueChange={setStatusFilter}>
                    <SelectTrigger className="w-[160px]">
                        <SelectValue placeholder="Pipeline Status" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="queue">Queue (actionable)</SelectItem>
                        <SelectItem value="all">All Statuses</SelectItem>
                        {PIPELINE_STATUSES.map((s) => (
                            <SelectItem key={s} value={s}>{s}</SelectItem>
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
                            <TableHead className="w-[10%] whitespace-normal">Score</TableHead>
                            <TableHead className="w-[14%] whitespace-normal">Location</TableHead>
                            <TableHead className="w-[12%] whitespace-normal">Source</TableHead>
                            <TableHead className="w-[20%] whitespace-normal text-right">Actions</TableHead>
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
                            data.map((job) => {
                                const multiPage = job.resume_pages != null && job.resume_pages > 1
                                return (
                                    <TableRow key={job.id}>
                                        <TableCell className="whitespace-normal font-medium text-sm" title={job.company_name}>
                                            {job.company_name}
                                        </TableCell>
                                        <TableCell className="whitespace-normal text-sm text-muted-foreground" title={job.job_title}>
                                            {job.job_title}
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex items-center gap-1">
                                                <Badge variant={scoreVariant(job.score)}>
                                                    {job.score ?? '—'}
                                                </Badge>
                                                {multiPage && (
                                                    <Badge
                                                        variant="destructive"
                                                        title={`Resume is ${job.resume_pages} pages (expected 1)`}
                                                    >
                                                        <AlertTriangle className="h-3 w-3" />
                                                        {job.resume_pages}p
                                                    </Badge>
                                                )}
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-muted-foreground text-xs whitespace-normal" title={job.location || ''}>
                                            {job.location || '—'}
                                        </TableCell>
                                        <TableCell>
                                            <span className="text-[11px] truncate max-w-full inline-block font-medium px-1.5 py-0.5 rounded bg-secondary text-secondary-foreground">
                                                {job.source}
                                            </span>
                                        </TableCell>
                                        <TableCell className="text-right">
                                            <div className="flex justify-end gap-0.5">
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => onViewJD(job.id)}
                                                    title="View JD"
                                                    className="h-7 w-7"
                                                >
                                                    <FileText className="h-3.5 w-3.5" />
                                                </Button>
                                                {job.resume_path && (
                                                    <Button
                                                        variant="ghost"
                                                        size="icon"
                                                        asChild
                                                        title="Download Resume"
                                                        className="h-7 w-7"
                                                    >
                                                        <a href={`/api/resume/${job.id}`} target="_blank" rel="noopener noreferrer">
                                                            <Download className="h-3.5 w-3.5" />
                                                        </a>
                                                    </Button>
                                                )}
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => onMarkApplied(job.id)}
                                                    title="Mark Applied"
                                                    className="h-7 w-7 text-emerald-600 hover:text-emerald-600"
                                                >
                                                    <CheckCircle2 className="h-3.5 w-3.5" />
                                                </Button>
                                                {job.pipeline_status === 'discarded' ? (
                                                    <Button
                                                        variant="ghost"
                                                        size="icon"
                                                        onClick={() => onReopen(job.id)}
                                                        title="Reopen"
                                                        className="h-7 w-7"
                                                    >
                                                        <RotateCcw className="h-3.5 w-3.5" />
                                                    </Button>
                                                ) : (
                                                    <Button
                                                        variant="ghost"
                                                        size="icon"
                                                        onClick={() => onDiscard(job.id)}
                                                        title="Discard"
                                                        className="h-7 w-7 text-destructive hover:text-destructive"
                                                    >
                                                        <XCircle className="h-3.5 w-3.5" />
                                                    </Button>
                                                )}
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                )
                            })
                        )}
                    </TableBody>
                </Table>
            </div>

            <div className="flex items-center justify-between py-2">
                <div className="text-sm text-muted-foreground">
                    {total} discovered job{total === 1 ? '' : 's'}
                </div>
            </div>
        </div>
    )
}
