'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { getSettings, setCandidatePreferences, setJevProfile } from '@/lib/preference-actions'
import { WORK_AUTHORIZATIONS } from '@/lib/constants'
import { toast } from 'sonner'
import { JevProfileForm } from './JevProfileForm'

type Settings = Awaited<ReturnType<typeof getSettings>>

const isRemote = (l: string) => l.trim().toLowerCase() === 'remote'

// Options match what the worker's screen recognizes (engine._degree_rank).
const DEGREES = [['none', 'No degree'], ['High School', 'High school'], ['Associate', 'Associate'],
    ["Bachelor's", "Bachelor's"], ["Master's", "Master's"], ['PhD', 'PhD']] as const
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

// The two stored settings the worker reads (#157): the screen's hard requirements and
// the JEV filter's profile. Same actions and validation as the MCP set_* tools.
export function SettingsPanel() {
    const router = useRouter()
    const [settings, setSettings] = useState<Settings | null>(null)
    const [degree, setDegree] = useState('')
    const [auth, setAuth] = useState('')
    const [clearance, setClearance] = useState('')
    const [places, setPlaces] = useState('')
    const [remote, setRemote] = useState(false)
    const [noInterns, setNoInterns] = useState(false)
    const [noContract, setNoContract] = useState(false)
    const [saving, setSaving] = useState(false)

    useEffect(() => {
        getSettings().catch((e) => { toast.error(`Could not load settings: ${e.message}`); return null }).then((s) => {
            if (!s) return
            setSettings(s)
            setDegree(s.preferences?.highest_degree ?? '')
            setAuth(s.preferences?.work_authorization ?? '')
            setClearance(s.preferences?.security_clearance ?? '')
            const locs = s.preferences?.locations ?? []
            setPlaces(locs.filter((l) => !isRemote(l)).join('\n'))
            setRemote(locs.some(isRemote))
            setNoInterns(s.preferences?.exclude_internships ?? false)
            setNoContract(s.preferences?.exclude_contract ?? false)
        })
    }, [])

    const done = (result: { success: boolean; error?: string; data?: any }, what: string) => {
        if (!result.success) return toast.error(result.error)
        toast.success(result.data?.unchanged ? `${what}: nothing changed` : `${what} saved`)
        getSettings().then(setSettings).catch(() => {})
        router.refresh() // the onboarding checklist re-reads setup status
    }

    const run = async (write: () => Promise<any>, what: string) => {
        setSaving(true)
        try {
            done(await write(), what)
        } catch (e: any) {
            toast.error(e.message)
        } finally {
            setSaving(false)
        }
    }

    const placeList = places.split('\n').map((l) => l.trim()).filter(Boolean)
    const saveRequirements = () => run(() => setCandidatePreferences({
        highest_degree: degree, work_authorization: auth, security_clearance: clearance,
        locations: [...placeList, ...(remote ? ['remote'] : [])],
        exclude_internships: noInterns, exclude_contract: noContract,
    }), 'Hard requirements')

    return (
        <>
                {!settings ? (
                    <p className="text-sm text-muted-foreground">Loading...</p>
                ) : (
                    <div className="space-y-8">
                        <section className="space-y-3">
                            <h3 className="font-semibold">Hard requirements</h3>
                            <p className="text-sm text-muted-foreground">
                                A posting failing any of these is discarded, free, before any paid model reads it.
                                Blank means &quot;do not screen on it&quot; - nothing is assumed about you.
                                {settings.preferences && ` Version ${settings.preferences.version}, last set by ${settings.preferences.actor}.`}
                            </p>
                            <div className="grid grid-cols-2 gap-3">
                                <div className="space-y-1">
                                    <Label htmlFor="s-degree">Highest degree</Label>
                                    <Choice id="s-degree" value={degree} onChange={setDegree} options={DEGREES} />
                                    <p className="text-xs text-muted-foreground">Postings requiring a higher degree are skipped.</p>
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="s-auth">Work authorization</Label>
                                    <Choice id="s-auth" value={auth} onChange={setAuth}
                                        options={WORK_AUTHORIZATIONS.map((w) => [w, w] as const)} />
                                    <p className="text-xs text-muted-foreground">With &quot;needs visa sponsorship&quot;, postings that say they will not sponsor are skipped.</p>
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="s-clearance">Security clearance</Label>
                                    <Choice id="s-clearance" value={clearance} onChange={setClearance} options={CLEARANCES} />
                                    <p className="text-xs text-muted-foreground">Any clearance you hold counts as enough; levels are not compared yet.</p>
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="s-locations">Locations (one per line)</Label>
                                    <Textarea id="s-locations" rows={3} value={places} onChange={(e) => setPlaces(e.target.value)}
                                        placeholder={'USA\nToronto'} />
                                    <p className="text-xs text-muted-foreground">
                                        {placeList.length === 0 && !remote
                                            ? 'Open to anywhere (no location screening).'
                                            : 'List every country or state you will work in; on-site postings anywhere else are skipped.'}
                                    </p>
                                    <label className="flex items-center gap-2 text-sm">
                                        <input type="checkbox" checked={remote} disabled={placeList.length === 0 && !remote}
                                            onChange={(e) => setRemote(e.target.checked)} />
                                        Include remote-eligible postings
                                    </label>
                                    <p className="text-xs text-muted-foreground">
                                        Remote postings tied to a country you did not list (e.g. Remote - India) are still skipped.
                                    </p>
                                </div>
                            </div>
                            <label className="flex items-center gap-2 text-sm">
                                <input type="checkbox" checked={noInterns} onChange={(e) => setNoInterns(e.target.checked)} />
                                Exclude internships and co-ops
                            </label>
                            <label className="flex items-center gap-2 text-sm">
                                <input type="checkbox" checked={noContract} onChange={(e) => setNoContract(e.target.checked)} />
                                Exclude contract / part-time / temporary
                            </label>
                            <div className="flex items-center gap-3">
                                <Button onClick={saveRequirements} disabled={saving}>Save requirements</Button>
                                <span className="text-sm text-muted-foreground">Postings already screened keep their verdict.</span>
                            </div>
                        </section>

                        <section className="space-y-3">
                            <h3 className="font-semibold">JEV profile</h3>
                            {!settings.jev ? (
                                <p className="text-sm text-muted-foreground">
                                    No JEV profile yet. The worker seeds it from <code>jev_dir</code> when run with
                                    <code> --jev</code>; the question packs only come from there.
                                </p>
                            ) : (
                                <>
                                    <p className="text-sm text-muted-foreground">
                                        A paid model reads each new posting against this and marks it keep or skip.
                                        Version {settings.jev.version}, last set by {settings.jev.actor}.
                                    </p>
                                    <JevProfileForm key={settings.jev.version} stored={settings.jev}
                                        reassessOnChange={settings.reassessOnChange} saving={saving}
                                        save={(input) => run(() => setJevProfile(input), 'JEV profile')} />
                                </>
                            )}
                        </section>
                    </div>
                )}
        </>
    )
}
