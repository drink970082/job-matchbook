'use client'

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
import { LOW_CONTEXT_MAX_DESCRIPTION_LENGTH } from '@/lib/constants'
import type { JobSort, JobViewScope, JobSearchScope, JobStage, JobStageFilter } from '@/lib/job-actions'
import type { ScreenOutcome, ScreenSummary, LegacyScreenEvidence } from '@/lib/screen-summary'
import { TRIAGE_STATUS_LABELS } from '@/lib/triage-summary'
import type { JobTriageSummary } from '@/lib/triage-summary'
import type { SourceLifecycleSummary, SourceFreshness } from '@/lib/source-lifecycle'
import { FileText, CheckCircle2 } from 'lucide-react'

export interface JobJev {
    status: string
    model_status: string
    reasons: string[]
    override: { decision: string; reason: string | null; actor: string | null; set_at: string | null; applies: boolean } | null
}

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
    jev?: JobJev
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
    counts?: Partial<Record<JobStage, number>>
    loading: boolean
    loadError: boolean
    onPageChange: (page: number) => void
    onFilterChange: (filters: JobTableFilters) => void
    onMarkApplied: (id: number, scope: JobViewScope) => void
    onViewJD: (id: number, scope: JobViewScope) => void
}

// The funnel, in pipeline order: rule -> screen -> JEV -> keep. Keep is the default.
export const STAGES: { value: JobStageFilter; label: string }[] = [
    { value: 'keep', label: 'Keep' },
    { value: 'unassessed', label: 'Unassessed' },
    { value: 'jev_skip', label: 'JEV skip' },
    { value: 'screen_rejected', label: 'Screen rejected' },
    { value: 'rule_rejected', label: 'Rule rejected' },
    { value: 'other', label: 'Applied / closed' },
    { value: 'all', label: 'All' },
]

const JEV_REASON_LABELS: Record<string, string> = {
    preference_weak: 'weak match to your preferences',
    required_yoe_3_plus: 'asks for 3+ years',
    required_yoe_above_candidate: 'asks for more years than you have',
}

const JEV_STATUS_LABELS: Record<string, string> = {
    keep: 'Keep', skip: 'Skip', unassessed: 'Not assessed', failed: 'Assessment failed', stale: 'Stale verdict',
}

const SCREEN_OUTCOMES: { value: 'all' | ScreenOutcome; label: string }[] = [
    { value: 'all', label: 'All screen outcomes' },
    { value: 'not_screened', label: 'No standalone record' },
    { value: 'provider_error', label: 'Provider error' },
    { value: 'disqualified', label: 'Disqualified (advisory)' },
    { value: 'no_disqualifier_found', label: 'No disqualifier found' },
    { value: 'unknown', label: 'Unknown' },
]

