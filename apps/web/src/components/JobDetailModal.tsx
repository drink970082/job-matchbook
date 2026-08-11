'use client'

import { Fragment, useState } from 'react'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ExternalLink, CheckCircle2, XCircle, RotateCcw, ChevronDown, ChevronRight, Ban } from 'lucide-react'
import { safeHref } from '@/lib/utils'
import { verdictClass, safeParseDetail } from '@/lib/score-detail'
import type { JobPosting } from './DiscoveredJobsTable'

interface JobDetailModalProps {
    isOpen: boolean
    onClose: () => void
    job: JobPosting
    onMarkApplied: (id: number) => void
    onDiscard: (id: number) => void
    onReopen: (id: number) => void
}

interface ScreenVerdict {
    pass: boolean
    note: string
}

interface Verdict {
    verdict: string
    note: string
}

// The S2.1 fit scorecard — per-dimension verdicts that supersede the flat
// matched/missing keyword lists + prose reasoning (kept as a legacy fallback below).
interface Assessment {
    seniority: Verdict
    domain: Verdict
    mustHaves: { met: string[]; missing: string[] }
    niceToHaves: { missing: string[] }
    summary: string
}

interface ScoreDetail {
    assessment: Assessment | null
    matched: string[]
    missing: string[]
    reasoning?: string
    disqualified: boolean
    disqualificationReason: string
    recommendedResume: string
    screen: [string, ScreenVerdict][]
}

function parseAssessment(a: any): Assessment | null {
    if (!a || typeof a !== 'object') return null
    const verdict = (v: any): Verdict => ({
        verdict: String(v?.verdict ?? ''),
        note: String(v?.note ?? ''),
    })
    const list = (x: any): string[] => (Array.isArray(x) ? x.map(String) : [])
    return {
        seniority: verdict(a.seniority),
        domain: verdict(a.domain),
        mustHaves: { met: list(a.must_haves?.met), missing: list(a.must_haves?.missing) },
        niceToHaves: { missing: list(a.nice_to_haves?.missing) },
        summary: String(a.summary ?? ''),
    }
}

// The worker (apps/worker/ats_worker/pipeline.py) writes score_detail as
// { matched_keywords, missing_keywords, reasoning, [disqualified,
// disqualification_reason], [screen] }. Normalize to a stable shape here,
// tolerating the legacy { matched, missing } keys too. `screen` is the
// per-requirement gate breakdown (which hard requirement passed/failed).
function parseScoreDetail(raw?: string | null): ScoreDetail | null {
    const p = safeParseDetail(raw)
    if (!p) return null
    const screen: [string, ScreenVerdict][] =
        p.screen && typeof p.screen === 'object'
            ? Object.entries(p.screen).map(([k, v]: [string, any]) => [
                  k,
                  { pass: v?.pass !== false, note: String(v?.note ?? '') },
              ])
            : []
    return {
        assessment: parseAssessment(p.assessment),
        matched: p.matched_keywords ?? p.matched ?? [],
        missing: p.missing_keywords ?? p.missing ?? [],
        reasoning: p.reasoning,
        disqualified: p.disqualified === true,
        disqualificationReason: p.disqualification_reason ?? '',
        recommendedResume:
            typeof p.recommended_resume === 'string' ? p.recommended_resume : '',
        screen,
    }
}

