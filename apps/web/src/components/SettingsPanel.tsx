'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { getCandidateProfile, setCandidateProfile } from '@/lib/profile-actions'
import { DEGREES, WORK_AUTHORIZATIONS } from '@/lib/constants'
import {
    type Education, type Experience, type ProfileView, type TriageContext,
    TRIAGE_FIELDS, highestDegree, totalYears, validateProfilePatch,
} from '@/lib/candidate-profile'
import { CustomContextEditor, Help, ListEditor } from './ProfileEditors'
import { X } from 'lucide-react'
import { toast } from 'sonner'

type Loaded = Awaited<ReturnType<typeof getCandidateProfile>>

// About what one posting's two JEV calls cost (measured pass: USD 0.079 / 300 postings).
const USD_PER_ASSESSMENT = 0.0003

const isRemote = (l: string) => l.trim().toLowerCase() === 'remote'
const lines = (t: string) => t.split('\n').map((l) => l.trim()).filter(Boolean)

const DEGREE_LABELS: Record<(typeof DEGREES)[number], string> = {
    none: 'No degree', 'high school': 'High school', associate: 'Associate',
    "bachelor's": "Bachelor's", "master's": "Master's", phd: 'PhD',
}
const CLEARANCES = [['none', 'I have none (skip postings that require one)'], ['secret', 'Secret'],
    ['top secret', 'Top Secret'], ['ts/sci', 'TS/SCI']] as const

