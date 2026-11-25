'use client'

import { useEffect, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { getLinkSuggestions, linkApplication, type LinkSuggestions } from '@/lib/link-actions'
import { safeHref } from '@/lib/utils'
import { toast } from 'sonner'

const TIER_LABEL = { 1: 'Same posting', 2: 'Same company and title', 3: 'Same company' } as const

const hasCandidates = (i: LinkSuggestions) => i.suggestions.length > 0 || i.more > 0

interface LinkPostingsDialogProps {
    open: boolean
    applicationId: number | null // null: every unlinked application that has a candidate
    onClose: () => void
    onLinked: () => void
}

// Link unlinked applications to the postings they were made for (#241). Every link is one
// click on one posting; nothing is pre-selected.
export function LinkPostingsDialog({ open, applicationId, onClose, onLinked }: LinkPostingsDialogProps) {
    const [items, setItems] = useState<LinkSuggestions[] | null>(null)
    const [error, setError] = useState('')
    const [linking, setLinking] = useState(false)
    const version = useRef(0)

    useEffect(() => {
        const v = ++version.current
        if (!open) return
        setItems(null)
        setError('')
        getLinkSuggestions(applicationId === null ? {} : { applicationId }).then((res) => {
            if (v !== version.current) return
            if (res.success) setItems(res.data)
            else setError(res.error)
        }).catch(() => { if (v === version.current) setError('Could not load suggestions') })
    }, [open, applicationId])

    const link = async (appId: number, jobId: number) => {
        if (linking) return
        setLinking(true)
        const v = version.current // a reply that lands after the dialog moved on must not touch it
        try {
            const res = await linkApplication(appId, jobId)
            if (!res.success) return toast.error(res.error)
            toast.success('Linked')
            onLinked()
            if (v !== version.current) return
            // A posting links once: drop it from the other applications' lists too.
            const rest = (items ?? []).filter((i) => i.application.id !== appId)
                .map((i) => ({ ...i, suggestions: i.suggestions.filter((s) => s.job_id !== jobId) }))
                .filter(hasCandidates)
            setItems(rest)
            if (rest.length === 0) onClose()
        } catch {
            toast.error('Could not link the application')
        } finally {
            setLinking(false)
        }
    }

    return (
        <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
            <DialogContent className="max-w-[680px]">
                <DialogHeader>
                    <DialogTitle>Link applications to postings</DialogTitle>
                    <DialogDescription>
                        Pick the posting an application was made for. The posting is marked applied.
                    </DialogDescription>
                </DialogHeader>
                <div className="max-h-[65vh] space-y-4 overflow-y-auto">
                    {error && <p className="text-sm text-red-600">{error}</p>}
                    {!error && items === null && <p className="text-sm text-muted-foreground">Loading...</p>}
                    {!error && items !== null && !items.some(hasCandidates) && (
                        <p className="text-sm text-muted-foreground">No posting found for {applicationId === null ? 'any unlinked application' : 'this application'}.</p>
                    )}
                    {items?.filter(hasCandidates).map(({ application: a, suggestions, more }) => (
                        <section key={a.id} className="rounded-md border p-3" aria-label={`${a.company_name} - ${a.job_title}`}>
                            <h4 className="text-sm font-medium">{a.company_name} - {a.job_title}</h4>
                            <p className="mb-2 text-xs text-muted-foreground">Application #{a.id}, applied {a.date_applied}</p>
                            <ul className="space-y-1.5">
                                {suggestions.map((s) => (
                                    <li key={s.job_id} className="flex items-center justify-between gap-3 text-sm">
                                        <div className="min-w-0">
                                            {safeHref(s.job_url) === '#' ? <span>{s.job_title}</span> : (
                                                <a href={safeHref(s.job_url)} target="_blank" rel="noopener noreferrer" className="hover:underline">{s.job_title}</a>
                                            )}
                                            <div className="text-xs text-muted-foreground">
                                                {[TIER_LABEL[s.tier], s.company_name, s.location, s.posted_at && `posted ${s.posted_at}`,
                                                    s.source_state === 'closed' && 'closed'].filter(Boolean).join(', ')}
                                            </div>
                                        </div>
                                        <Button size="sm" variant="outline" disabled={linking}
                                            aria-label={`Link ${a.company_name} - ${a.job_title} to ${s.job_title} (job ${s.job_id})`}
                                            onClick={() => link(a.id, s.job_id)}>Link</Button>
                                    </li>
                                ))}
                            </ul>
                            {more > 0 && <p className="mt-2 text-xs text-muted-foreground">{more} more postings at this company{applicationId === null && ': use the Link button on the application'}.</p>}
                        </section>
                    ))}
                </div>
            </DialogContent>
        </Dialog>
    )
}
