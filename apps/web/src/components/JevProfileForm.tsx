'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { type JevForm, parseJevProfile, renderJevProfile, totalYears, validateJevForm } from '@/lib/jev-profile-form'
import { X, Plus } from 'lucide-react'
import { toast } from 'sonner'

// About what one posting's two JEV calls cost (measured pass: USD 0.079 / 300 postings).
const USD_PER_ASSESSMENT = 0.0003
const EMPTY: JevForm = { target_roles: [], open_to: [], not_interested: [], education: [], experience: [] }

interface Props {
    stored: { profile_text: string; yoe_context: string }
    reassessOnChange: number
    saving: boolean
    save: (input: Record<string, unknown>) => Promise<void>
}

function Help({ children }: { children: React.ReactNode }) {
    return <p className="text-xs text-muted-foreground">{children}</p>
}

function ListEditor({ id, label, help, placeholder, items, onChange }: {
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
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }} />
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

// One node of the stored profile JSON, edited in place: strings, numbers and booleans are
// inputs; objects and lists nest; list entries can be added (same shape) and removed.
function JsonField({ name, value, path, onSet, onRemove }: {
    name: string; value: Json; path: Path; onSet: (path: Path, v: Json) => void; onRemove: (path: Path, i: number) => void
}) {
    const id = `jp-${path.join('.')}`
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
    if (value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).join() === 'id,text'
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

// The JEV profile as a form (#206). Saves the structured fields; the server renders the
// profile text from them. A stored profile the form did not write (e.g. seeded from
// jev_dir) is edited field by field as the JSON it is, so the page always shows it.
export function JevProfileForm({ stored, reassessOnChange, saving, save }: Props) {
    const parsed = parseJevProfile(stored.profile_text, stored.yoe_context)
    const [form, setForm] = useState<JevForm>(parsed ?? EMPTY)
    // Shown indented; the unedited text saves as the stored bytes (see saveRaw).
    const [shown] = useState(() => { try { return JSON.stringify(JSON.parse(stored.profile_text), null, 2) } catch { return stored.profile_text } })
    const [profile, setProfile] = useState(shown)
    const [yoe, setYoe] = useState(stored.yoe_context)
    const original = parseObject(stored.profile_text)
    const [doc, setDoc] = useState<Json | null>(original)
    // The structured editor and Advanced are two views of one profile: each edit updates both.
    const editDoc = (v: Json) => { setDoc(v); setProfile(JSON.stringify(v, null, 2)) }
    const set = <K extends keyof JevForm>(k: K, v: JevForm[K]) => setForm({ ...form, [k]: v })

    const confirmCost = () => {
        const usd = (reassessOnChange * USD_PER_ASSESSMENT).toFixed(2)
        return window.confirm(`A changed JEV profile re-assesses ${reassessOnChange} recent postings on the next worker pass (paid, about USD ${usd}). Save?`)
    }

    const saveForm = async () => {
        // Normalize as the server will (trim, drop blank rows) before comparing, so an
        // empty added row does not read as a change and prompt for a paid re-assessment.
        let clean: JevForm
        try { clean = validateJevForm(form) } catch (e: any) { return toast.error(e.message) }
        const next = renderJevProfile(clean)
        if (next.profile_text === stored.profile_text && next.yoe_context === stored.yoe_context) {
            return toast.success('JEV profile: nothing changed')
        }
        if (confirmCost()) await save({ form: clean })
    }

    const saveRaw = async () => {
        // A textarea normalizes line endings, so compare modulo CR; an edit that only
        // dropped CRs is no change, and the stored bytes (the policy hash input) stay.
        const lf = (t: string) => t.replace(/\r\n?/g, '\n')
        const profileChanged = lf(profile) !== lf(shown)
        if (!profileChanged && yoe.trim() === stored.yoe_context) return toast.success('JEV profile: nothing changed')
        if (confirmCost()) await save({ profile_text: profileChanged ? profile : stored.profile_text, yoe_context: yoe })
    }

    const saveDoc = async () => {
        const unchanged = JSON.stringify(doc) === JSON.stringify(original)
        if (unchanged && yoe.trim() === stored.yoe_context) return toast.success('JEV profile: nothing changed')
        // Unchanged keeps the stored bytes (the policy hash input); an edit keeps its layout.
        const compact = stored.profile_text.trim() === JSON.stringify(original)
        const text = unchanged ? stored.profile_text : JSON.stringify(doc, null, compact ? undefined : 2)
        if (confirmCost()) await save({ profile_text: text, yoe_context: yoe })
    }

    const row = 'grid grid-cols-[1fr_1fr_auto] gap-2'
    return (
        <div className="space-y-4">
            {!parsed && doc && (
                <div className="space-y-4">
                    <JsonField name="" value={doc} path={[]} onRemove={(p, i) => editDoc(removeAt(doc, p, i))}
                        onSet={(p, v) => editDoc(setAt(doc, p, v))} />
                    <div className="space-y-1">
                        <Label htmlFor="j-yoe">Education and experience</Label>
                        <Textarea id="j-yoe" rows={3} value={yoe} onChange={(e) => setYoe(e.target.value)} />
                    </div>
                    <div className="flex items-center gap-3">
                        <Button onClick={saveDoc} disabled={saving}>Save JEV profile</Button>
                        <span className="text-sm text-muted-foreground">A change re-assesses recent postings on the next pass (paid; you confirm the cost first).</span>
                    </div>
                </div>
            )}
            {!parsed && !doc && (
                <p className="text-sm">Your stored profile is not a JSON object, so it can only be edited under Advanced below.</p>
            )}
            {parsed && (<>
            <div className="grid grid-cols-3 gap-4">
                <ListEditor id="j-target" label="Target roles" items={form.target_roles} onChange={(v) => set('target_roles', v)}
                    placeholder="e.g. Backend engineer" help="The roles you want most." />
                <ListEditor id="j-open" label="Open to" items={form.open_to} onChange={(v) => set('open_to', v)}
                    placeholder="e.g. Data platform" help="Also fine, if the posting fits otherwise." />
                <ListEditor id="j-not" label="Not interested" items={form.not_interested} onChange={(v) => set('not_interested', v)}
                    placeholder="e.g. Sales engineering" help="Postings mainly about these are marked skip." />
            </div>

            <div className="space-y-2">
                <Label>Education</Label>
                {form.education.map((e, i) => (
                    <div key={i} className={row}>
                        <Input aria-label={`Degree ${i + 1}`} value={e.degree} placeholder="e.g. Master's"
                            onChange={(ev) => set('education', form.education.map((x, j) => j === i ? { ...x, degree: ev.target.value } : x))} />
                        <Input aria-label={`Field ${i + 1}`} value={e.field} placeholder="e.g. Computer Science"
                            onChange={(ev) => set('education', form.education.map((x, j) => j === i ? { ...x, field: ev.target.value } : x))} />
                        <Button type="button" variant="ghost" size="icon" aria-label={`Remove education ${i + 1}`}
                            onClick={() => set('education', form.education.filter((_, j) => j !== i))}><X className="h-4 w-4" /></Button>
                    </div>
                ))}
                <Button type="button" variant="outline" size="sm" onClick={() => set('education', [...form.education, { degree: '', field: '' }])}>
                    Add education
                </Button>
            </div>

            <div className="space-y-2">
                <Label>Experience</Label>
                {form.experience.map((e, i) => (
                    <div key={i} className="grid grid-cols-[1fr_1fr_6rem_auto] gap-2">
                        <Input aria-label={`Title ${i + 1}`} value={e.title} placeholder="e.g. Software Engineer"
                            onChange={(ev) => set('experience', form.experience.map((x, j) => j === i ? { ...x, title: ev.target.value } : x))} />
                        <Input aria-label={`Company ${i + 1}`} value={e.company} placeholder="e.g. Acme"
                            onChange={(ev) => set('experience', form.experience.map((x, j) => j === i ? { ...x, company: ev.target.value } : x))} />
                        <Input aria-label={`Years ${i + 1}`} type="number" min={0} max={60} step={0.5} value={e.years}
                            onChange={(ev) => set('experience', form.experience.map((x, j) => j === i ? { ...x, years: Number(ev.target.value) || 0 } : x))} />
                        <Button type="button" variant="ghost" size="icon" aria-label={`Remove experience ${i + 1}`}
                            onClick={() => set('experience', form.experience.filter((_, j) => j !== i))}><X className="h-4 w-4" /></Button>
                    </div>
                ))}
                <Button type="button" variant="outline" size="sm" onClick={() => set('experience', [...form.experience, { title: '', company: '', years: 0 }])}>
                    Add experience
                </Button>
                <Help>Total years of experience: {totalYears(form)} (the sum of the rows). Used for postings that require a number of years.</Help>
            </div>

            <div className="flex items-center gap-3">
                <Button onClick={saveForm} disabled={saving}>Save JEV profile</Button>
                <span className="text-sm text-muted-foreground">A change re-assesses recent postings on the next pass (paid; you confirm the cost first).</span>
            </div>
            </>)}

            <details>
                <summary className="cursor-pointer text-sm font-medium">Advanced: edit the raw profile text</summary>
                <div className="mt-2 space-y-3">
                    <div className="space-y-1">
                        <Label htmlFor="s-profile">Profile (JSON)</Label>
                        <Textarea id="s-profile" rows={20} className="font-mono text-xs" value={profile}
                            onChange={(e) => { setProfile(e.target.value); const v = parseObject(e.target.value); if (v && doc) setDoc(v) }} />
                    </div>
                    {(parsed || !doc) && <div className="space-y-1">
                        <Label htmlFor="s-yoe">Education and experience</Label>
                        <Textarea id="s-yoe" rows={3} value={yoe} onChange={(e) => setYoe(e.target.value)} />
                    </div>}
                    <Button variant="outline" onClick={saveRaw} disabled={saving}>Save raw text</Button>
                </div>
            </details>
        </div>
    )
}