// A select with "(do not screen)" first; a stored value outside the options stays selectable.
function Choice({ id, value, onChange, options }: {
    id: string; value: string; onChange: (v: string) => void; options: readonly (readonly [string, string])[]
}) {
    const known = options.some(([v]) => v.toLowerCase() === value.toLowerCase())
    const selected = known ? options.find(([v]) => v.toLowerCase() === value.toLowerCase())![0] : value
    return (
        <select id={id} value={selected} onChange={(e) => onChange(e.target.value)}
            className="flex h-9 w-full rounded-md border bg-transparent px-3 text-sm">
            <option value="">(do not screen)</option>
            {options.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
            {!known && value && <option value={value}>{value}</option>}
        </select>
    )
}

interface Draft {
    titleInclude: string; titleExclude: string; maxAge: string
    auth: string; clearance: string; places: string; remote: boolean; noInterns: boolean; noContract: boolean
    education: Education[]; experience: Experience[]
    target_roles: string[]; open_to: string[]; not_interested: string[]
    context: TriageContext | null   // the custom context to save (null = none / cleared)
    dropPacks: boolean
}

function draftFrom(p: ProfileView | null): Draft {
    const locs = p?.locations ?? []
    return {
        titleInclude: (p?.title_include ?? []).join('\n'), titleExclude: (p?.title_exclude ?? []).join('\n'),
        maxAge: String(p?.max_age_days ?? 0),
        auth: p?.work_authorization ?? '', clearance: p?.security_clearance ?? '',
        places: locs.filter((l) => !isRemote(l)).join('\n'), remote: locs.some(isRemote),
        noInterns: p?.exclude_internships ?? false, noContract: p?.exclude_contract ?? false,
        education: p?.education ?? [], experience: p?.experience ?? [],
        target_roles: p?.target_roles ?? [], open_to: p?.open_to ?? [], not_interested: p?.not_interested ?? [],
        context: p?.custom_triage_context ?? null, dropPacks: false,
    }
}

// The one candidate profile form (#224): every field every worker stage reads, saved in
// one write through the same action and validation as MCP set_candidate_profile.
export function SettingsPanel() {
    const router = useRouter()
    const [loaded, setLoaded] = useState<Loaded | null>(null)
    const [d, setD] = useState<Draft>(draftFrom(null))
    const [editorKey, setEditorKey] = useState(0)
    const [saving, setSaving] = useState(false)
    const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((x) => ({ ...x, [k]: v }))

    const load = (s: Loaded) => { setLoaded(s); setD(draftFrom(s.profile)); setEditorKey((k) => k + 1) }
    useEffect(() => {
        getCandidateProfile().catch((e) => { toast.error(`Could not load the profile: ${e.message}`); return null })
            .then((s) => { if (s) load(s) })
    }, [])

    const stored = loaded?.profile ?? null
    const placeList = lines(d.places)
    const patch = () => ({
        title_include: lines(d.titleInclude), title_exclude: lines(d.titleExclude),
        max_age_days: Number(d.maxAge),
        locations: [...placeList, ...(d.remote ? ['remote'] : [])],
        work_authorization: d.auth, security_clearance: d.clearance,
        exclude_internships: d.noInterns, exclude_contract: d.noContract,
        education: d.education, experience: d.experience,
        target_roles: d.target_roles, open_to: d.open_to, not_interested: d.not_interested,
        ...(JSON.stringify(d.context) !== JSON.stringify(stored?.custom_triage_context ?? null)
            ? { custom_triage_context: d.context } : {}),
        ...(d.dropPacks ? { custom_packs: null } : {}),
    })

    const save = async () => {
        let clean: ReturnType<typeof validateProfilePatch>
        try { clean = validateProfilePatch(patch()) } catch (e: any) { return toast.error(e.message) }
        // A change to what triage reads re-assesses recent postings (paid): confirm first.
        const before = stored as Record<string, unknown> | null
        const triageChanged = TRIAGE_FIELDS.some((k) => k in clean && (k === 'custom_packs'
            || JSON.stringify((clean as Record<string, unknown>)[k]) !== JSON.stringify(before?.[k] ?? (k === 'custom_triage_context' ? null : []))))
        const willTriage = clean.target_roles!.length > 0 || (('custom_triage_context' in clean) ? clean.custom_triage_context !== null : !!stored?.custom_triage_context)
        const n = loaded?.reassessOnChange ?? 0
        if (triageChanged && willTriage && n > 0) {
            const usd = (n * USD_PER_ASSESSMENT).toFixed(2)
            if (!window.confirm(`This changes what triage reads: ${n} recent postings are re-assessed on the next worker pass (paid, about USD ${usd}). Save?`)) return
        }
        setSaving(true)
        try {
            const result = await setCandidateProfile(clean)
            if (!result.success) return toast.error(result.error)
            toast.success(result.data?.unchanged ? 'Candidate profile: nothing changed' : 'Candidate profile saved')
            load(await getCandidateProfile())
            router.refresh() // the onboarding checklist re-reads setup status
        } catch (e: any) {
            toast.error(e.message)
        } finally {
            setSaving(false)
        }
    }

    if (!loaded) return <p className="text-sm text-muted-foreground">Loading...</p>
    const degree = highestDegree(d.education)
    const row = 'grid grid-cols-[1fr_1fr_auto] gap-2'
    return (
        <div className="space-y-8">
            <div className="space-y-1">
                <h2 className="text-xl font-semibold">Candidate profile</h2>
                <p className="text-sm text-muted-foreground">
                    The one profile every stage reads: fetch, the hard-requirement screen and triage.
                    {stored ? ` Version ${stored.version}, last set by ${stored.actor}.` : ' Nothing is set yet.'}
                    {' '}A change applies to postings evaluated from the next worker pass on; postings already evaluated keep their verdict.
                </p>
            </div>

            <section className="space-y-3">
                <h3 className="text-lg font-semibold">Search scope</h3>
                <p className="text-sm text-muted-foreground">What the system looks at: postings outside it are dropped at fetch, before storage.</p>
                <div className="grid grid-cols-3 gap-3">
                    <div className="space-y-1">
                        <Label htmlFor="s-title-include">Title must contain one of (one per line)</Label>
                        <Textarea id="s-title-include" rows={3} value={d.titleInclude} onChange={(e) => set('titleInclude', e.target.value)}
                            placeholder={'engineer\ndeveloper'} />
                        <Help>Blank keeps every title.</Help>
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="s-title-exclude">Title must not contain (one per line)</Label>
                        <Textarea id="s-title-exclude" rows={3} value={d.titleExclude} onChange={(e) => set('titleExclude', e.target.value)}
                            placeholder={'sales\nstaff'} />
                        <Help>Whole words: &quot;intern&quot; does not drop &quot;international&quot;.</Help>
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="s-max-age">Drop postings older than (days)</Label>
                        <Input id="s-max-age" type="number" min={0} value={d.maxAge} onChange={(e) => set('maxAge', e.target.value)} />
                        <Help>0 = off. Postings without a date are kept.</Help>
                    </div>
                </div>
            </section>

            <section className="space-y-3 border-t pt-8">
                <h3 className="text-lg font-semibold">Hard requirements</h3>
                <p className="text-sm text-muted-foreground">
                    A posting failing any of these is discarded, free, before any paid model reads it.
                    Blank means &quot;do not screen on it&quot; - nothing is assumed about you.
                </p>
                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                        <Label htmlFor="s-auth">Work authorization</Label>
                        <Choice id="s-auth" value={d.auth} onChange={(v) => set('auth', v)}
                            options={WORK_AUTHORIZATIONS.map((w) => [w, w] as const)} />
                        <Help>With &quot;needs visa sponsorship&quot;, postings that say they will not sponsor are skipped.</Help>
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="s-clearance">Security clearance</Label>
                        <Choice id="s-clearance" value={d.clearance} onChange={(v) => set('clearance', v)} options={CLEARANCES} />
                        <Help>Any clearance you hold counts as enough; levels are not compared yet.</Help>
                    </div>
                    <div className="space-y-1">
                        <Label htmlFor="s-locations">Locations (one per line)</Label>
                        <Textarea id="s-locations" rows={3} value={d.places} onChange={(e) => set('places', e.target.value)}
                            placeholder={'USA\nToronto'} />
                        <Help>
                            {placeList.length === 0 && !d.remote
                                ? 'Open to anywhere (no location screening).'
                                : 'List every country or state you will work in; on-site postings anywhere else are skipped.'}
                        </Help>
                        <label className="flex items-center gap-2 text-sm">
                            <input type="checkbox" checked={d.remote} disabled={placeList.length === 0 && !d.remote}
                                onChange={(e) => set('remote', e.target.checked)} />
                            Include remote-eligible postings
                        </label>
                        <Help>Remote postings tied to a country you did not list (e.g. Remote - India) are still skipped.</Help>
                    </div>
                    <div className="space-y-2 pt-6">
                        <label className="flex items-center gap-2 text-sm">
                            <input type="checkbox" checked={d.noInterns} onChange={(e) => set('noInterns', e.target.checked)} />
                            Exclude internships and co-ops
                        </label>
                        <label className="flex items-center gap-2 text-sm">
                            <input type="checkbox" checked={d.noContract} onChange={(e) => set('noContract', e.target.checked)} />
                            Exclude contract / part-time / temporary
                        </label>
                    </div>
                </div>
            </section>

            <section className="space-y-3 border-t pt-8">
                <h3 className="text-lg font-semibold">Background</h3>
                <p className="text-sm text-muted-foreground">Entered once; the screen and triage both read it.</p>
                <div className="space-y-2">
                    <Label>Education</Label>
                    {d.education.map((e, i) => (
                        <div key={i} className={row}>
                            <select aria-label={`Degree ${i + 1}`} value={e.degree}
                                className="flex h-9 w-full rounded-md border bg-transparent px-3 text-sm"
                                onChange={(ev) => set('education', d.education.map((x, j) => j === i ? { ...x, degree: ev.target.value as Education['degree'] } : x))}>
                                {DEGREES.map((g) => <option key={g} value={g}>{DEGREE_LABELS[g]}</option>)}
                            </select>
                            <Input aria-label={`Field ${i + 1}`} value={e.field} placeholder="e.g. Computer Science"
                                onChange={(ev) => set('education', d.education.map((x, j) => j === i ? { ...x, field: ev.target.value } : x))} />
                            <Button type="button" variant="ghost" size="icon" aria-label={`Remove education ${i + 1}`}
                                onClick={() => set('education', d.education.filter((_, j) => j !== i))}><X className="h-4 w-4" /></Button>
                        </div>
                    ))}
                    <Button type="button" variant="outline" size="sm"
                        onClick={() => set('education', [...d.education, { degree: "bachelor's", field: '' }])}>Add education</Button>
                    <Help>
                        Highest degree: {degree ? DEGREE_LABELS[degree as Education['degree']] : '(none listed: degree is not screened)'}.
                        {degree && ' Postings requiring a higher degree are discarded.'}
                    </Help>
                </div>
                <div className="space-y-2">
                    <Label>Experience</Label>
                    {d.experience.map((e, i) => (
                        <div key={i} className="grid grid-cols-[1fr_1fr_6rem_auto] gap-2">
                            <Input aria-label={`Title ${i + 1}`} value={e.title} placeholder="e.g. Software Engineer"
                                onChange={(ev) => set('experience', d.experience.map((x, j) => j === i ? { ...x, title: ev.target.value } : x))} />
                            <Input aria-label={`Company ${i + 1}`} value={e.company} placeholder="e.g. Acme"
                                onChange={(ev) => set('experience', d.experience.map((x, j) => j === i ? { ...x, company: ev.target.value } : x))} />
                            <Input aria-label={`Years ${i + 1}`} type="number" min={0} max={60} step={0.5} value={e.years}
                                onChange={(ev) => set('experience', d.experience.map((x, j) => j === i ? { ...x, years: Number(ev.target.value) || 0 } : x))} />
                            <Button type="button" variant="ghost" size="icon" aria-label={`Remove experience ${i + 1}`}
                                onClick={() => set('experience', d.experience.filter((_, j) => j !== i))}><X className="h-4 w-4" /></Button>
                        </div>
                    ))}
                    <Button type="button" variant="outline" size="sm"
                        onClick={() => set('experience', [...d.experience, { title: '', company: '', years: 0 }])}>Add experience</Button>
                    <Help>Total years of experience: {totalYears(d.experience)} (the sum of the rows). Triage compares it with a posting&apos;s required years.</Help>
                </div>
            </section>

            <section className="space-y-3 border-t pt-8">
                <h3 className="text-lg font-semibold">Preferences (triage)</h3>
                <p className="text-sm text-muted-foreground">
                    Triage is the keep/skip stage: a paid model (JEV) reads each new posting that passed the hard
                    requirements and marks it skip only when its core work is something you exclude, or it requires more
                    years than you have. It runs once you name a target role.
                </p>
                <div className="grid grid-cols-3 gap-4">
                    <ListEditor id="j-target" label="Target roles" items={d.target_roles} onChange={(v) => set('target_roles', v)}
                        placeholder="e.g. Backend engineer" help="The roles you want most." />
                    <ListEditor id="j-open" label="Open to" items={d.open_to} onChange={(v) => set('open_to', v)}
                        placeholder="e.g. Data platform" help="Also fine, if the posting fits otherwise." />
                    <ListEditor id="j-not" label="Not interested" items={d.not_interested} onChange={(v) => set('not_interested', v)}
                        placeholder="e.g. Sales engineering" help="Postings mainly about these are marked skip." />
                </div>
                <p className="text-sm">
                    Question packs: {stored?.packs === 'custom'
                        ? 'your custom packs.'
                        : 'the committed defaults (not yet measured on real postings).'}
                </p>
                {stored?.packs === 'custom' && (
                    <label className="flex items-center gap-2 text-sm">
                        <input type="checkbox" checked={d.dropPacks} onChange={(e) => set('dropPacks', e.target.checked)} />
                        Use the committed default packs instead
                    </label>
                )}
                {stored?.custom_triage_context ? (
                    <div className="space-y-3 rounded-md border p-3">
                        <p className="text-sm">
                            Triage sends this custom context instead of the background and preferences above.
                        </p>
                        <label className="flex items-center gap-2 text-sm">
                            <input type="checkbox" checked={d.context === null}
                                onChange={(e) => set('context', e.target.checked ? null : stored.custom_triage_context)} />
                            Stop using the custom context; send the fields above instead
                        </label>
                        {d.context !== null && (
                            <CustomContextEditor key={editorKey} stored={stored.custom_triage_context}
                                onChange={(next) => set('context', next)} />
                        )}
                    </div>
                ) : (
                    <details>
                        <summary className="cursor-pointer text-sm font-medium">Advanced: send a custom context instead of the fields</summary>
                        <div className="mt-2 grid grid-cols-2 gap-3">
                            <div className="space-y-1">
                                <Label htmlFor="c-new-profile">Profile (a JSON object, sent as written)</Label>
                                <Textarea id="c-new-profile" rows={6} className="font-mono text-xs" value={d.context?.profile_text ?? ''}
                                    onChange={(e) => set('context', e.target.value || d.context?.yoe_context ? { profile_text: e.target.value, yoe_context: d.context?.yoe_context ?? '' } : null)} />
                            </div>
                            <div className="space-y-1">
                                <Label htmlFor="c-new-yoe">Education and experience</Label>
                                <Textarea id="c-new-yoe" rows={6} value={d.context?.yoe_context ?? ''}
                                    onChange={(e) => set('context', e.target.value || d.context?.profile_text ? { profile_text: d.context?.profile_text ?? '', yoe_context: e.target.value } : null)} />
                            </div>
                        </div>
                    </details>
                )}
            </section>

            <div className="flex items-center gap-3 border-t pt-6">
                <Button onClick={save} disabled={saving}>Save profile</Button>
                <span className="text-sm text-muted-foreground">A change to what triage reads asks you to confirm the re-assessment cost first.</span>
            </div>
        </div>
    )
}
