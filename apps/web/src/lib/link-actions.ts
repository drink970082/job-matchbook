'use server'

import { prisma } from '@/lib/db'
import { type Actor } from '@/lib/constants'
import { checkedActor, linkPosting, unlinkedApplications } from '@/lib/action-helpers'
import { rankPostings, type MatchTier } from '@/lib/application-match'

// Linking an application to the posting it was made for (#241). Suggestions are read
// here and shown by web and MCP; a link is always one explicit call naming both ids.

export interface PostingSuggestion {
    tier: MatchTier
    job_id: number
    company_name: string
    job_title: string
    job_url: string
    location: string | null
    posted_at: string | null
    source_state: string
}
export interface LinkSuggestions {
    application: { id: number; company_name: string; job_title: string; application_url: string | null; date_applied: string; status: string }
    suggestions: PostingSuggestion[]
    more: number // candidates past the ones returned (tier 3 only: tiers 1 and 2 are never cut)
}

// Tier-3 candidates returned per application: the whole-list view, and one application.
const PICKER_LIST = 5
const PICKER_ONE = 50

// Link suggestions for unlinked applications: one application, one posting (which
// applications it may already be), or every application that has any candidate.
export async function getLinkSuggestions(filter: { applicationId?: number; jobId?: number } = {}):
    Promise<{ success: true; data: LinkSuggestions[] } | { success: false; error: string }> {
    try {
        const { applicationId, jobId } = filter
        if (applicationId !== undefined) {
            const app = await prisma.applications.findUnique({ where: { id: applicationId }, include: { job_postings: { select: { id: true } } } })
            if (!app) return { success: false, error: 'Application not found' }
            if (app.job_postings.length) {
                return { success: false, error: `Application ${applicationId} is already linked to job ${app.job_postings[0].id}` }
            }
        }
        if (jobId !== undefined) {
            const job = await prisma.job_postings.findUnique({ where: { id: jobId }, select: { application_id: true, pipeline_status: true } })
            if (!job) return { success: false, error: 'Job posting not found' }
            if (job.application_id != null) return { success: false, error: `Job ${jobId} is already linked to application ${job.application_id}` }
        }
        const [apps, postings] = await Promise.all([
            unlinkedApplications(prisma, applicationId),
            prisma.job_postings.findMany({
                where: { application_id: null, pipeline_status: { not: 'removed' }, ...(jobId === undefined ? {} : { id: jobId }) },
                select: { id: true, company_name: true, job_title: true, job_url: true, location: true, posted_at: true, source_state: true },
            }),
        ])
        const keep = applicationId === undefined ? PICKER_LIST : PICKER_ONE
        const data = apps.flatMap((application) => {
            const ranked = rankPostings(application, postings)
            const shown = ranked.filter((p) => p.tier < 3).concat(ranked.filter((p) => p.tier === 3).slice(0, keep))
            if (!shown.length && applicationId === undefined) return []
            const suggestions = shown.map(({ id, ...p }) => ({ job_id: id, ...p }))
            return [{ application, suggestions, more: ranked.length - shown.length }]
        })
        // Best first: the applications a click settles, before the ones that only have a picker.
        data.sort((a, b) => (a.suggestions[0]?.tier ?? 9) - (b.suggestions[0]?.tier ?? 9) || b.application.id - a.application.id)
        return { success: true, data }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function linkApplication(applicationId: number, jobId: number, actor: Actor = 'web') {
    try {
        checkedActor(actor)
        await prisma.$transaction((tx) => linkPosting(tx, applicationId, jobId, actor))
        return { success: true as const, data: { application_id: applicationId, job_id: jobId, pipeline_status: 'applied' } }
    } catch (error: any) {
        return { success: false as const, error: error.message as string }
    }
}
