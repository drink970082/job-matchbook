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
import { safeHref } from '@/lib/utils'
import type { JobBucket, DisqualifyCause, JobSort } from '@/lib/actions'
import { FileText, CheckCircle2, XCircle, RotateCcw } from 'lucide-react'

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
    pipeline_status?: string
    pipeline_error?: string | null
    posted_at?: string | null
    created_at?: string | null
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

const BUCKETS: { value: JobBucket; label: string }[] = [
    { value: 'matched', label: 'Matched' },
    { value: 'belowbar', label: 'Below bar' },
    { value: 'discarded', label: 'Discarded' },
    { value: 'failed', label: 'Failed' },
    { value: 'lowcontext', label: 'Low-context' },
]

// Disqualification-cause sub-filter for the Discarded bucket (mirrors DisqualifyCause).
const CAUSES: { value: 'all' | DisqualifyCause; label: string }[] = [
    { value: 'all', label: 'All causes' },
    { value: 'authorization', label: 'Work authorization' },
    { value: 'location', label: 'Location' },
    { value: 'degree', label: 'Degree' },
    { value: 'clearance', label: 'Clearance' },
    { value: 'internship', label: 'Internship' },
]

// Compact, timezone-safe date: "2026-06-01" (yyyy-mm-dd) from a YYYY-MM-DD (or full-ISO)
// string; "—" for null. Parsed by regex (no Date object) so a UTC-midnight string never
// shifts a day.
function fmtDate(raw?: string | null): string {
    if (!raw) return '—'
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw)
    if (!m) return raw
    return `${m[1]}-${m[2]}-${m[3]}`
}

const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)

function scoreVariant(score?: number | null): 'default' | 'secondary' | 'destructive' | 'outline' {
    if (score == null) return 'outline'
    if (score >= 80) return 'default'
    if (score >= 60) return 'secondary'
    return 'destructive'
}

// Seniority/domain verdict pill color, reusing the modal's palette (no new colors):
// a clean match is green, a hard mismatch red, everything in between (adjacent, or an
// off-level too_junior/too_senior) amber.
function verdictClass(v: string): string {
    if (v === 'match') return 'bg-emerald-500/15 text-emerald-700 border-transparent'
    if (v === 'mismatch') return 'bg-red-500/15 text-red-700 border-transparent'
    return 'bg-amber-500/15 text-amber-700 border-transparent'
}

// Human label for a verdict token ("too_junior" → "Too junior", "adjacent" → "Adjacent").
function verdictLabel(v: string): string {
    if (v === 'too_junior') return 'Too junior'
    if (v === 'too_senior') return 'Too senior'
    return cap(v)
}

// Which résumé version the scorer picked as the best fit — shown next to the score so
// you know which one to submit. Unknown labels fall through as-is.
const RESUME_LABELS: Record<string, string> = { swe: 'SWE', quant_dev: 'Quant Dev' }

interface ParsedDetail {
    disqualificationReason: string
    seniorityVerdict: string
    seniorityNote: string
    domainVerdict: string
    domainNote: string
    firstMissing: string
    summary: string
    reasoning: string
    recommendedResume: string
}

// The minimal slice of the worker's score_detail the why-cell needs. Parses the same
// { assessment:{domain,must_haves,summary}, disqualification_reason } shape the modal
// reads; tolerant of bad JSON / pre-S2.1 rows (returns null / empty fields).
function parseDetail(raw?: string | null): ParsedDetail | null {
    if (!raw) return null
    let p: any
    try { p = JSON.parse(raw) } catch { return null }
    if (!p || typeof p !== 'object') return null
    const a = p.assessment && typeof p.assessment === 'object' ? p.assessment : null
    const missing = Array.isArray(a?.must_haves?.missing) ? a.must_haves.missing.map(String) : []
    return {
        disqualificationReason: String(p.disqualification_reason ?? ''),
        seniorityVerdict: String(a?.seniority?.verdict ?? ''),
        seniorityNote: String(a?.seniority?.note ?? ''),
        domainVerdict: String(a?.domain?.verdict ?? ''),
        domainNote: String(a?.domain?.note ?? ''),
        firstMissing: missing.length > 0 ? String(missing[0]) : '',
        summary: String(a?.summary ?? ''),
        reasoning: String(p.reasoning ?? ''),
        recommendedResume: String(p.recommended_resume ?? ''),
    }
}

