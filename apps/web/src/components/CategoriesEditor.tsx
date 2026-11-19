'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { setCategories } from '@/lib/category-actions'
import { toast } from 'sonner'
import { X, Plus } from 'lucide-react'

// Edit the application-category vocabulary - the labels shown in the Add form, the
// Mark-Applied dialog, the table filter, and the category donut. Free-form: add or
// remove anything; a removed category doesn't relabel applications already filed
// under it.
export function CategoriesEditor({ initial }: { initial: string[] }) {
    const [list, setList] = useState<string[]>(initial)
    const [draft, setDraft] = useState('')
    const [saving, setSaving] = useState(false)

    const add = () => {
        const c = draft.trim()
        setDraft('')
        if (!c || list.some((x) => x.toLowerCase() === c.toLowerCase())) return
        setList([...list, c])
    }

    const save = async () => {
        setSaving(true)
        const result = await setCategories(list)
        setSaving(false)
        if (result.success) {
            toast.success('Categories saved')
            setList(result.data ?? list)
        } else {
            toast.error(result.error)
        }
    }

    return (
        <section className="space-y-3">
            <h3 className="font-semibold">Application categories</h3>
            <p className="text-sm text-muted-foreground">
                Labels for your applications and the category chart. Just labels - edit them anytime.
            </p>
            <div className="flex flex-wrap gap-1.5">
                {list.map((c, i) => (
                    <span key={c} className="inline-flex items-center gap-1 rounded-full border bg-muted/50 px-2.5 py-1 text-sm">
                        {c}
                        <button type="button" aria-label={`Remove ${c}`}
                            onClick={() => setList(list.filter((_, idx) => idx !== i))}
                            className="text-muted-foreground hover:text-foreground">
                            <X className="h-3 w-3" />
                        </button>
                    </span>
                ))}
                {list.length === 0 && <span className="text-sm text-muted-foreground">No categories yet - add at least one.</span>}
            </div>
            <div className="flex max-w-md gap-2">
                <Input value={draft} onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
                    placeholder="Add a category, e.g. Data Science" aria-label="New category" />
                <Button type="button" variant="outline" onClick={add} aria-label="Add category">
                    <Plus className="h-4 w-4" />
                </Button>
            </div>
            <Button onClick={save} disabled={saving || list.length === 0}>{saving ? 'Saving...' : 'Save categories'}</Button>
        </section>
    )
}
