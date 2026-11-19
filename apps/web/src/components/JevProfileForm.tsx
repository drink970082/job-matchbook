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

// The JEV profile as a form (#206). Saves the structured fields; the server renders the
// profile text from them. A stored profile the form did not write opens in Advanced.
export function JevProfileForm({ stored, reassessOnChange, saving, save }: Props) {
    const parsed = parseJevProfile(stored.profile_text, stored.yoe_context)
    const [form, setForm] = useState<JevForm>(parsed ?? EMPTY)
    const [advanced, setAdvanced] = useState(!parsed)
    const [profile, setProfile] = useState(stored.profile_text)
    const [yoe, setYoe] = useState(stored.yoe_context)
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
        const profileChanged = lf(profile) !== lf(stored.profile_text)
        if (!profileChanged && yoe.trim() === stored.yoe_context) return toast.success('JEV profile: nothing changed')
        if (confirmCost()) await save({ profile_text: profileChanged ? profile : stored.profile_text, yoe_context: yoe })
    }

    const row = 'grid grid-cols-[1fr_1fr_auto] gap-2'
    return (
        <div className="space-y-4">
            {!parsed && (
                <p className="text-sm">
                    Your stored profile was written as free text, so it opens under Advanced. Filling in the form
                    and saving replaces it.
                </p>
            )}
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

            <details open={advanced} onToggle={(e) => setAdvanced((e.target as HTMLDetailsElement).open)}>
                <summary className="cursor-pointer text-sm font-medium">Advanced: edit the raw profile text</summary>
                <div className="mt-2 space-y-3">
                    <div className="space-y-1">
                        <Label htmlFor="s-profile">Profile (JSON)</Label>
                        <Textarea id="s-profile" rows={12} className="font-mono text-xs" value={profile}
                            onChange={(e) => setProfile(e.target.value)} />
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="s-yoe">Education and experience</Label>
                        <Textarea id="s-yoe" rows={3} value={yoe} onChange={(e) => setYoe(e.target.value)} />
                    </div>
                    <Button variant="outline" onClick={saveRaw} disabled={saving}>Save raw text</Button>
                </div>
            </details>
        </div>
    )
}
