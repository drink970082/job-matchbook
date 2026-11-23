'use server'

import { readFileSync } from 'node:fs'
import path from 'node:path'
import { prisma } from '@/lib/db'
import { profileView, requirementsConfigured } from '@/lib/candidate-profile'

// Web counterpart of MCP get_setup_status (worker read_repository.get_setup_status):
// what a fresh install still needs. Same "configured" rule for the hard requirements.
export async function getSetupStatus() {
    const [row, sources, firstPosting, mcpWrite] = await Promise.all([
        prisma.candidate_profile.findUnique({ where: { id: 1 } }),
        prisma.watched_companies.count(),
        prisma.job_postings.findFirst({ select: { id: true } }),
        Promise.all([prisma.audit_log, prisma.applications, prisma.status_history].map((t: any) =>
            t.findFirst({ where: { actor: 'mcp' }, select: { id: true } }))).then((rows) => rows.some(Boolean)),
    ])
    const profile = row ? profileView(row) : null
    const steps = {
        // ponytail: "connected" = the MCP server has written through /api/v1 at least once;
        // a read-only connection never ticks it (the step is optional).
        aiClient: mcpWrite,
        requirements: !!profile && requirementsConfigured(profile),
        sources: sources > 0,
        triage: !!profile?.triage_configured,
        firstFetch: !!firstPosting,
    }
    // Steps 1 (AI client) and 4 (triage) are optional: a web-only user still finishes.
    return { steps, complete: steps.requirements && steps.sources && steps.firstFetch }
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
