'use client'

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Pagination } from './Pagination'
import { safeHref } from '@/lib/utils'
import type { JobStage, JobViewScope } from '@/lib/job-actions'
import type { ScreenSummary, LegacyScreenEvidence } from '@/lib/screen-summary'
import type { JobTriageSummary } from '@/lib/triage-summary'
import type { SourceLifecycleSummary } from '@/lib/source-lifecycle'
import { ExternalLink, FileText, CheckCircle2, EyeOff } from 'lucide-react'

// The triage reasons and the operator's override; the posting's effective status is
// JobPosting.status (the override if one exists, else the stored verdict).
export interface JobJev {
    reasons: string[]
    override: { decision: string; reason: string | null; actor: string | null; set_at: string | null } | null
}

// An unlinked application this posting matches (#241, lib/application-match.ts tier 1 or 2).
export interface AppliedMatch { id: number; tier: 1 | 2; company_name: string; job_title: string; date_applied: string }

export interface JobPosting {
    id: number
    source: string
    company_name: string
    job_title: string
    location?: string | null
    job_url: string
    description?: string | null
    score_detail?: string | null
    pipeline_status?: string
    pipeline_error?: string | null
    posted_at?: string | null
    created_at?: string | null
    stage?: JobStage
    status?: string
    verdict?: string
    profile_version?: number | null
    jev?: JobJev
    applied_match?: AppliedMatch | null
    screen_summary?: ScreenSummary
    legacy_screen_evidence?: LegacyScreenEvidence
    triage_summary?: JobTriageSummary
    source_lifecycle?: SourceLifecycleSummary
}

export type JobTableFilters = JobViewScope

interface DiscoveredJobsTableProps {
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
    onViewJD: (id: number, scope: JobViewScope) => void
    onNotInterested: (id: number) => void
}

const WITHIN: { value: string; label: string }[] = [
    { value: '', label: 'Any time' }, { value: '1', label: 'Posted today or yesterday' },
    { value: '7', label: 'Past 7 days' }, { value: '30', label: 'Past 30 days' },
]

// Calendar days from a YYYY-MM-DD date to the viewer's local today (null if unparseable).
function daysAgo(date: string | null | undefined, now: number): number | null {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(date ?? '')
    if (!m) return null
    const today = new Date(now)
    return Math.round((Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())
        - Date.UTC(+m[1], +m[2] - 1, +m[3])) / 86_400_000)
}

// "3d ago" from a YYYY-MM-DD posted date, counted in the viewer's calendar days.
export function postedAgo(posted: string | null | undefined, now = Date.now()): string {
    const days = daysAgo(posted, now)
    return days == null ? '' : days <= 0 ? 'today' : `${days}d ago`
}

