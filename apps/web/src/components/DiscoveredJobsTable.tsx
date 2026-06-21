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
import { Pagination } from './Pagination'
import { MATCH_SCORE_THRESHOLD } from '@/lib/constants'
import type { JobBucket, DiscardType } from '@/lib/actions'
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
    page: number
    size: number
    onPageChange: (page: number) => void
    onFilterChange: (filters: {
        bucket: JobBucket
        search: string
        minScore?: number
        discardType?: DiscardType
    }) => void
    onMarkApplied: (id: number) => void
    onDiscard: (id: number) => void
    onReopen: (id: number) => void
    onViewJD: (id: number) => void
}

const BUCKETS: { value: JobBucket; label: string }[] = [
    { value: 'matched', label: 'Matched' },
    { value: 'discarded', label: 'Discarded' },
    { value: 'failed', label: 'Failed' },
]

function scoreVariant(score?: number | null): 'default' | 'secondary' | 'destructive' | 'outline' {
    if (score == null) return 'outline'
    if (score >= 80) return 'default'
    if (score >= 60) return 'secondary'
    return 'destructive'
}

// Why a discarded posting is here, at a glance (so you don't open each one):
// a hard disqualification (with its reason) vs. just a below-threshold score.
function discardLabel(job: JobPosting): { text: string; cls: string } | null {
    let detail: any = null
    if (job.score_detail) {
        try { detail = JSON.parse(job.score_detail) } catch { /* ignore bad JSON */ }
    }
    if (detail?.disqualified) {
        return { text: `✕ ${detail.disqualification_reason || 'disqualified'}`, cls: 'text-red-600' }
    }
    if (job.score != null && job.score < MATCH_SCORE_THRESHOLD) {
        return { text: `low score (< ${MATCH_SCORE_THRESHOLD})`, cls: 'text-amber-600' }
    }
    if (job.pipeline_status === 'discarded') {
        return { text: 'discarded manually', cls: 'text-muted-foreground' }
    }
    return null
}

export function DiscoveredJobsTable({
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
}: DiscoveredJobsTableProps) {
    const [search, setSearch] = useState('')
    const [bucket, setBucket] = useState<JobBucket>('matched')
    const [minScore, setMinScore] = useState('')
    // Discarded-only sub-filter for debugging/human-check: all | disqualified | lowscore
    const [discardType, setDiscardType] = useState<'all' | DiscardType>('all')

    const stableFilterChange = useCallback(onFilterChange, [])

    useEffect(() => {
        const timer = setTimeout(() => {
            stableFilterChange({
                search,
                bucket,
                minScore: minScore === '' ? undefined : Number(minScore),
                discardType: bucket === 'discarded' && discardType !== 'all' ? discardType : undefined,
            })
        }, 300)
        return () => clearTimeout(timer)
    }, [search, bucket, minScore, discardType, stableFilterChange])

    return (
        <div className="space-y-4">
            <div className="flex flex-col sm:flex-row gap-3 sm:items-center">
                <div className="inline-flex items-center gap-1 rounded-lg border bg-muted/40 p-1">
                    {BUCKETS.map((b) => (
                        <button
                            key={b.value}
                            type="button"
                            onClick={() => setBucket(b.value)}
                            className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
                                bucket === b.value
                                    ? 'bg-background shadow-sm text-foreground'
                                    : 'text-muted-foreground hover:text-foreground'
                            }`}
                        >
                            {b.label}
                        </button>
                    ))}
                </div>
                <div className="flex-1">
                    <Input
                        placeholder="Search companies or job titles..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                    />
                </div>
                <Input
                    type="number"
                    min={0}
                    max={100}
                    placeholder="Min score"
                    value={minScore}
                    onChange={(e) => setMinScore(e.target.value)}
                    className="w-[110px]"
                    aria-label="Minimum score"
                />
                {bucket === 'discarded' && (
                    <Select value={discardType} onValueChange={(v) => setDiscardType(v as 'all' | DiscardType)}>
                        <SelectTrigger className="w-[150px]" aria-label="Discard type">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">All discarded</SelectItem>
                            <SelectItem value="disqualified">Disqualified</SelectItem>
                            <SelectItem value="lowscore">Low score</SelectItem>
                        </SelectContent>
                    </Select>
                )}
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
                                const reason = discardLabel(job)
                                return (
                                    <TableRow key={job.id}>
                                        <TableCell className="whitespace-normal font-medium text-sm" title={job.company_name}>
                                            {job.company_name}
                                        </TableCell>
                                        <TableCell className="whitespace-normal text-sm text-muted-foreground" title={job.job_title}>
                                            {job.job_title}
                                            {reason && (
                                                <div className={`mt-0.5 text-[11px] font-medium ${reason.cls}`} title={reason.text}>
                                                    {reason.text}
                                                </div>
                                            )}
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

            <Pagination page={page} size={size} total={total} onPageChange={onPageChange} />
        </div>
    )
}
