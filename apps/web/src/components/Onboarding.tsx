import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CopyBlock } from './CopyBlock'
import type { getMcpTemplates, getSetupStatus } from '@/lib/setup-actions'

type Steps = Awaited<ReturnType<typeof getSetupStatus>>['steps']
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
export function Onboarding({ steps, templates }: { steps: Steps; templates: Templates }) {
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
                    <Step done={steps.requirements} title={<>Set your hard requirements in <Link className="underline" href="/settings">Settings</Link></>}>
                        Postings that fail one are discarded for free, before any paid model reads them.
                    </Step>
                    <Step done={steps.sources} title={<>Add at least one company board in <Link className="underline" href="/sources">Sources</Link></>} />
                    <Step done={steps.jev} title={<>Optional: set up JEV in <Link className="underline" href="/settings">Settings</Link></>}>
                        A paid model (metered) reads each new posting against your profile and marks it keep or skip.
                    </Step>
                    <Step done={steps.firstFetch} title="Wait for the first fetch">
                        The worker fetches your boards on its next pass; postings then show under Jobs.
                    </Step>
                </ol>
            </CardContent>
        </Card>
    )
}
