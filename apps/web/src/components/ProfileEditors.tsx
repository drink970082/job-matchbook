'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import type { TriageContext } from '@/lib/candidate-profile'
import { X, Plus } from 'lucide-react'

// Editors the candidate profile form (SettingsPanel) is built from.

export function Help({ children }: { children: React.ReactNode }) {
    return <p className="text-xs text-muted-foreground">{children}</p>
}

export function ListEditor({ id, label, help, placeholder, items, onChange }: {
    id: string; label: string; help: string; placeholder: string; items: string[]; onChange: (v: string[]) => void
}) {
    const [draft, setDraft] = useState('')
    const add = () => {
        const v = draft.trim()
        setDraft('')
        if (v && !items.includes(v)) onChange([...items, v])
    }
    return (
        <div className="space-y-1">
            <Label htmlFor={id}>{label}</Label>
            <div className="flex flex-wrap gap-1.5">
                {items.map((x) => (
                    <span key={x} className="inline-flex items-center gap-1 rounded-full border bg-muted/50 px-2.5 py-0.5 text-sm">
                        {x}
                        <button type="button" aria-label={`Remove ${x}`} onClick={() => onChange(items.filter((i) => i !== x))}
                            className="text-muted-foreground hover:text-foreground"><X className="h-3 w-3" /></button>
                    </span>
                ))}
            </div>
            <div className="flex gap-2">
                <Input id={id} value={draft} placeholder={placeholder} onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
                    onBlur={add} /* typed but not added: leaving the box (e.g. for Save) adds it */ />
                <Button type="button" variant="outline" onClick={add} aria-label={`Add to ${label}`}><Plus className="h-4 w-4" /></Button>
            </div>
            <Help>{help}</Help>
        </div>
    )
}

type Json = null | boolean | number | string | Json[] | { [k: string]: Json }
type Path = (string | number)[]

const setAt = (v: Json, path: Path, x: Json): Json => {
    if (!path.length) return x
    const [h, ...t] = path
    if (Array.isArray(v)) { const a = [...v]; a[h as number] = setAt(a[h as number], t, x); return a }  // h = length appends
    const o = v as Record<string, Json>
    return { ...o, [h]: setAt(o[h as string], t, x) }
}
const removeAt = (v: Json, path: Path, i: number): Json =>
    setAt(v, path, (path.reduce<any>((o, k) => o[k], v) as Json[]).filter((_, j) => j !== i))
// A blank copy of an array's last item, so Add gives an entry of the same shape.
const blank = (v: Json): Json => typeof v === 'string' ? '' : typeof v === 'number' ? 0 : typeof v === 'boolean' ? false
    : v === null ? null : Array.isArray(v) ? [] : Object.fromEntries(Object.entries(v).map(([k, e]) => [k, blank(e)]))
const itemName = (v: Json, fallback: string) =>
    v && typeof v === 'object' && !Array.isArray(v) && typeof v.id === 'string' && v.id ? v.id : fallback

