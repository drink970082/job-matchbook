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
    onConfirm: (category: string) => void
    onClose: () => void
}

// Pick the application category when marking a discovered job applied (instead of
// always defaulting to 'Others'). Defaults to the first category; editable later in
// the Applications table. The category vocabulary is user-configured (passed in).
export function ApplyCategoryDialog({ open, categories, companyName, jobTitle, onConfirm, onClose }: ApplyCategoryDialogProps) {
    const [category, setCategory] = useState<string>(categories[0] ?? '')

    // Reset to the first category each time the dialog opens for a new job.
    useEffect(() => {
        if (open) setCategory(categories[0] ?? '')
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
                    <Button onClick={() => onConfirm(category)}>Mark Applied</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
