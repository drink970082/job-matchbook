'use client'

import { useEffect, useState } from 'react'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { todayISO } from '@/lib/utils'
import type { AppliedMatch } from './DiscoveredJobsTable'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'

interface ApplyCategoryDialogProps {
    open: boolean
    categories: string[]
    companyName?: string
    jobTitle?: string
    match?: AppliedMatch | null // an unlinked application that looks like this job (#241)
    onConfirm: (category: string, date: string, createNew: boolean) => void | Promise<void>
    onLink: (applicationId: number) => void | Promise<void>
    onClose: () => void
}

// Pick the application category and date when marking a discovered job applied (instead of
// always defaulting to 'Others'). Defaults to the first category; editable later in
// the Applications table. The category vocabulary is user-configured (passed in). When an
// unlinked application already looks like this job, it offers linking that one instead.
export function ApplyCategoryDialog({ open, categories, companyName, jobTitle, match, onConfirm, onLink, onClose }: ApplyCategoryDialogProps) {
    const [category, setCategory] = useState<string>(categories[0] ?? '')
    const [date, setDate] = useState(todayISO())
    const [busy, setBusy] = useState(false)

    // One call at a time.
    const run = async (call: () => void | Promise<void>) => {
        setBusy(true)
        try {
            await call()
        } finally {
            setBusy(false)
        }
    }

    // Reset to the first category each time the dialog opens for a new job.
    useEffect(() => {
        if (open) {
            setCategory(categories[0] ?? '')
            setDate(todayISO())
            setBusy(false)
        }
    }, [open, categories])

    return (
        <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
            <DialogContent className="max-w-[420px]">
                <DialogHeader>
                    <DialogTitle>Mark applied</DialogTitle>
                </DialogHeader>
                <div className="space-y-3">
                    {(companyName || jobTitle) && (
                        <p className="text-sm text-muted-foreground">
                            {companyName}
                            {companyName && jobTitle ? ' — ' : ''}
                            {jobTitle}
                        </p>
                    )}
                    {match && (
                        <div role="alert" className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
                            <p>
                                You may have applied already: application #{match.id}, {match.company_name} - {match.job_title},
                                applied {match.date_applied} ({match.tier === 1 ? 'same posting' : 'same company and title'}).
                            </p>
                            <Button size="sm" disabled={busy} onClick={() => run(() => onLink(match.id))}>Link to application #{match.id}</Button>
                        </div>
                    )}
                    <div className="space-y-1.5">
                        <label className="text-sm font-medium" htmlFor="apply-date">Date applied</label>
                        <Input id="apply-date" type="date" value={date} max={todayISO()} onChange={(e) => setDate(e.target.value)} />
                    </div>
                    <div className="space-y-1.5">
                        <label className="text-sm font-medium">Category</label>
                        <Select value={category} onValueChange={setCategory}>
                            <SelectTrigger aria-label="Category">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {categories.map((c) => (
                                    <SelectItem key={c} value={c}>{c}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose}>Cancel</Button>
                    <Button variant={match ? 'outline' : 'default'} disabled={!date || busy}
                        // The second click of a double click (detail 2) must not land on "It is a new application".
                        onClick={(e) => { if (e.detail < 2) run(() => onConfirm(category, date, !!match)) }}>
                        {match ? 'It is a new application' : 'Mark Applied'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