// The viewer's local date N days ago: the same days postedAgo counts, so the filter
// and the row age agree.
export function localDateDaysAgo(n: number, now = Date.now()): string {
    const d = new Date(now)
    d.setDate(d.getDate() - n)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// Discovered Jobs as a job board (#207): title, company, location, posted age, actions.
export function DiscoveredJobsTable({
    data, total, page, size, filters, loading, loadError,
    onPageChange, onFilterChange, onMarkApplied, onViewJD, onNotInterested,
}: DiscoveredJobsTableProps) {
    const updateFilters = (patch: Partial<JobTableFilters>) => onFilterChange({ ...filters, ...patch })
    const filtered = Boolean(filters.search || filters.postedSince)
    const within = filters.postedSince ? String(daysAgo(filters.postedSince, Date.now())) : ''

    return (
        <div className="space-y-4">
            <div className="flex flex-row flex-wrap gap-3 items-center">
                <div className="flex-1 min-w-[16rem]">
                    <Input placeholder="Search companies, roles, or locations..." maxLength={200}
                        value={filters.search ?? ''} onChange={(e) => updateFilters({ search: e.target.value })} />
                </div>
                <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={filters.searchScope === 'all_text'}
                        onChange={(e) => updateFilters({ searchScope: e.target.checked ? 'all_text' : 'metadata' })} />
                    Search in JD
                </label>
                <select aria-label="Posted within" value={within}
                    onChange={(e) => updateFilters({ postedSince: e.target.value ? localDateDaysAgo(Number(e.target.value)) : undefined })}
                    className="h-9 rounded-md border bg-transparent px-3 text-sm">
                    {WITHIN.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
                </select>
            </div>

            <div className="rounded-md border overflow-hidden">
                <Table className="table-fixed w-full">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[38%]">Role</TableHead>
                            <TableHead className="w-[20%]">Company</TableHead>
                            <TableHead className="w-[18%]">Location</TableHead>
                            <TableHead className="w-[9%]">Posted</TableHead>
                            <TableHead className="w-[15%] text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading ? (
                            <TableRow><TableCell colSpan={5} className="h-24 text-center text-muted-foreground">Loading jobs...</TableCell></TableRow>
                        ) : loadError ? (
                            <TableRow><TableCell colSpan={5} className="h-24 text-center text-muted-foreground">Could not load jobs.</TableCell></TableRow>
                        ) : data.length === 0 ? (
                            <TableRow><TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                                {filtered ? 'No postings match these filters.' : 'No postings for you yet.'}
                            </TableCell></TableRow>
                        ) : data.map((job) => (
                            <TableRow key={job.id}>
                                <TableCell className="whitespace-normal break-words">
                                    {safeHref(job.job_url) === '#' ? <span className="font-medium">{job.job_title}</span> : (
                                        <a href={job.job_url} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
                                            {job.job_title}
                                        </a>
                                    )}
                                    {job.applied_match && (
                                        <div className="text-xs text-amber-700">You may have applied already (application #{job.applied_match.id})</div>
                                    )}
                                    {job.profile_version != null && (
                                        <div className="text-xs text-muted-foreground">Judged under profile v{job.profile_version}</div>
                                    )}
                                </TableCell>
                                <TableCell className="whitespace-normal break-words">{job.company_name}</TableCell>
                                <TableCell className="whitespace-normal break-words text-muted-foreground">{job.location}</TableCell>
                                <TableCell className="text-muted-foreground" title={job.posted_at ?? undefined}>{postedAgo(job.posted_at)}</TableCell>
                                <TableCell className="text-right">
                                    <div className="flex justify-end gap-0.5">
                                        {safeHref(job.job_url) !== '#' && (
                                            <Button asChild variant="ghost" size="icon" className="h-7 w-7" title="Apply">
                                                <a href={job.job_url} target="_blank" rel="noopener noreferrer" aria-label={`Apply: ${job.job_title}`}>
                                                    <ExternalLink className="h-3.5 w-3.5" />
                                                </a>
                                            </Button>
                                        )}
                                        <Button variant="ghost" size="icon" className="h-7 w-7 text-emerald-600 hover:text-emerald-600"
                                            title="Mark applied" aria-label={`Mark applied: ${job.job_title}`} onClick={() => onMarkApplied(job.id, filters)}>
                                            <CheckCircle2 className="h-3.5 w-3.5" />
                                        </Button>
                                        <Button variant="ghost" size="icon" className="h-7 w-7" title="Not interested"
                                            aria-label={`Not interested: ${job.job_title}`} onClick={() => onNotInterested(job.id)}>
                                            <EyeOff className="h-3.5 w-3.5" />
                                        </Button>
                                        <Button variant="ghost" size="icon" className="h-7 w-7" title="View JD"
                                            aria-label={`View JD: ${job.job_title}`} onClick={() => onViewJD(job.id, filters)}>
                                            <FileText className="h-3.5 w-3.5" />
                                        </Button>
                                    </div>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>

            <Pagination page={page} size={size} total={total} onPageChange={onPageChange} />
        </div>
    )
}
