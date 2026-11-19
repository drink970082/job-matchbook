'use client'

import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ExternalLink, CheckCircle2, XCircle, Ban } from 'lucide-react'
import { safeHref } from '@/lib/utils'
import { safeParseDetail } from '@/lib/score-detail'
import type { JobPosting } from './DiscoveredJobsTable'
import type { ScreenOutcome } from '@/lib/screen-summary'
import { TRIAGE_STATUS_LABELS } from '@/lib/triage-summary'

interface JobDetailModalProps {
    isOpen: boolean
    onClose: () => void
    job: JobPosting
    onMarkApplied: (id: number) => void
}

interface ScreenVerdict {
    pass: boolean | null
    note: string
}

interface ScoreDetail {
    disqualified: boolean
    disqualificationReason: string
    screen: [string, ScreenVerdict][]
}

// The screen half of the worker's score_detail ({ [disqualified,
// disqualification_reason], [screen] }); `screen` is the per-requirement gate
// breakdown. The retired fit scorer's fields in older rows are not shown.
function parseScoreDetail(raw?: string | null): ScoreDetail | null {
    const p = safeParseDetail(raw)
    if (!p) return null
    const screen: [string, ScreenVerdict][] =
        p.screen && typeof p.screen === 'object' && !Array.isArray(p.screen)
            ? Object.entries(p.screen).map(([k, v]: [string, any]) => [
                  k,
                  { pass: typeof v?.pass === 'boolean' ? v.pass : null, note: String(v?.note ?? '') },
              ])
            : []
    return {
        disqualified: p.disqualified === true,
        disqualificationReason: p.disqualification_reason ?? '',
        screen,
    }
}

function standaloneOutcomeLabel(outcome?: ScreenOutcome): string {
    switch (outcome) {
        case 'not_screened': return 'No standalone record'
        case 'provider_error': return 'Provider error'
        case 'disqualified': return 'Disqualified'
        case 'no_disqualifier_found': return 'No disqualifier found'
        default: return 'Unknown'
    }
}

function sourceFreshnessLabel(value?: string): string {
    if (value === 'current') return 'Current'
    if (value === 'stale') return 'Stale: assessment uses older source content'
    if (value === 'unknown') return 'Unknown: source revision was not recorded'
    if (value === 'provider_error') return 'Provider error'
    return 'Not assessed'
}

function sourceDate(value?: string | null): string | null {
    return value ? value.slice(0, 10) : null
}

