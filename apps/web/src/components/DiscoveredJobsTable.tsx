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
import { verdictClass, verdictLabel, safeParseDetail, parseAssessment } from '@/lib/score-detail'
import { LOW_CONTEXT_MAX_DESCRIPTION_LENGTH } from '@/lib/constants'
import type { JobBucket, DisqualifyCause, JobSort, JobViewScope, JobSearchScope } from '@/lib/actions'
import type { ScreenOutcome, ScreenSummary, LegacyScreenEvidence } from '@/lib/screen-summary'
import type { SourceLifecycleSummary, SourceFreshness } from '@/lib/source-lifecycle'
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
    screen_summary?: ScreenSummary
    legacy_screen_evidence?: LegacyScreenEvidence
    source_lifecycle?: SourceLifecycleSummary
}

export type JobTableFilters = JobViewScope & { sortExplicit: boolean }

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
    onDiscard: (id: number, scope: JobViewScope) => void
    onReopen: (id: number, scope: JobViewScope) => void
    onViewJD: (id: number, scope: JobViewScope) => void
    onBulkRemove: (ids: number[], scope: JobViewScope) => void
    onBulkReopen: (ids: number[], scope: JobViewScope) => void
    onRemoveAllInView: (filter: JobViewScope) => void
}

const BUCKETS: { value: JobBucket; label: string }[] = [
    { value: 'all', label: 'All jobs' },
    { value: 'matched', label: 'Matched' },
    { value: 'belowbar', label: 'Below bar' },
    { value: 'discarded', label: 'Discarded' },
    { value: 'failed', label: 'Failed' },
    { value: 'lowcontext', label: 'Low-context' },
]

const SCREEN_OUTCOMES: { value: 'all' | ScreenOutcome; label: string }[] = [
    { value: 'all', label: 'All screen outcomes' },
    { value: 'not_screened', label: 'Not screened' },
    { value: 'provider_error', label: 'Provider error' },
    { value: 'disqualified', label: 'Disqualified (advisory)' },
    { value: 'no_disqualifier_found', label: 'No disqualifier found' },
    { value: 'unknown', label: 'Unknown' },
]

const SEARCH_SCOPES: { value: JobSearchScope; label: string }[] = [
    { value: 'metadata', label: 'Metadata' },
    { value: 'all_text', label: 'All text, including JD' },
]

