import Link from 'next/link'
import { getMcpTemplates, getSetupStatus } from '@/lib/setup-actions'
import { getNewJobsCount } from '@/lib/job-actions'
import { Onboarding } from './Onboarding'

export const TABS = [
    ['/applications', 'Applications'],
    ['/jobs', 'Jobs'],
    ['/sources', 'Sources'],
    ['/activity', 'Activity'],
    ['/settings', 'Settings'],
] as const

export type TabPath = (typeof TABS)[number][0]

// Header, tab nav and the setup checklist around every page. Rendered by each page
// (not the root layout) so a navigation re-reads the badge and the setup status.
export async function AppShell({ active, children }: { active: TabPath; children: React.ReactNode }) {
    const [setup, newJobs] = await Promise.all([getSetupStatus(), getNewJobsCount()])
    return (
        <div className="container mx-auto space-y-6 px-4 py-10">
            <h1 className="text-2xl font-bold tracking-tight">Job Matchbook</h1>
            <nav className="inline-flex items-center gap-1 rounded-lg border bg-muted/40 p-1">
                {TABS.map(([href, label]) => (
                    <Link key={href} href={href} aria-current={active === href ? 'page' : undefined}
                        className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                            active === href ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>
                        {label}
                        {href === '/jobs' && newJobs > 0 && (
                            <span title="New postings for you in the last 24 hours"
                                className="ml-2 rounded-full bg-primary px-1.5 py-0.5 text-[10px] text-primary-foreground">
                                {newJobs}
                            </span>
                        )}
                    </Link>
                ))}
            </nav>
            {!setup.complete && <Onboarding steps={setup.steps} intake={setup.intake} templates={await getMcpTemplates()} />}
            {children}
        </div>
    )
}
