'use client'

import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Download, ExternalLink, CheckCircle2, XCircle } from 'lucide-react'
import type { JobPosting } from './DiscoveredJobsTable'

interface JobDetailModalProps {
    isOpen: boolean
    onClose: () => void
    job: JobPosting
    onMarkApplied: (id: number) => void
    onDiscard: (id: number) => void
}

interface ScoreDetail {
    matched: string[]
    missing: string[]
    reasoning?: string
}

// The worker (apps/worker/ats_worker/pipeline.py) writes score_detail as
// { matched_keywords, missing_keywords, reasoning }. Normalize to a stable
// shape here, tolerating the legacy { matched, missing } keys too.
function parseScoreDetail(raw?: string | null): ScoreDetail | null {
    if (!raw) return null
    try {
        const p = JSON.parse(raw)
        if (!p || typeof p !== 'object') return null
        return {
            matched: p.matched_keywords ?? p.matched ?? [],
            missing: p.missing_keywords ?? p.missing ?? [],
            reasoning: p.reasoning,
        }
    } catch {
        return null
    }
}

export function JobDetailModal({ isOpen, onClose, job, onMarkApplied, onDiscard }: JobDetailModalProps) {
    const detail = parseScoreDetail(job.score_detail)

    return (
        <Dialog open={isOpen} onOpenChange={onClose}>
            <DialogContent className="sm:max-w-[640px]">
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

                <div className="space-y-6 max-h-[70vh] overflow-y-auto">
                    {/* Match analysis */}
                    {detail && (
                        <div className="space-y-3 border rounded-md p-4">
                            <h4 className="font-medium text-sm">Match Analysis</h4>
                            {detail.matched && detail.matched.length > 0 && (
                                <div>
                                    <div className="text-xs font-semibold text-emerald-700 mb-1">Matched</div>
                                    <div className="flex flex-wrap gap-1">
                                        {detail.matched.map((kw) => (
                                            <Badge key={kw} variant="secondary" className="bg-emerald-500/15 text-emerald-700 border-transparent">
                                                {kw}
                                            </Badge>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {detail.missing && detail.missing.length > 0 && (
                                <div>
                                    <div className="text-xs font-semibold text-red-700 mb-1">Missing</div>
                                    <div className="flex flex-wrap gap-1">
                                        {detail.missing.map((kw) => (
                                            <Badge key={kw} variant="secondary" className="bg-red-500/15 text-red-700 border-transparent">
                                                {kw}
                                            </Badge>
                                        ))}
                                    </div>
                                </div>
                            )}
                            {detail.reasoning && (
                                <div>
                                    <div className="text-xs font-semibold text-muted-foreground mb-1">Reasoning</div>
                                    <p className="text-sm text-muted-foreground">{detail.reasoning}</p>
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
                            <a href={job.job_url} target="_blank" rel="noopener noreferrer">
                                <ExternalLink className="mr-2 h-4 w-4" /> Open Posting
                            </a>
                        </Button>
                        {job.resume_path && (
                            <Button variant="outline" size="sm" asChild>
                                <a href={`/api/resume/${job.id}`} target="_blank" rel="noopener noreferrer">
                                    <Download className="mr-2 h-4 w-4" /> Download Resume (PDF)
                                </a>
                            </Button>
                        )}
                        <div className="flex-1" />
                        <Button size="sm" onClick={() => onMarkApplied(job.id)}>
                            <CheckCircle2 className="mr-2 h-4 w-4" /> Mark Applied
                        </Button>
                        <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => onDiscard(job.id)}>
                            <XCircle className="mr-2 h-4 w-4" /> Discard
                        </Button>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    )
}