const SEARCH_SCOPES: { value: JobSearchScope; label: string }[] = [
    { value: 'metadata', label: 'Metadata' },
    { value: 'all_text', label: 'All text, including JD' },
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

function screenOutcomeLabel(outcome?: ScreenOutcome): string {
    switch (outcome) {
        case 'not_screened': return 'No standalone record'
        case 'provider_error': return 'Provider error'
        case 'disqualified': return 'Disqualified'
        case 'no_disqualifier_found': return 'No disqualifier found'
        default: return 'Unknown'
    }
}

function ScreenCell({ job, includeTriage = false }: { job: JobPosting; includeTriage?: boolean }) {
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
            {includeTriage && job.triage_summary && (
                <Badge
                    variant="secondary"
                    title={`${job.triage_summary.reason} · Evidence: ${job.triage_summary.provenance}`}
                >
                    Triage · {TRIAGE_STATUS_LABELS[job.triage_summary.status]}
                </Badge>
            )}
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
            {(screen || combinedScreen) && (
                <span className="text-muted-foreground">
                    {[screen, combinedScreen].filter(Boolean).join(' · ')}
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


// Why a posting sits in its stage: JEV's verdict and reasons, and the operator's override
// when there is one (MCP override_triage; the dashboard does not set it).
function JevCell({ job }: { job: JobPosting }) {
    const jev = job.jev
    if (!jev) return null
    const override = jev.override
    return (
        <div className="space-y-1 text-[11px]">
            <Badge variant={jev.status === 'keep' ? 'default' : jev.status === 'skip' ? 'destructive' : 'outline'}>
                {JEV_STATUS_LABELS[jev.status] ?? jev.status}
            </Badge>
            {jev.reasons.map((r) => (
                <div key={r} className="text-muted-foreground">{JEV_REASON_LABELS[r] ?? r}</div>
            ))}
            {override && (
                <div className="text-muted-foreground" title={override.reason ?? undefined}>
                    {override.applies
                        ? `Override: ${override.decision} (model said ${JEV_STATUS_LABELS[jev.model_status] ?? jev.model_status})`
                        : `Override ${override.decision} lapsed (content changed)`}
                </div>
            )}
        </div>
    )
}

export function DiscoveredJobsTable({
    data,
    total,
    page,
    size,
    filters,
    counts,
    loading,
    loadError,
    onPageChange,
    onFilterChange,
    onMarkApplied,
    onViewJD,
}: DiscoveredJobsTableProps) {
    const stage = filters.stage ?? 'keep'
    const search = filters.search ?? ''
    const sort = filters.sort ?? 'created'
    const searchScope = filters.searchScope ?? 'metadata'
    const screenOutcome = filters.screenOutcome ?? 'all'
    const updateFilters = (patch: Partial<JobTableFilters>) => onFilterChange({ ...filters, ...patch })
    // Every stage empty (or, before the counts arrive, an unfiltered All view) means the
    // inventory itself is empty, not that a filter excluded everything.
    const inventoryEmpty = counts
        ? Object.values(counts).every((n) => !n)
        : stage === 'all' && !search && screenOutcome === 'all'

    return (
        <div className="space-y-4">
            <div className="inline-flex flex-wrap items-center gap-1 rounded-lg border bg-muted/40 p-1" role="tablist" aria-label="Job stage">
                {STAGES.map((s) => (
                    <button
                        key={s.value}
                        type="button"
                        role="tab"
                        aria-selected={stage === s.value}
                        onClick={() => updateFilters({ stage: s.value })}
                        className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                            stage === s.value
                                ? 'bg-background shadow-sm text-foreground'
                                : 'text-muted-foreground hover:text-foreground'
                        }`}
                    >
                        {s.label}
                        {s.value !== 'all' && counts?.[s.value as JobStage] != null && (
                            <span className="ml-1.5 text-xs text-muted-foreground">{counts[s.value as JobStage]}</span>
                        )}
                    </button>
                ))}
            </div>
            <div className="flex flex-row gap-3 items-center">
                <div className="flex-1">
                    <Input
                        placeholder="Search companies, roles, or locations..."
                        maxLength={200}
                        value={search}
                        onChange={(e) => updateFilters({ search: e.target.value })}
                    />
                </div>
                <Select value={sort} onValueChange={(v) => updateFilters({ sort: v as JobSort })}>
                    <SelectTrigger className="w-[160px]" aria-label="Sort by">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="created">Newest fetched</SelectItem>
                        <SelectItem value="posted">Newest posted</SelectItem>
                    </SelectContent>
                </Select>
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
                <Select value={searchScope} onValueChange={(value) => updateFilters({ searchScope: value as JobSearchScope })}>
                    <SelectTrigger className="w-[175px]" aria-label="Search scope">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {SEARCH_SCOPES.map((item) => (
                            <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>

            <div className="rounded-md border overflow-hidden">
                <Table className="table-fixed w-full">
                    <TableHeader>
                        <TableRow>
                            <TableHead className="w-[22%] whitespace-normal">Company</TableHead>
                            <TableHead className="w-[40%] whitespace-normal">Role</TableHead>
                            <TableHead className="w-[16%] whitespace-normal">JEV</TableHead>
                            <TableHead className="w-[12%] whitespace-normal">Dates</TableHead>
                            <TableHead className="w-[10%] whitespace-normal text-right">Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {loading || loadError || data.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                                    {loading ? 'Loading jobs...'
                                        : loadError ? 'Could not load jobs. Change a filter to try again.'
                                            : inventoryEmpty
                                                ? 'No jobs in inventory yet.'
                                                : 'No jobs match these filters.'}
                                </TableCell>
                            </TableRow>
                        ) : (
                            data.map((job) => {
                                const shortDescription = descriptionLabel(job.description)
                                return (
                                <TableRow key={job.id}>
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
                                        {(stage === 'all' || stage === 'other') && (
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
                                        <ScreenCell job={job} includeTriage={stage === 'all' || stage === 'rule_rejected' || stage === 'screen_rejected'} />
                                        <SourceCell job={job} />
                                        {shortDescription && (
                                            <div className="mt-1 text-[11px] text-muted-foreground">{shortDescription}</div>
                                        )}
                                    </TableCell>
                                    <TableCell className="align-top whitespace-normal">
                                        <JevCell job={job} />
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
                                                onClick={() => onViewJD(job.id, filters)}
                                                title="View JD"
                                                className="h-7 w-7"
                                            >
                                                <FileText className="h-3.5 w-3.5" />
                                            </Button>
                                            {job.pipeline_status === 'applied' ? (
                                                <Badge variant="secondary" className="mr-1">Applied</Badge>
                                            ) : job.pipeline_status !== 'removed' && (
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    onClick={() => onMarkApplied(job.id, filters)}
                                                    title="Mark Applied"
                                                    className="h-7 w-7 text-emerald-600 hover:text-emerald-600"
                                                >
                                                    <CheckCircle2 className="h-3.5 w-3.5" />
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
