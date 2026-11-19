'use server'

import { readFileSync } from 'node:fs'
import path from 'node:path'
import { prisma } from '@/lib/db'

// Web counterpart of MCP get_setup_status (worker read_repository.get_setup_status):
// what a fresh install still needs. Same "configured" rule for the hard requirements.
export async function getSetupStatus() {
    const [pref, sources, jev, firstPosting, mcpWrite] = await Promise.all([
        prisma.candidate_preferences.findUnique({ where: { id: 1 } }),
        prisma.watched_companies.count(),
        prisma.jev_profile.count(),
        prisma.job_postings.findFirst({ select: { id: true } }),
        Promise.all([prisma.audit_log, prisma.applications, prisma.status_history].map((t: any) =>
            t.findFirst({ where: { actor: 'mcp' }, select: { id: true } }))).then((rows) => rows.some(Boolean)),
    ])
    const requirements = !!pref && (
        [pref.highest_degree, pref.work_authorization, pref.security_clearance].some((v) => v.trim())
        || pref.locations.trim() !== '[]' && pref.locations.trim() !== '' || pref.exclude_internships || pref.exclude_contract)
    const steps = {
        // ponytail: "connected" = the MCP server has written through /api/v1 at least once;
        // a read-only connection never ticks it (the step is optional).
        aiClient: mcpWrite,
        requirements,
        sources: sources > 0,
        jev: jev > 0,
        firstFetch: !!firstPosting,
    }
    // Steps 1 (AI client) and 4 (JEV) are optional: a web-only user still finishes.
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
