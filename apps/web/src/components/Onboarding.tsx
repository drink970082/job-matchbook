import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CopyBlock } from './CopyBlock'
import { Funnel } from './ActivityTab'
import { ConfirmProfileButton } from './ConfirmProfileButton'
import type { getMcpTemplates, getSetupStatus } from '@/lib/setup-actions'
import type { FunnelWindow } from '@/lib/intake-funnel'

type Setup = Awaited<ReturnType<typeof getSetupStatus>>
type Steps = Setup['steps']

// The #203 guard "your filters let N through": the postings still waiting for evaluation.
const waiting = (w: FunnelWindow) => w.stages.find((s) => s.stage === 'evaluated')?.reasons.pending ?? 0
type Templates = Awaited<ReturnType<typeof getMcpTemplates>>

function Step({ done, title, children }: { done: boolean; title: React.ReactNode; children?: React.ReactNode }) {
    return (
        <li className="space-y-1">
            <div className="flex items-baseline gap-2 text-sm">
                <span aria-label={done ? 'done' : 'to do'} className={done ? 'text-emerald-600' : 'text-muted-foreground'}>
                    [{done ? 'x' : ' '}]
                </span>
                <span className={done ? 'text-muted-foreground line-through' : 'font-medium'}>{title}</span>
            </div>
            {!done && children && <div className="ml-7 text-sm text-muted-foreground">{children}</div>}
        </li>
    )
}

// Setup checklist (#211), shown until the required steps are done. Every step but the
// first can be done on the web alone; the first is recommended, not required.
export function Onboarding({ steps, intake, wouldDiscard = null, templates }:
    { steps: Steps; intake: Setup['intake']; wouldDiscard?: number | null; templates: Templates }) {
    return (
        <Card>
            <CardHeader className="pb-2"><CardTitle className="text-lg">Get set up</CardTitle></CardHeader>
            <CardContent>
                <ol className="space-y-3">
                    <Step done={steps.aiClient} title="Connect an AI client (recommended)">
                        <p>
                            The intended way to set up and run this tool is an AI client (ChatGPT, Claude or Codex)
                            driving its MCP server: it can interview you for your requirements, add boards, log
                            applications and update statuses from your email. Everything below also works here
                            without one.
                        </p>
                        <details className="mt-2">
                            <summary className="cursor-pointer text-foreground">Connection templates</summary>
                            <div className="mt-2 space-y-3">
                                <CopyBlock label="Claude Code" text={templates['claude-code.txt']} />
                                <CopyBlock label="Claude Desktop (claude_desktop_config.json)" text={templates['claude-desktop.json']} />
                                <CopyBlock label="Codex CLI" text={templates['codex.txt']} />
                                <CopyBlock label="ChatGPT (Secure MCP Tunnel)" text={templates['chatgpt.txt']} />
                            </div>
                        </details>
                        <details className="mt-2">
                            <summary className="cursor-pointer text-foreground">Starter prompts</summary>
                            <div className="mt-2 space-y-3">
                                <CopyBlock label="Set me up" text={templates['prompt-set-me-up.txt']} />
                                <CopyBlock label="Log an application" text={templates['prompt-log-application.txt']} />
                                <CopyBlock label="Update statuses from my email" text={templates['prompt-update-from-email.txt']} />
                            </div>
                        </details>
                    </Step>
                    <Step done={steps.requirements} title={<>Fill in your candidate profile in <Link className="underline" href="/settings">Settings</Link></>}>
                        Postings that fail a hard requirement are discarded for free, before any paid model reads them.
                    </Step>
                    <Step done={steps.sources} title={<>Add at least one company board in <Link className="underline" href="/sources">Sources</Link></>} />
                    <Step done={steps.triage} title={<>Optional: set up triage in <Link className="underline" href="/settings">Settings</Link></>}>
                        Add target roles to your profile; a paid model (JEV, metered) then reads each new posting against them and marks it keep or skip.
                    </Step>
                    <Step done={steps.first_fetch} title="Wait for the first fetch">
                        The worker fetches your boards on its next pass; postings then show under Jobs.
                    </Step>
                    <Step done={steps.confirmed} title="Review what your profile lets through, then confirm it">
                        <p>
                            Until you confirm, the worker only fetches and applies your title filters and hard
                            requirements, which cost nothing; no model reads a posting. Check what was dropped and
                            why below, then adjust the profile in{' '}
                            <Link className="underline" href="/settings">Settings</Link>. A requirement you change now discards
                            nothing until you confirm; a posting already discarded at fetch stays discarded (an AI
                            client can rescue one with a keep override). After you confirm, postings from the last 7
                            days that are still waiting are evaluated once, under the profile you confirmed.
                        </p>
                        {intake?.last_7_days.passes ? (
                            <div className="my-3 max-w-md text-foreground">
                                <p className="mb-2 font-medium">
                                    Your filters and requirements let {waiting(intake.last_7_days).toLocaleString('en-US')} posting(s)
                                    through so far; they are evaluated after you confirm, a capped number per pass.
                                    {wouldDiscard ? ` Your current requirements would discard ${wouldDiscard.toLocaleString('en-US')} of them for free first.` : ''}
                                </p>
                                <Funnel title={`Last 7 days, passes: ${intake.last_7_days.passes}`} window={intake.last_7_days} />
                            </div>
                        ) : null}
                        {steps.first_fetch && !steps.requirements && <p>Set at least one hard requirement before you confirm.</p>}
                        {steps.first_fetch && steps.requirements && <ConfirmProfileButton />}
                    </Step>
                </ol>
            </CardContent>
        </Card>
    )
}