export function JobDetailModal({ isOpen, onClose, job, onMarkApplied, onDiscard, onReopen }: JobDetailModalProps) {
    const [showDetails, setShowDetails] = useState(false)
    const detail = parseScoreDetail(job.score_detail)
    const isDiscarded = job.pipeline_status === 'discarded'
    const assessment = detail?.assessment ?? null
    const hasMatchDetail = !!detail && (
        !!assessment ||
        (detail.matched?.length ?? 0) > 0 ||
        (detail.missing?.length ?? 0) > 0 ||
        !!detail.reasoning
    )

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
                            {job.score != null && <Badge>{job.score}</Badge>}
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

                    {/* Which resume version to send — decision-critical, always visible */}
                    {detail?.recommendedResume && (
                        <div className="flex items-center gap-2 text-sm">
                            <span className="text-xs font-semibold text-muted-foreground">
                                Recommended resume
                            </span>
                            <Badge variant="secondary">{detail.recommendedResume}</Badge>
                        </div>
                    )}

                    {/* Hard-requirement gate breakdown — which requirement passed/failed */}
                    {detail && detail.screen.length > 0 && (
                        <div className="rounded-md border p-3 space-y-1.5">
                            <div className="text-xs font-semibold text-muted-foreground mb-1">Screening</div>
                            {detail.screen.map(([key, v]) => (
                                <div key={key} className="flex items-start gap-2 text-sm">
                                    {v.pass ? (
                                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 mt-0.5 shrink-0" />
                                    ) : (
                                        <XCircle className="h-3.5 w-3.5 text-red-600 mt-0.5 shrink-0" />
                                    )}
                                    <span className="capitalize font-medium">{key}</span>
                                    {v.note && <span className="text-muted-foreground">— {v.note}</span>}
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Match analysis — tucked behind a toggle to keep the modal clean */}
                    {hasMatchDetail && (
                        <div className="border rounded-md">
                            <button
                                type="button"
                                onClick={() => setShowDetails((v) => !v)}
                                className="flex w-full items-center gap-1.5 p-3 text-sm font-medium hover:bg-muted/50"
                            >
                                {showDetails ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                                {assessment ? 'Fit assessment' : 'Match details & reasoning'}
                            </button>
                            {showDetails && (
                                <div className="space-y-3 px-4 pb-4">
                                    {assessment ? (
                                        <>
                                            {/* A 3-column grid, not per-row flex: the label and pill
                                                columns size to the widest cell, so the notes start at
                                                the same x on both rows. Under flex each row sized
                                                independently and a wide pill ("too_junior") pushed its
                                                note out of line with the row below. */}
                                            <div className="grid grid-cols-[max-content_max-content_1fr] items-start gap-x-2 gap-y-2">
                                                {([['Seniority', assessment.seniority], ['Domain', assessment.domain]] as const).map(([label, v]) => (
                                                    <Fragment key={label}>
                                                        <span className="text-xs font-semibold text-muted-foreground py-0.5">{label}</span>
                                                        <Badge variant="secondary" className={`${verdictClass(v.verdict)} justify-center`}>
                                                            {v.verdict || '—'}
                                                        </Badge>
                                                        <span className="text-xs text-muted-foreground py-0.5">{v.note}</span>
                                                    </Fragment>
                                                ))}
                                            </div>
                                            {assessment.mustHaves.met.length > 0 && (
                                                <div>
                                                    <div className="text-xs font-semibold text-emerald-700 mb-1">Must-haves met</div>
                                                    <div className="flex flex-wrap gap-1">
                                                        {assessment.mustHaves.met.map((kw) => (
                                                            <Badge key={kw} variant="secondary" className="bg-emerald-500/15 text-emerald-700 border-transparent">{kw}</Badge>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            {assessment.mustHaves.missing.length > 0 && (
                                                <div>
                                                    <div className="text-xs font-semibold text-red-700 mb-1">Must-haves missing</div>
                                                    <div className="flex flex-wrap gap-1">
                                                        {assessment.mustHaves.missing.map((kw) => (
                                                            <Badge key={kw} variant="secondary" className="bg-red-500/15 text-red-700 border-transparent">{kw}</Badge>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            {assessment.niceToHaves.missing.length > 0 && (
                                                <div>
                                                    <div className="text-xs font-semibold text-muted-foreground mb-1">Nice-to-haves missing (optional)</div>
                                                    <div className="flex flex-wrap gap-1">
                                                        {assessment.niceToHaves.missing.map((kw) => (
                                                            <Badge key={kw} variant="outline" className="text-muted-foreground">{kw}</Badge>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            {assessment.summary && (
                                                <div>
                                                    <div className="text-xs font-semibold text-muted-foreground mb-1">Summary</div>
                                                    <p className="text-sm text-muted-foreground">{assessment.summary}</p>
                                                </div>
                                            )}
                                        </>
                                    ) : (
                                        <>
                                            {detail!.matched && detail!.matched.length > 0 && (
                                                <div>
                                                    <div className="text-xs font-semibold text-emerald-700 mb-1">Matched</div>
                                                    <div className="flex flex-wrap gap-1">
                                                        {detail!.matched.map((kw) => (
                                                            <Badge key={kw} variant="secondary" className="bg-emerald-500/15 text-emerald-700 border-transparent">
                                                                {kw}
                                                            </Badge>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            {detail!.missing && detail!.missing.length > 0 && (
                                                <div>
                                                    <div className="text-xs font-semibold text-red-700 mb-1">Missing</div>
                                                    <div className="flex flex-wrap gap-1">
                                                        {detail!.missing.map((kw) => (
                                                            <Badge key={kw} variant="secondary" className="bg-red-500/15 text-red-700 border-transparent">
                                                                {kw}
                                                            </Badge>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                            {detail!.reasoning && (
                                                <div>
                                                    <div className="text-xs font-semibold text-muted-foreground mb-1">Reasoning</div>
                                                    <p className="text-sm text-muted-foreground">{detail!.reasoning}</p>
                                                </div>
                                            )}
                                        </>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Job description */}
                    <div className="space-y-2">
                        <h4 className="font-medium text-sm">Job Description</h4>
                        <div className="border rounded-md p-4 max-h-[260px] overflow-y-auto">
                            <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                                {job.description || 'No description available.'}
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
                        <Button size="sm" onClick={() => onMarkApplied(job.id)}>
                            <CheckCircle2 className="mr-2 h-4 w-4" /> Mark Applied
                        </Button>
                        {isDiscarded ? (
                            <Button variant="ghost" size="sm" onClick={() => onReopen(job.id)}>
                                <RotateCcw className="mr-2 h-4 w-4" /> Reopen
                            </Button>
                        ) : (
                            <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => onDiscard(job.id)}>
                                <XCircle className="mr-2 h-4 w-4" /> Remove
                            </Button>
                        )}
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    )
}
