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
import { setCategories } from '@/lib/actions'
import { toast } from 'sonner'
import { X, Plus } from 'lucide-react'

interface CategoriesDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    initial: string[]
    firstRun?: boolean
    onSaved: (list: string[]) => void
}

// Edit the application-category vocabulary — the labels shown in the Add form, the
// Mark-Applied dialog, the table filter, and the category donut. Free-form: add or
// remove anything; a removed category doesn't relabel applications already filed
// under it. Auto-opens once on first run (no categories saved yet).
export function CategoriesDialog({ open, onOpenChange, initial, firstRun, onSaved }: CategoriesDialogProps) {
    const [list, setList] = useState<string[]>(initial)
    const [draft, setDraft] = useState('')
    const [saving, setSaving] = useState(false)

    // Re-seed the editor from the current list whenever it (re)opens.
    useEffect(() => {
        if (open) { setList(initial); setDraft('') }
    }, [open, initial])

    const add = () => {
        const c = draft.trim()
        setDraft('')
        if (!c || list.some((x) => x.toLowerCase() === c.toLowerCase())) return
        setList([...list, c])
    }

    const remove = (i: number) => setList(list.filter((_, idx) => idx !== i))

    const save = async () => {
        setSaving(true)
        const result = await setCategories(list)
        setSaving(false)
        if (result.success) {
            toast.success('Categories saved')
            onSaved(result.data ?? list)
            onOpenChange(false)
        } else {
            toast.error(result.error)
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-[440px]">
                <DialogHeader>
                    <DialogTitle>{firstRun ? 'Choose your job categories' : 'Edit categories'}</DialogTitle>
                </DialogHeader>
                <p className="text-sm text-muted-foreground">
                    These label your applications and group the category chart. Add or remove to
                    match the roles you actually apply to — just labels you can edit anytime.
                </p>
                <div className="space-y-2">
                    <div className="flex flex-wrap gap-1.5">
                        {list.map((c, i) => (
                            <span key={c} className="inline-flex items-center gap-1 rounded-full border bg-muted/50 px-2.5 py-1 text-sm">
                                {c}
                                <button
                                    type="button"
                                    aria-label={`Remove ${c}`}
                                    onClick={() => remove(i)}
                                    className="text-muted-foreground hover:text-foreground"
                                >
                                    <X className="h-3 w-3" />
                                </button>
                            </span>
                        ))}
                        {list.length === 0 && (
                            <span className="text-sm text-muted-foreground">No categories yet — add at least one.</span>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <Input
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
                            placeholder="Add a category…"
                            aria-label="New category"
                        />
                        <Button type="button" variant="outline" onClick={add} aria-label="Add category">
                            <Plus className="h-4 w-4" />
                        </Button>
                    </div>
                </div>
                <DialogFooter>
                    {!firstRun && <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>}
                    <Button onClick={save} disabled={saving || list.length === 0}>
                        {saving ? 'Saving…' : firstRun ? 'Save categories' : 'Save'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