// One node of a profile JSON document, edited in place: strings, numbers and booleans are
// inputs; objects and lists nest; list entries can be added (same shape) and removed.
function JsonField({ name, value, path, onSet, onRemove }: {
    name: string; value: Json; path: Path; onSet: (path: Path, v: Json) => void; onRemove: (path: Path, i: number) => void
}) {
    const id = `jp-${path.map((k) => encodeURIComponent(String(k))).join('.')}`  // a '.' inside a key cannot collide
    if (typeof value === 'string') return (
        <div className="space-y-1">
            <Label htmlFor={id}>{name}</Label>
            <Textarea id={id} rows={1} className="min-h-9 text-sm" value={value} onChange={(e) => onSet(path, e.target.value)} />
        </div>
    )
    if (typeof value === 'number') return (
        <div className="space-y-1">
            <Label htmlFor={id}>{name}</Label>
            <Input id={id} type="number" value={value} onChange={(e) => { const n = Number(e.target.value); if (e.target.value.trim() && Number.isFinite(n)) onSet(path, n) }} />
        </div>
    )
    if (typeof value === 'boolean') return (
        <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={value} onChange={(e) => onSet(path, e.target.checked)} /> {name}
        </label>
    )
    // An {id, text} entry (the profile's background/preferences items) reads as one row.
    if (value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join() === 'id,text'
        && typeof value.id === 'string' && typeof value.text === 'string') return (
        <div className="grid grid-cols-[11rem_1fr] gap-2">
            <Input aria-label={`${name} id`} className="font-mono text-xs" value={value.id} onChange={(e) => onSet([...path, 'id'], e.target.value)} />
            <Textarea id={id} aria-label={`${name} text`} rows={1} className="min-h-9 text-sm" value={value.text}
                onChange={(e) => onSet([...path, 'text'], e.target.value)} />
        </div>
    )
    if (value === null) return <p className="text-sm text-muted-foreground">{name}: (empty)</p>
    const list = Array.isArray(value)
    const entries: [string | number, Json][] = list ? value.map((v, i) => [i, v]) : Object.entries(value)
    const body = entries.map(([k, v]) => {
        const label = list ? itemName(v, `${name} ${Number(k) + 1}`) : String(k)
        const field = <JsonField key={k} name={label} value={v} path={[...path, k]} onSet={onSet} onRemove={onRemove} />
        return !list ? field : (
            <div key={k} className="flex items-start gap-2">
                <div className="flex-1">{field}</div>
                {/* The last entry stays: it is the shape Add copies. */}
                {value.length > 1 && <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${label}`}
                    onClick={() => onRemove(path, Number(k))}><X className="h-4 w-4" /></Button>}
            </div>
        )
    })
    if (!path.length) return <div className="space-y-4">{body}</div>
    return (
        <fieldset className="space-y-3 border-l-2 border-muted-foreground/30 pl-4">
            <legend className="text-sm font-semibold">{name}</legend>
            {body}
            {list && (
                <Button type="button" variant="outline" size="sm" aria-label={`Add to ${name}`}
                    onClick={() => onSet([...path, value.length], value.length ? blank(value[value.length - 1]) : '')}>
                    <Plus className="mr-1 h-4 w-4" /> Add
                </Button>
            )}
        </fieldset>
    )
}

const parseObject = (t: string): Json | null => {
    try { const v = JSON.parse(t); return v && typeof v === 'object' && !Array.isArray(v) ? v : null } catch { return null }
}

// A custom triage context (a free-text profile carried verbatim, e.g. migrated from the
// old JEV profile): its JSON edited field by field, plus the raw text under Advanced.
// Reports the context to save; an unedited profile reports the stored bytes (the JEV
// policy hash covers them), and a textarea's CRLF normalization is not an edit.
export function CustomContextEditor({ stored, onChange }: {
    stored: TriageContext; onChange: (next: TriageContext) => void
}) {
    const [shown] = useState(() => { try { return JSON.stringify(JSON.parse(stored.profile_text), null, 2) } catch { return stored.profile_text } })
    const original = parseObject(stored.profile_text)
    const compact = stored.profile_text.trim() === JSON.stringify(original)
    const [doc, setDoc] = useState<Json | null>(original)
    const [raw, setRaw] = useState(shown)
    const [yoe, setYoe] = useState(stored.yoe_context)
    const lf = (t: string) => t.replace(/\r\n?/g, '\n')
    const emit = (nextRaw: string, nextYoe: string) => {
        const v = parseObject(nextRaw)
        const same = lf(nextRaw) === lf(shown) || (v !== null && JSON.stringify(v) === JSON.stringify(original))
        onChange({
            profile_text: same ? stored.profile_text : v !== null ? JSON.stringify(v, null, compact ? undefined : 2) : nextRaw,
            yoe_context: nextYoe.trim() === stored.yoe_context ? stored.yoe_context : nextYoe,
        })
    }
    const editDoc = (v: Json) => { setDoc(v); const t = JSON.stringify(v, null, 2); setRaw(t); emit(t, yoe) }
    return (
        <div className="space-y-4">
            {doc
                ? <JsonField name="" value={doc} path={[]} onRemove={(p, i) => editDoc(removeAt(doc, p, i))}
                    onSet={(p, v) => editDoc(setAt(doc, p, v))} />
                : <p className="text-sm">The stored context is not a JSON object: it is kept as written. Edit the experience text below, or rewrite the profile as a JSON object under Advanced.</p>}
            <div className="space-y-1">
                <Label htmlFor="c-yoe">Education and experience (sent as written)</Label>
                <Textarea id="c-yoe" rows={3} value={yoe} onChange={(e) => { setYoe(e.target.value); emit(raw, e.target.value) }} />
            </div>
            <details>
                <summary className="cursor-pointer text-sm font-medium">Advanced: edit the raw profile text</summary>
                <div className="mt-2 space-y-1">
                    <Label htmlFor="c-profile">Profile (JSON)</Label>
                    <Textarea id="c-profile" rows={16} className="font-mono text-xs" value={raw}
                        onChange={(e) => { setRaw(e.target.value); const v = parseObject(e.target.value); if (v && doc) setDoc(v); emit(e.target.value, yoe) }} />
                </div>
            </details>
        </div>
    )
}