// The signature element: a bucket-aware "why is this row here" subline under the role
// title, scannable at a glance so you don't open each posting.
function WhyCell({ bucket, job, detail }: { bucket: JobBucket; job: JobPosting; detail: ParsedDetail | null }) {
    if (bucket === 'belowbar') {
        // The shape of the shortfall: a pill for each of seniority/domain that isn't a
        // clean match (too_junior, adjacent, mismatch…), then the specific gap.
        const pills = [detail?.seniorityVerdict, detail?.domainVerdict]
            .filter((v): v is string => !!v && v !== 'match')
        const gap = detail?.firstMissing
            ? `missing: ${detail.firstMissing}`
            : (detail?.summary || detail?.domainNote || detail?.seniorityNote || '')
        // Structured assessment (post round-2) is preferred; legacy rows with no
        // scorecard fall back to the one-line `reasoning` so Below bar still says WHY
        // it fell short, not just the score.
        if (pills.length === 0 && !gap) {
            const why = detail?.reasoning ?? ''
            if (!why) return null
            return (
                <div className="mt-0.5 truncate text-[11px] text-muted-foreground" title={why}>
                    {why}
                </div>
            )
        }
        return (
            <div className="mt-0.5 flex items-center gap-1 min-w-0 text-[11px]">
                {pills.map((v) => (
                    <Badge
                        key={v}
                        variant="secondary"
                        className={`${verdictClass(v)} shrink-0 px-1.5 py-0 text-[10px] font-medium`}
                    >
                        {verdictLabel(v)}
                    </Badge>
                ))}
                {pills.length > 0 && gap && <span className="shrink-0 text-muted-foreground">·</span>}
                {gap && (
                    <span className="truncate min-w-0 text-muted-foreground" title={gap}>
                        {gap}
                    </span>
                )}
            </div>
        )
    }

    if (bucket === 'discarded') {
        const reason = detail?.disqualificationReason || 'disqualified'
        return (
            <div className="mt-0.5 truncate text-[11px] font-medium text-red-600" title={reason}>
                ✕ {reason}
            </div>
        )
    }

    if (bucket === 'lowcontext') {
        const len = (job.description ?? '').trim().length
        return (
            <div className="mt-0.5 text-[11px] text-muted-foreground">
                Thin JD ({len} chars)
            </div>
        )
    }

    if (bucket === 'failed') {
        const err = job.pipeline_error || 'Pipeline failed'
        return (
            <div className="mt-0.5 truncate text-[11px] text-muted-foreground" title={err}>
                {err}
            </div>
        )
    }

    // matched — keep it quiet; the score leads. Optional one-line summary, or nothing.
    if (detail?.summary) {
        return (
            <div className="mt-0.5 truncate text-[11px] text-muted-foreground" title={detail.summary}>
                {detail.summary}
            </div>
        )
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
    onBulkRemove,
    onBulkReopen,
    onRemoveAllInView,
}: DiscoveredJobsTableProps) {
    const [search, setSearch] = useState('')
    const [bucket, setBucket] = useState<JobBucket>('matched')
    const [minScore, setMinScore] = useState('')
    const [sort, setSort] = useState<JobSort>('score')
    // Discarded-only sub-filter: which hard-constraint cause disqualified the row.
    const [cause, setCause] = useState<'all' | DisqualifyCause>('all')

    const [selected, setSelected] = useState<Set<number>>(new Set())
    // Whenever the visible row set changes (page / filter / post-action refresh),
    // drop the selection — stale ids must never carry across views.
    useEffect(() => { setSelected(new Set()) }, [data])

    const allSelected = data.length > 0 && data.every((j) => selected.has(j.id))
    const toggleAll = () => setSelected(allSelected ? new Set() : new Set(data.map((j) => j.id)))
    const toggleOne = (id: number) =>
        setSelected((prev) => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id); else next.add(id)
            return next
        })
    const ids = () => [...selected]

    const stableFilterChange = useCallback(onFilterChange, [])

    useEffect(() => {
        const timer = setTimeout(() => {
            stableFilterChange({
                search,
                bucket,
                minScore: minScore === '' ? undefined : Number(minScore),
                cause: bucket === 'discarded' && cause !== 'all' ? cause : undefined,
                sort,
            })
        }, 300)
        return () => clearTimeout(timer)
    }, [search, bucket, minScore, cause, sort, stableFilterChange])

    return (
        <div className="space-y-4">
            {selected.size > 0 && (
                <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
                    <span className="font-medium">{selected.size} selected</span>
                    {bucket === 'discarded' && (
                        <Button variant="outline" size="sm" onClick={() => onBulkReopen(ids())}>
                            Reopen selected
                        </Button>
                    )}
                    <Button variant="destructive" size="sm" onClick={() => onBulkRemove(ids())}>
                        Remove selected
                    </Button>
                </div>
            )}
            {/* Bucket navigation — its own row, above the within-bucket filters. */}
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
            <div className="flex flex-col sm:flex-row gap-3 sm:items-center">
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
                <Select value={sort} onValueChange={(v) => setSort(v as JobSort)}>
                    <SelectTrigger className="w-[150px]" aria-label="Sort by">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="score">Best match</SelectItem>
                        <SelectItem value="posted">Newest posted</SelectItem>
                    </SelectContent>
                </Select>
                {bucket === 'discarded' && (
                    <>
                        <Select value={cause} onValueChange={(v) => setCause(v as 'all' | DisqualifyCause)}>
                            <SelectTrigger className="w-[170px]" aria-label="Disqualification cause">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {CAUSES.map((c) => (
                                    <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => onRemoveAllInView({
                                bucket,
                                search,
                                minScore: minScore === '' ? undefined : Number(minScore),
                                cause: bucket === 'discarded' && cause !== 'all' ? cause : undefined,
                            })}
                        >
                            Remove all in view
                        </Button>
                    </>
                )}
            </div>

            <div className="rounded-md border overflow-hidden">
                <Table className="table-fixed w-full">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[4%]">
                                <input
                                    type="checkbox"
                                    aria-label="Select all"
                                    checked={allSelected}
                                    onChange={toggleAll}
                                    className="h-4 w-4 align-middle"
                                />
                            </TableHead>
                            <TableHead className="w-[22%] whitespace-normal">Company</TableHead>
                            <TableHead className="w-[34%] whitespace-normal">Role</TableHead>
                            <TableHead className="w-[12%] whitespace-normal">Score</TableHead>
                            <TableHead className="w-[12%] whitespace-normal">Dates</TableHead>
                            <TableHead className="w-[16%] whitespace-normal text-right">Actions</TableHead>
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
                                const detail = parseDetail(job.score_detail)
                                return (
                                <TableRow key={job.id}>
                                    <TableCell className="align-top">
                                        <input
                                            type="checkbox"
                                            aria-label={`Select ${job.job_title}`}
                                            checked={selected.has(job.id)}
                                            onChange={() => toggleOne(job.id)}
                                            className="h-4 w-4 align-middle"
                                        />
                                    </TableCell>
                                    <TableCell className="whitespace-normal align-top">
                                        <div className="truncate text-sm font-medium" title={job.company_name}>
                                            {job.company_name}
                                        </div>
                                        {job.location && (
                                            <div className="truncate text-xs text-muted-foreground" title={job.location}>
                                                {job.location}
                                            </div>
                                        )}
                                        <span className="mt-1 inline-block max-w-full truncate rounded bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-secondary-foreground">
                                            {job.source}
                                        </span>
                                    </TableCell>
                                    <TableCell className="whitespace-normal align-top text-sm">
                                        <a
                                            href={safeHref(job.job_url)}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="block truncate font-medium text-foreground hover:underline"
                                            title={job.job_title}
                                        >
                                            {job.job_title}
                                        </a>
                                        <WhyCell bucket={bucket} job={job} detail={detail} />
                                    </TableCell>
                                    <TableCell className="align-top">
                                        <Badge variant={scoreVariant(job.score)}>
                                            {job.score ?? '—'}
                                        </Badge>
                                        {detail?.recommendedResume && (
                                            <div
                                                className="mt-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground"
                                                title={`Recommended résumé: ${RESUME_LABELS[detail.recommendedResume] ?? detail.recommendedResume}`}
                                            >
                                                {RESUME_LABELS[detail.recommendedResume] ?? detail.recommendedResume}
                                            </div>
                                        )}
                                    </TableCell>
                                    <TableCell className="align-top whitespace-normal text-xs">
                                        <div className="text-foreground">Posted {fmtDate(job.posted_at)}</div>
                                        <div className="text-muted-foreground">Fetched {fmtDate(job.created_at)}</div>
                                    </TableCell>
                                    <TableCell className="align-top text-right">
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
                                                    title="Remove"
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