export function JobDetailModal({ isOpen, onClose, job, onMarkApplied }: JobDetailModalProps) {
    const detail = parseScoreDetail(job.score_detail)

    return (
        <Dialog open={isOpen} onOpenChange={onClose}>
            <DialogContent className="max-w-[640px]">
                <DialogHeader>
                    <DialogTitle asChild>
                        <div className="flex justify-between items-start pr-6">
                            <div>
                                {job.company_name} — {job.job_title}
                                {job.location && (
                                    <span className="ml-2 px-1.5 py-0.5 rounded text-xs bg-secondary text-secondary-foreground">
                                        {job.location}
                                    </span>
                                )}
                            </div>
                        </div>
                    </DialogTitle>
                </DialogHeader>

                <div className="space-y-4 max-h-[70vh] overflow-y-auto">
                    {/* Decision summary — always visible, so the "why" is one glance away */}
                    {detail?.disqualified && detail.disqualificationReason && (
                        <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3">
                            <Ban className="h-4 w-4 text-red-700 mt-0.5 shrink-0" />
                            <div className="text-sm">
                                <span className="font-semibold text-red-700">Disqualified</span>
                                <span className="text-red-700/90"> — {detail.disqualificationReason}</span>
                            </div>
                        </div>
                    )}

                    {job.jev && (
                        <div className="rounded-md border p-3 space-y-1.5">
                            <div className="text-xs font-semibold text-muted-foreground">JEV keep/skip filter</div>
                            <div className="flex flex-wrap items-center gap-2">
                                <Badge variant={job.jev.status === 'keep' ? 'default' : job.jev.status === 'skip' ? 'destructive' : 'outline'}>
                                    {job.jev.status}
                                </Badge>
                                {job.jev.reasons.length > 0 && (
                                    <span className="text-sm text-muted-foreground">{job.jev.reasons.join(', ')}</span>
                                )}
                            </div>
                            {job.jev.override && (
                                <p className="text-xs text-muted-foreground">
                                    Override {job.jev.override.decision}
                                    {job.jev.override.applies ? ` (model: ${job.jev.model_status})` : ' lapsed: the posting changed since it was set'}
                                    {job.jev.override.reason ? ` - ${job.jev.override.reason}` : ''}
                                </p>
                            )}
                        </div>
                    )}

                    {job.source_lifecycle && (
                        <div className="rounded-md border p-3 space-y-1.5">
                            <div className="text-xs font-semibold text-muted-foreground">Source evidence</div>
                            <div className="flex flex-wrap items-center gap-2 text-sm">
                                <Badge variant="outline">{job.source_lifecycle.state === 'available'
                                    ? 'Available at source'
                                    : job.source_lifecycle.state === 'closed' ? 'Confirmed closed' : 'Source state unknown'}</Badge>
                                {job.source_lifecycle.content_revision != null && (
                                    <span className="text-xs text-muted-foreground">
                                        Content revision {job.source_lifecycle.content_revision}
                                    </span>
                                )}
                            </div>
                            <p className="text-xs text-muted-foreground">
                                {job.source_lifecycle.last_check_outcome === 'inconclusive'
                                    ? `Latest detail attempt inconclusive${job.source_lifecycle.last_check_error_category
                                        ? ` (${job.source_lifecycle.last_check_error_category})` : ''}` +
                                        (job.source_lifecycle.last_check_attempted_at
                                            ? ` · Attempted ${sourceDate(job.source_lifecycle.last_check_attempted_at)}` : '') +
                                        (job.source_lifecycle.last_checked_at
                                            ? ` · Last conclusive detail check ${sourceDate(job.source_lifecycle.last_checked_at)}`
                                            : ' · no prior conclusive detail check')
                                    : job.source_lifecycle.last_checked_at
                                        ? `Last conclusive detail check ${sourceDate(job.source_lifecycle.last_checked_at)}`
                                        : 'No conclusive detail check'}
                                {job.source_lifecycle.last_seen_at &&
                                    ` · Last seen ${sourceDate(job.source_lifecycle.last_seen_at)}`}
                            </p>
                            <p className="text-xs text-muted-foreground">
                                Standalone screen: {sourceFreshnessLabel(job.source_lifecycle.screen_freshness)}
                                {job.legacy_screen_evidence?.available && (
                                    <> · Fit-pipeline screen: {sourceFreshnessLabel(
                                        job.source_lifecycle.combined_screen_freshness)}</>
                                )}
                            </p>
                        </div>
                    )}

                    {job.triage_summary && (
                        <div className="rounded-md border p-3 space-y-1.5">
                            <div className="text-xs font-semibold text-muted-foreground">Job triage</div>
                            <div className="flex flex-wrap items-center gap-2">
                                <Badge variant="secondary">
                                    {TRIAGE_STATUS_LABELS[job.triage_summary.status]}
                                </Badge>
                                <span className="text-sm text-muted-foreground">{job.triage_summary.reason}</span>
                            </div>
                            <p className="text-xs text-muted-foreground">
                                Evidence: {job.triage_summary.provenance}. Candidate status means retained for fit research, not qualified.
                            </p>
                        </div>
                    )}

                    <div className="rounded-md border p-3 space-y-1.5">
                        <div className="text-xs font-semibold text-muted-foreground">Standalone advisory screen</div>
                        <div className="flex flex-wrap items-center gap-2">
                            <Badge variant="outline">Advisory · {standaloneOutcomeLabel(job.screen_summary?.outcome)}</Badge>
                            {job.screen_summary?.reason && (
                                <span className="text-sm text-muted-foreground">{job.screen_summary.reason}</span>
                            )}
                        </div>
                        {job.screen_summary?.origin === 'none' && (
                            <p className="text-xs text-muted-foreground">No standalone record.</p>
                        )}
                        {(job.screen_summary?.backend || job.screen_summary?.model || job.screen_summary?.effort || job.screen_summary?.assessment_time) && (
                            <p className="text-xs text-muted-foreground">
                                {[job.screen_summary.backend, job.screen_summary.model, job.screen_summary.effort,
                                    job.screen_summary.assessment_time && `assessed ${job.screen_summary.assessment_time}`]
                                    .filter(Boolean).join(' · ')}
                            </p>
                        )}
                    </div>

                    {/* Older fit-pipeline evidence remains distinct from the standalone result above. */}
                    {detail && detail.screen.length > 0 && (
                        <div className="rounded-md border p-3 space-y-1.5">
                            <div className="text-xs font-semibold text-muted-foreground mb-1">Legacy screen evidence in fit record</div>
                            <p className="text-xs text-muted-foreground">This evidence is separate from the standalone advisory result above.</p>
                            {detail.screen.map(([key, v]) => (
                                <div key={key} className="flex items-start gap-2 text-sm">
                                    {v.pass === true ? (
                                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 mt-0.5 shrink-0" />
                                    ) : v.pass === false ? (
                                        <XCircle className="h-3.5 w-3.5 text-red-600 mt-0.5 shrink-0" />
                                    ) : (
                                        <span className="h-3.5 w-3.5 text-muted-foreground">?</span>
                                    )}
                                    <span className="capitalize font-medium">{key}</span>
                                    <span className="text-muted-foreground">{v.pass === null ? 'Unknown' : v.pass ? 'Passed' : 'Failed'}</span>
                                    {v.note && <span className="text-muted-foreground">— {v.note}</span>}
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Job description */}
                    <div className="space-y-2">
                        <h4 className="font-medium text-sm">Job Description</h4>
                        <div className="border rounded-md p-4 max-h-[260px] overflow-y-auto">
                            <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                                {job.description == null
                                    ? 'Description unavailable.'
                                    : job.description.length === 0
                                        ? 'Description is empty.'
                                        : job.description}
                            </p>
                        </div>
                    </div>

                    {/* Links + actions */}
                    <div className="flex flex-wrap gap-2 border-t pt-4">
                        <Button variant="outline" size="sm" asChild>
                            <a href={safeHref(job.job_url)} target="_blank" rel="noopener noreferrer">
                                <ExternalLink className="mr-2 h-4 w-4" /> Open Posting
                            </a>
                        </Button>
                        <div className="flex-1" />
                        {job.pipeline_status !== 'applied' && job.pipeline_status !== 'removed' && (
                            <Button size="sm" onClick={() => onMarkApplied(job.id)}>
                                <CheckCircle2 className="mr-2 h-4 w-4" /> Mark Applied
                            </Button>
                        )}
                        {job.pipeline_status === 'applied' && <Badge variant="secondary">Applied</Badge>}
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    )
}
