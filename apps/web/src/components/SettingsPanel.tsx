'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { getSettings, setCandidatePreferences, setJevProfile } from '@/lib/preference-actions'
import { WORK_AUTHORIZATIONS } from '@/lib/constants'
import { toast } from 'sonner'

// About what one posting's two JEV calls cost (measured pass: USD 0.079 / 300 postings).
const USD_PER_ASSESSMENT = 0.0003

type Settings = Awaited<ReturnType<typeof getSettings>>

// The two stored settings the worker reads (#157): the screen's hard requirements and
// the JEV filter's profile. Same actions and validation as the MCP set_* tools.
export function SettingsPanel() {
    const router = useRouter()
    const [settings, setSettings] = useState<Settings | null>(null)
    const [degree, setDegree] = useState('')
    const [auth, setAuth] = useState('')
    const [clearance, setClearance] = useState('')
    const [locations, setLocations] = useState('')
    const [noInterns, setNoInterns] = useState(false)
    const [profile, setProfile] = useState('')
    const [yoe, setYoe] = useState('')
    const [saving, setSaving] = useState(false)

    useEffect(() => {
        getSettings().catch((e) => { toast.error(`Could not load settings: ${e.message}`); return null }).then((s) => {
            if (!s) return
            setSettings(s)
            setDegree(s.preferences?.highest_degree ?? '')
            setAuth(s.preferences?.work_authorization ?? '')
            setClearance(s.preferences?.security_clearance ?? '')
            setLocations((s.preferences?.locations ?? []).join('\n'))
            setNoInterns(s.preferences?.exclude_internships ?? false)
            setProfile(s.jev?.profile_text ?? '')
            setYoe(s.jev?.yoe_context ?? '')
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

    const saveRequirements = () => run(() => setCandidatePreferences({
        highest_degree: degree, work_authorization: auth, security_clearance: clearance,
        locations: locations.split('\n'), exclude_internships: noInterns,
    }), 'Hard requirements')

    const saveProfile = async () => {
        const stored = settings?.jev
        if (!stored) return
        // A textarea normalizes line endings, so compare modulo CR; an edit that only
        // dropped CRs is no change, and the stored bytes (the policy hash input) stay.
        const lf = (t: string) => t.replace(/\r\n?/g, '\n')
        const profileChanged = lf(profile) !== lf(stored.profile_text)
        if (!profileChanged && yoe.trim() === stored.yoe_context) {
            toast.success('JEV profile: nothing changed')
            return
        }
        const n = settings.reassessOnChange
        const usd = (n * USD_PER_ASSESSMENT).toFixed(2)
        if (!window.confirm(`A changed JEV profile re-assesses ${n} recent postings on the next worker pass (paid, about USD ${usd}). Save?`)) return
        await run(() => setJevProfile({ profile_text: profileChanged ? profile : stored.profile_text, yoe_context: yoe }), 'JEV profile')
    }

    return (
        <>
                {!settings ? (
                    <p className="text-sm text-muted-foreground">Loading...</p>
                ) : (
                    <div className="space-y-8">
                        <section className="space-y-3">
                            <h3 className="font-semibold">Hard requirements</h3>
                            <p className="text-sm text-muted-foreground">
                                The only things that discard a posting. Blank = do not screen on it.
                                {settings.preferences && ` Version ${settings.preferences.version}, last set by ${settings.preferences.actor}.`}
                            </p>
                            <div className="grid grid-cols-2 gap-3">
                                <div className="space-y-1">
                                    <Label htmlFor="s-degree">Highest degree</Label>
                                    <Input id="s-degree" value={degree} onChange={(e) => setDegree(e.target.value)}
                                        placeholder="none, Bachelor's, Master's, PhD..." />
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="s-auth">Work authorization</Label>
                                    <select id="s-auth" value={auth} onChange={(e) => setAuth(e.target.value)}
                                        className="flex h-9 w-full rounded-md border bg-transparent px-3 text-sm">
                                        <option value="">(do not screen)</option>
                                        {WORK_AUTHORIZATIONS.map((w) => <option key={w} value={w}>{w}</option>)}
                                    </select>
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="s-clearance">Security clearance</Label>
                                    <Input id="s-clearance" value={clearance} onChange={(e) => setClearance(e.target.value)}
                                        placeholder="none, secret, top secret..." />
                                </div>
                                <div className="space-y-1">
                                    <Label htmlFor="s-locations">Locations (one per line)</Label>
                                    <Textarea id="s-locations" rows={3} value={locations} onChange={(e) => setLocations(e.target.value)} />
                                </div>
                            </div>
                            <label className="flex items-center gap-2 text-sm">
                                <input type="checkbox" checked={noInterns} onChange={(e) => setNoInterns(e.target.checked)} />
                                Exclude internships and co-ops
                            </label>
                            <p className="text-xs text-muted-foreground">Postings already screened keep their verdict.</p>
                            <Button onClick={saveRequirements} disabled={saving}>Save requirements</Button>
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
                                        What you want from a job, sent to the keep/skip filter as written.
                                        Version {settings.jev.version}, last set by {settings.jev.actor}.
                                    </p>
                                    <div className="space-y-1">
                                        <Label htmlFor="s-profile">Profile (JSON)</Label>
                                        <Textarea id="s-profile" rows={14} className="font-mono text-xs" value={profile}
                                            onChange={(e) => setProfile(e.target.value)} />
                                    </div>
                                    <div className="space-y-1">
                                        <Label htmlFor="s-yoe">Education and experience</Label>
                                        <Textarea id="s-yoe" rows={3} value={yoe} onChange={(e) => setYoe(e.target.value)} />
                                    </div>
                                    <Button onClick={saveProfile} disabled={saving}>Save JEV profile</Button>
                                </>
                            )}
                        </section>
                    </div>
                )}
        </>
    )
}