// Disqualification-cause sub-filter for the Discarded bucket (mirrors DisqualifyCause).
const CAUSES: { value: 'all' | DisqualifyCause; label: string }[] = [
    { value: 'all', label: 'All causes' },
    { value: 'authorization', label: 'Work authorization' },
    { value: 'location', label: 'Location' },
    { value: 'degree', label: 'Degree' },
    { value: 'clearance', label: 'Clearance' },
    { value: 'internship', label: 'Internship' },
    { value: 'prefilter', label: 'Pre-filter (title/age)' },
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

function scoreVariant(score?: number | null): 'default' | 'secondary' | 'destructive' | 'outline' {
    if (score == null) return 'outline'
    if (score >= 80) return 'default'
    if (score >= 60) return 'secondary'
    return 'destructive'
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
    const p = safeParseDetail(raw)
    if (!p) return null
    const a = parseAssessment(p.assessment)
    return {
        disqualificationReason: String(p.disqualification_reason ?? ''),
        seniorityVerdict: a?.seniority.verdict ?? '',
        seniorityNote: a?.seniority.note ?? '',
        domainVerdict: a?.domain.verdict ?? '',
        domainNote: a?.domain.note ?? '',
        firstMissing: a?.mustHaves.missing[0] ?? '',
        summary: a?.summary ?? '',
        // Coerced HERE rather than in the shared parser: the modal deliberately reads
        // these two differently (a non-string recommended_resume is 'absent' there,
        // '5' here). Unifying would change one component's output on malformed input.
        reasoning: String(p.reasoning ?? ''),
        recommendedResume: String(p.recommended_resume ?? ''),
    }
}

// The shape of the shortfall: a pill for each of seniority/domain that isn't a clean
// match (too_junior, adjacent, mismatch…), then the specific gap. Shared by Below bar
// (near misses) and the fit-verdict half of Discarded — the two differ only in WHICH
// verdicts land them there, not in how the shortfall reads.
function VerdictShortfall({ detail }: { detail: ParsedDetail | null }) {
    const pills = [detail?.seniorityVerdict, detail?.domainVerdict]
        .filter((v): v is string => !!v && v !== 'match')
    const gap = detail?.firstMissing
        ? `missing: ${detail.firstMissing}`
        : (detail?.summary || detail?.domainNote || detail?.seniorityNote || '')
    // Structured assessment (post round-2) is preferred; legacy rows with no scorecard
    // fall back to the one-line `reasoning` so the row still says WHY it fell short,
    // not just the score.
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

// The signature element: a bucket-aware "why is this row here" subline under the role
// title, scannable at a glance so you don't open each posting.
function WhyCell({ bucket, job, detail }: { bucket: JobBucket; job: JobPosting; detail: ParsedDetail | null }) {
    if (bucket === 'belowbar') return <VerdictShortfall detail={detail} />

    if (bucket === 'discarded') {
        // Two populations share this bucket (see actions.ts). A hard-constraint screen
        // failure has a keyed disqualification_reason; a fit-verdict reject has none, and
        // reads as the same shortfall line Below bar uses. Falling back to the literal
        // "disqualified" for a row that was never disqualified would be a lie.
        const reason = detail?.disqualificationReason
        if (!reason) return <VerdictShortfall detail={detail} />
        return (
            <div className="mt-0.5 truncate text-[11px] font-medium text-red-600" title={reason}>
                ✕ {reason}
            </div>
        )
    }

    if (bucket === 'lowcontext') {
        // Low-context has TWO causes (actions.ts lowContextIds) and they read differently:
        // a genuinely short body, or a full-length JD the fit scorer itself flagged as
        // too boilerplate/truncated to trust. Reporting a 4,560-char JD as "Thin JD" was
        // simply wrong — say which rule caught it.
        const len = (job.description ?? '').trim().length
        const why = len < LOW_CONTEXT_MAX_DESCRIPTION_LENGTH
            ? `Thin JD (${len} chars)`
            : `Scorer found no usable detail (${len} chars)`
        return (
            <div className="mt-0.5 text-[11px] text-muted-foreground">
                {why}
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

function screenOutcomeLabel(outcome?: ScreenOutcome): string {
    switch (outcome) {
        case 'not_screened': return 'Not screened'
        case 'provider_error': return 'Provider error'
        case 'disqualified': return 'Disqualified'
        case 'no_disqualifier_found': return 'No disqualifier found'
        default: return 'Unknown'
    }
}

function ScreenCell({ job }: { job: JobPosting }) {
    const summary = job.screen_summary
    const label = screenOutcomeLabel(summary?.outcome)
    const legacy = job.legacy_screen_evidence?.available
    const provenance = [summary?.backend, summary?.model, summary?.effort]
        .filter((value): value is string => !!value)
    return (
        <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px]">
            <Badge variant="outline" title="Advisory only; this does not establish universal eligibility">
                Advisory · {label}
            </Badge>
            {summary?.reason && (
                <span className="truncate text-muted-foreground" title={summary.reason}>
                    {summary.reason}
                </span>
            )}
            {legacy && (
                <Badge variant="secondary" title="Older screen evidence stored with the fit result">
                    Legacy screen evidence
                </Badge>
            )}
            {(provenance.length > 0 || summary?.assessment_time) && (
                <span className="text-muted-foreground">
                    {[
                        ...provenance,
                        summary?.assessment_time ? `assessed ${summary.assessment_time}` : null,
                    ].filter(Boolean).join(' · ')}
                </span>
            )}
        </div>
    )
}

function freshnessLabel(value: SourceFreshness): string {
    switch (value) {
        case 'current': return 'current'
        case 'stale': return 'stale'
        case 'unknown': return 'unknown freshness'
        case 'provider_error': return 'provider error'
        default: return 'not assessed'
    }
}

function SourceCell({ job }: { job: JobPosting }) {
    const source = job.source_lifecycle
    if (!source) return null
    const stateLabel = source.state === 'available' ? 'Available'
        : source.state === 'closed' ? 'Closed' : 'Unknown'
    const attemptNote = source.last_check_outcome === 'inconclusive'
        ? `Latest detail attempt inconclusive${source.last_check_error_category ? ` (${source.last_check_error_category})` : ''}` +
            (source.last_check_attempted_at
                ? ` · attempted ${fmtDate(source.last_check_attempted_at)}` : '') +
            (source.last_checked_at
                ? ` · last conclusive detail check ${fmtDate(source.last_checked_at)}`
                : ' · no prior conclusive detail check')
        : source.last_checked_at
            ? `Last conclusive detail check ${fmtDate(source.last_checked_at)}`
            : 'No conclusive detail check'
    const seenNote = source.last_seen_at ? `Last seen ${fmtDate(source.last_seen_at)}` : null
    const fit = source.fit_freshness !== 'not_assessed'
        ? `Fit ${freshnessLabel(source.fit_freshness)}` : null
    const screen = source.screen_freshness !== 'not_assessed'
        ? `Standalone screen ${freshnessLabel(source.screen_freshness)}` : null
    const combinedScreen = job.legacy_screen_evidence?.available &&
        source.combined_screen_freshness !== 'not_assessed'
        ? `Fit-pipeline screen ${freshnessLabel(source.combined_screen_freshness)}` : null
    return (
        <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px]" title="Source availability and assessment freshness are separate from pipeline status">
            <Badge variant="outline">Source · {stateLabel}</Badge>
            {attemptNote && <span className="text-muted-foreground">{attemptNote}</span>}
            {seenNote && <span className="text-muted-foreground">{seenNote}</span>}
            {(fit || screen || combinedScreen) && (
                <span className="text-muted-foreground">
                    {[fit, screen, combinedScreen].filter(Boolean).join(' · ')}
                </span>
            )}
        </div>
    )
}

function pipelineStatusLabel(status?: string): string {
    const labels: Record<string, string> = {
        new: 'New',
        scored: 'Scored',
        notified: 'Notified',
        applied: 'Applied',
        discarded: 'Discarded',
        failed: 'Failed',
        expired: 'Expired',
        removed: 'Removed',
    }
    if (status && Object.prototype.hasOwnProperty.call(labels, status)) return labels[status]
    return `Unknown status (${status || 'missing'})`
}

function descriptionLabel(description?: string | null): string | null {
    if (description == null) return 'Description unavailable'
    const length = description.trim().length
    if (length === 0) return 'Description is empty'
    if (length < LOW_CONTEXT_MAX_DESCRIPTION_LENGTH) return `Short JD (${length} chars)`
    return null
}

function actionScope(filters: JobTableFilters): JobViewScope {
    const { sortExplicit: _sortExplicit, ...scope } = filters
    return scope
}

export function DiscoveredJobsTable({
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
}: DiscoveredJobsTableProps) {
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

    const bucket = filters.bucket
    const search = filters.search ?? ''
    const minScore = filters.minScore == null ? '' : String(filters.minScore)
    const sort = filters.sort ?? (bucket === 'all' ? 'created' : 'score')
    const cause = filters.cause ?? 'all'
    const searchScope = filters.searchScope ?? 'metadata'
    const screenOutcome = filters.screenOutcome ?? 'all'
    const scope = actionScope(filters)

    const updateFilters = (patch: Partial<JobTableFilters>) => {
        const next: JobTableFilters = { ...filters, ...patch }
        if (patch.bucket && patch.bucket !== bucket) {
            if (!filters.sortExplicit) next.sort = patch.bucket === 'all' ? 'created' : 'score'
            if (patch.bucket !== 'all') {
                next.screenOutcome = undefined
                next.searchScope = 'metadata'
            }
            if (patch.bucket !== 'discarded') next.cause = undefined
        }
        onFilterChange(next)
    }

    return (
        <div className="space-y-4">
            {bucket !== 'all' && selected.size > 0 && (
                <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
                    <span className="font-medium">{selected.size} selected</span>
                    {bucket === 'discarded' && (
                        <Button variant="outline" size="sm" onClick={() => onBulkReopen(ids(), scope)}>
                            Reopen selected
                        </Button>
                    )}
                    <Button variant="destructive" size="sm" onClick={() => onBulkRemove(ids(), scope)}>
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
                        onClick={() => updateFilters({ bucket: b.value })}
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
            <div className="flex flex-row gap-3 items-center">
                <div className="flex-1">
                    <Input
                        placeholder={bucket === 'all'
                            ? 'Search companies, roles, or locations...'
                            : 'Search companies or job titles...'}
                        maxLength={200}
                        value={search}
                        onChange={(e) => updateFilters({ search: e.target.value })}
                    />
                </div>
                <Input
                    type="number"
                    min={0}
                    max={100}
                    placeholder="Min score"
                    value={minScore}
                    onChange={(e) => updateFilters({ minScore: e.target.value === '' ? undefined : Number(e.target.value) })}
                    className="w-[110px]"
                    aria-label="Minimum score"
                />
                <Select value={sort} onValueChange={(v) => updateFilters({ sort: v as JobSort, sortExplicit: true })}>
                    <SelectTrigger className="w-[150px]" aria-label="Sort by">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="created">Discovery recency</SelectItem>
                        <SelectItem value="score">Best match</SelectItem>
                        <SelectItem value="posted">Newest posted</SelectItem>
                    </SelectContent>
                </Select>
                {bucket === 'all' && (
                    <>
                        <Select
                            value={screenOutcome}
                            onValueChange={(value) => updateFilters({ screenOutcome: value === 'all' ? undefined : value as ScreenOutcome })}
                        >
                            <SelectTrigger className="w-[190px]" aria-label="Standalone screen outcome">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {SCREEN_OUTCOMES.map((outcome) => (
                                    <SelectItem key={outcome.value} value={outcome.value}>{outcome.label}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <Select
                            value={searchScope}
                            onValueChange={(value) => updateFilters({ searchScope: value as JobSearchScope })}
                        >
                            <SelectTrigger className="w-[175px]" aria-label="Search scope">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {SEARCH_SCOPES.map((item) => (
                                    <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </>
                )}
                {bucket === 'discarded' && (
                    <>
                        <Select value={cause} onValueChange={(v) => updateFilters({ cause: v === 'all' ? undefined : v as DisqualifyCause })}>
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
                            onClick={() => onRemoveAllInView(scope)}
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
                            {bucket !== 'all' && (
                                <TableHead className="w-[4%]">
                                    <input
                                        type="checkbox"
                                        aria-label="Select all"
                                        checked={allSelected}
                                        onChange={toggleAll}
                                        className="h-4 w-4 align-middle"
                                    />
                                </TableHead>
                            )}
                            <TableHead className="w-[22%] whitespace-normal">Company</TableHead>
                            <TableHead className="w-[34%] whitespace-normal">Role</TableHead>
                            <TableHead className="w-[12%] whitespace-normal">{bucket === 'all' ? 'Fit' : 'Score'}</TableHead>
                            <TableHead className="w-[12%] whitespace-normal">Dates</TableHead>
                            <TableHead className="w-[16%] whitespace-normal text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading ? (
                            <TableRow>
                                <TableCell colSpan={bucket === 'all' ? 5 : 6} className="h-24 text-center text-muted-foreground">
                                    Loading jobs…
                                </TableCell>
                            </TableRow>
                        ) : loadError ? (
                            <TableRow>
                                <TableCell colSpan={bucket === 'all' ? 5 : 6} className="h-24 text-center text-muted-foreground">
                                    Could not load jobs. Change a filter to try again.
                                </TableCell>
                            </TableRow>
                        ) : data.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={bucket === 'all' ? 5 : 6} className="h-24 text-center text-muted-foreground">
                                    {bucket === 'all' && !search && screenOutcome === 'all' && minScore === ''
                                        ? 'No jobs in inventory yet.'
                                        : 'No jobs match these filters.'}
                                </TableCell>
                            </TableRow>
                        ) : (
                            data.map((job) => {
                                const detail = parseDetail(job.score_detail)
                                const shortDescription = descriptionLabel(job.description)
                                return (
                                <TableRow key={job.id}>
                                    {bucket !== 'all' && (
                                        <TableCell className="align-top">
                                            <input
                                                type="checkbox"
                                                aria-label={`Select ${job.job_title}`}
                                                checked={selected.has(job.id)}
                                                onChange={() => toggleOne(job.id)}
                                                className="h-4 w-4 align-middle"
                                            />
                                        </TableCell>
                                    )}
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
                                        {bucket === 'all' && (
                                            <div className="mt-1">
                                                <Badge variant="outline">{pipelineStatusLabel(job.pipeline_status)}</Badge>
                                            </div>
                                        )}
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
                                        {bucket === 'all' ? (
                                            <>
                                                <ScreenCell job={job} />
                                                <SourceCell job={job} />
                                                {shortDescription && (
                                                    <div className="mt-1 text-[11px] text-muted-foreground">{shortDescription}</div>
                                                )}
                                            </>
                                        ) : (
                                            <>
                                                <WhyCell bucket={bucket} job={job} detail={detail} />
                                                <SourceCell job={job} />
                                                {(job.screen_summary?.origin === 'job_screenings' || job.legacy_screen_evidence?.available) && (
                                                    <ScreenCell job={job} />
                                                )}
                                            </>
                                        )}
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
                                                onClick={() => onViewJD(job.id, scope)}
                                                title="View JD"
                                                className="h-7 w-7"
                                            >
                                                <FileText className="h-3.5 w-3.5" />
                                            </Button>
                                            {job.pipeline_status === 'applied' ? (
                                                <Badge variant="secondary" className="mr-1">Applied</Badge>
                                            ) : (
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => onMarkApplied(job.id, scope)}
                                                    title="Mark Applied"
                                                    className="h-7 w-7 text-emerald-600 hover:text-emerald-600"
                                                >
                                                    <CheckCircle2 className="h-3.5 w-3.5" />
                                                </Button>
                                            )}
                                            {job.pipeline_status === 'discarded' ? (
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => onReopen(job.id, scope)}
                                                    title="Reopen"
                                                    className="h-7 w-7"
                                                >
                                                    <RotateCcw className="h-3.5 w-3.5" />
                                                </Button>
                                            ) : job.pipeline_status !== 'applied' ? (
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => onDiscard(job.id, scope)}
                                                    title="Remove"
                                                    className="h-7 w-7 text-destructive hover:text-destructive"
                                                >
                                                    <XCircle className="h-3.5 w-3.5" />
                                                </Button>
                                            ) : null}
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
