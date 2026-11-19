'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { getRecentActivity } from '@/lib/activity-actions'

export type RecentActivity = Awaited<ReturnType<typeof getRecentActivity>>

function By({ actor }: { actor: string }) {
    return <span className={`text-xs ${actor === 'mcp' ? 'font-medium' : 'text-muted-foreground'}`}>{actor === 'mcp' ? 'via MCP' : 'web'}</span>
}

function Section({ title, empty, children }: { title: string; empty: boolean; children: React.ReactNode }) {
    return (
        <Card>
            <CardHeader className="pb-2"><CardTitle className="text-base">{title}</CardTitle></CardHeader>
            <CardContent>
                {empty ? <p className="text-sm text-muted-foreground">Nothing yet.</p> : <ul className="space-y-1.5 text-sm">{children}</ul>}
            </CardContent>
        </Card>
    )
}

// Recent writes and who made them (#158), newest first.
export function ActivityTab({ activity }: { activity: RecentActivity | null }) {
    if (!activity) return <p className="text-sm text-muted-foreground">Loading activity...</p>
    return (
        <div className="grid gap-6 lg:grid-cols-3">
            <Section title="New applications" empty={activity.applications.length === 0}>
                {activity.applications.map((a) => (
                    <li key={a.id} className="flex flex-wrap items-baseline gap-2">
                        <span className="text-muted-foreground">{a.date_applied}</span>
                        <span>{a.company_name} - {a.job_title}</span>
                        <By actor={a.actor} />
                    </li>
                ))}
            </Section>
            <Section title="Status changes" empty={activity.statusChanges.length === 0}>
                {activity.statusChanges.map((h) => (
                    <li key={h.id} className="flex flex-wrap items-baseline gap-2">
                        <span className="text-muted-foreground">{h.timestamp.slice(0, 10)}</span>
                        <span>{h.company_name} -&gt; {h.status}</span>
                        <By actor={h.actor} />
                    </li>
                ))}
            </Section>
            <Section title="Sources, overrides and settings" empty={activity.changes.length === 0}>
                {activity.changes.map((c) => (
                    <li key={c.id} className="flex flex-wrap items-baseline gap-2">
                        <span className="text-muted-foreground">{c.at.slice(0, 10)}</span>
                        <span>{c.action} {c.label}</span>
                        <By actor={c.actor} />
                    </li>
                ))}
            </Section>
        </div>
    )
}
