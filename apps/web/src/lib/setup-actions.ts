'use server'

import { readFileSync } from 'node:fs'
import path from 'node:path'
import { prisma } from '@/lib/db'
import { setupSteps } from '@/lib/candidate-profile'
import { readIntakeFunnel } from '@/lib/activity-actions'
import { parseObject } from '@/lib/pass-record'

// Web counterpart of MCP get_setup_status: what a fresh install still needs, by the one
// shared rule (candidate-profile.ts setupSteps). Until the profile is confirmed, the
// intake summary the operator reviews first (#227) rides along.
export async function getSetupStatus() {
    const [row, sources, firstPosting, mcpWrite] = await Promise.all([
        prisma.candidate_profile.findUnique({ where: { id: 1 } }),
        prisma.watched_companies.count(),
        prisma.job_postings.findFirst({ select: { id: true } }),
        Promise.all([prisma.audit_log, prisma.applications, prisma.status_history].map((t: any) =>
            t.findFirst({ where: { actor: 'mcp' }, select: { id: true } }))).then((rows) => rows.some(Boolean)),
    ])
    // The AI client and triage steps are optional: a web-only user still finishes.
    const { complete, ...shared } = setupSteps(row, { sources, hasPosting: !!firstPosting })
    // ponytail: "connected" = the MCP server has written through /api/v1 at least once;
    // a read-only connection never ticks it (the step is optional).
    const steps = { aiClient: mcpWrite, ...shared }
    const intake = !steps.confirmed && steps.first_fetch ? await readIntakeFunnel() : null
    // The latest gated pass's dry run (#227): what the current profile would discard
    // among the waiting postings once confirmed.
    const pass = intake && await prisma.worker_runs.findFirst({ orderBy: [{ started_at: 'desc' }, { id: 'desc' }],
        select: { counts_json: true } })
    const preview = pass ? parseObject(pass.counts_json).screen : null
    const wouldDiscard = Number.isInteger(preview?.would_discard) ? preview.would_discard as number : null
    return { steps, complete, intake, wouldDiscard }
}

// The copy-paste MCP templates under apps/web/templates/mcp (plain text, shared with
// docs/SETUP.md). Read at request time; the Docker image copies the directory.
const TEMPLATE_FILES = ['claude-code.txt', 'claude-desktop.json', 'codex.txt', 'chatgpt.txt',
    'prompt-set-me-up.txt', 'prompt-log-application.txt', 'prompt-update-from-email.txt'] as const

export async function getMcpTemplates() {
    const dir = path.join(process.cwd(), 'templates', 'mcp')
    return Object.fromEntries(TEMPLATE_FILES.map((f) => [f, readFileSync(path.join(dir, f), 'utf8')])) as
        Record<(typeof TEMPLATE_FILES)[number], string>
}
