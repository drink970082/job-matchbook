// Deterministic e2e seed data + helpers, the single source of truth imported
// directly by every spec (re-seed in beforeEach for isolation). Schema init
// happens separately, in the webServer command (see playwright.config.ts).
// Seeds via a PrismaClient pointed at the throwaway DB.
import { PrismaClient } from '@prisma/client'
import { DATABASE_URL } from './db-path.mjs'

// Acme/Globex must satisfy the matched-bucket predicate exactly as read by
// matchedIds() (actions.ts:192-199 — the SAME verdict gate as the worker's
// notify gate, ats_worker/db.py get_notifiable): pipeline_status IN
// ('scored','notified') AND assessment.seniority.verdict === 'match' AND
// assessment.domain.verdict === 'match' AND NOT insufficient_context. They
// also need a description >= LOW_CONTEXT_MAX_DESCRIPTION_LENGTH (200 chars,
// src/lib/constants.ts) or lowContextIds() reroutes them to Low-context before
// the Matched query ever sees them. Initech is disqualified (pipeline_status
// 'discarded' + score_detail.disqualified) so it lands in the literal
// Discarded bucket the discovered.spec.ts assertion checks — a below-bar
// (scored-but-non-matching) row would land in Below bar instead, not Discarded.
//
// score_detail's `assessment` shape mirrors the worker's real S2.1 scorecard
// (apps/worker/ats_worker/pipeline.py _score_detail / tests/test_score.py
// _assessment helper): { seniority, domain, must_haves: {met,missing},
// nice_to_haves: {missing}, summary }. Once `assessment` is present at all,
// JobDetailModal (src/components/JobDetailModal.tsx parseAssessment) always
// renders the scorecard branch ("Fit assessment" toggle + must-haves badges +
// summary) instead of the legacy flat matched_keywords/missing_keywords/
// reasoning fallback — there's no score_detail shape that satisfies
// matchedIds() while keeping the legacy modal rendering, since the SQL
// predicate and the client parse the same JSON blob.
export const POSTINGS = [
    {
        source: 'greenhouse', external_id: 'e2e-1', company_slug: 'acme', company_name: 'Acme Robotics',
        job_title: 'Backend Engineer', location: 'Remote',
        job_url: 'https://acme.example/jobs/1',
        description:
            'We are looking for a Backend Engineer to design, build, and operate backend ' +
            "systems using Python and AWS. You'll partner with the platform team to scale " +
            'services, write tests, and ship production code that supports our core product.',
        score: 91,
        score_detail: JSON.stringify({
            assessment: {
                seniority: { verdict: 'match', note: '' },
                domain: { verdict: 'match', note: '' },
                must_haves: { met: ['python', 'aws'], missing: ['kubernetes'] },
                nice_to_haves: { missing: [] },
                summary: 'Strong backend match on the core stack.',
            },
        }),
        pipeline_status: 'scored', created_at: '2026-01-01T00:00:00.000Z',
    },
    {
        source: 'lever', external_id: 'e2e-2', company_slug: 'globex', company_name: 'Globex Analytics',
        job_title: 'ML Engineer', location: 'NYC',
        job_url: 'https://globex.example/jobs/2',
        description:
            'Train and deploy machine learning models for production workloads, working ' +
            'across the full lifecycle from data pipelines to monitoring. You will ' +
            'collaborate with backend and data teams to ship reliable, well-tested models at scale.',
        score: 78,
        score_detail: JSON.stringify({
            assessment: {
                seniority: { verdict: 'match', note: '' },
                domain: { verdict: 'match', note: '' },
                must_haves: { met: ['python', 'pytorch'], missing: [] },
                nice_to_haves: { missing: ['spark'] },
                summary: 'Solid ML fundamentals with production training experience.',
            },
        }),
        pipeline_status: 'notified', created_at: '2026-01-01T00:00:00.000Z',
    },
    {
        source: 'ashby', external_id: 'e2e-3', company_slug: 'initech', company_name: 'Initech Cloud',
        job_title: 'Platform Engineer', location: 'Austin',
        job_url: 'https://initech.example/jobs/3', description: 'Run the platform.',
        score: 65,
        score_detail: JSON.stringify({
            disqualified: true,
            disqualification_reason: 'location: onsite only, no remote/relocation offered',
        }),
        pipeline_status: 'discarded', created_at: '2026-01-01T00:00:00.000Z',
    },
]

// A couple of recorded unresolved feed listings so the Unresolved tab renders.
export const FEED_UNRESOLVED = [
    {
        feed: 'simplify', url: 'https://careers.bigco.com/job/1?gh_jid=1',
        company_name: 'BigCo', job_title: 'Software Engineer',
        host: 'careers.bigco.com', reason: 'embedded_greenhouse',
        created_at: '2026-01-01T00:00:00.000Z',
    },
    {
        feed: 'simplify', url: 'https://jobs.jobvite.com/foocorp/job/2',
        company_name: 'FooCorp', job_title: 'Engineer',
        host: 'jobs.jobvite.com', reason: 'unsupported_host',
        created_at: '2026-01-01T00:00:00.000Z',
    },
]

export const EXISTING_APPLICATION = {
    company_name: 'Wayne Enterprises', job_title: 'Software Engineer',
    application_url: 'https://wayne.example', date_applied: '2026-01-02',
    category: 'SWE', status: 'Applied', notes: '',
    last_updated: '2026-01-02T00:00:00.000Z',
}

export const WATCHED_COMPANIES = [
    { source: 'greenhouse', slug: 'acme', name: 'Acme Robotics', created_at: '2026-01-01T00:00:00.000Z' },
    { source: 'lever', slug: 'globex', name: 'Globex Analytics', created_at: '2026-01-01T00:00:00.000Z' },
]

function client(url) {
    return new PrismaClient({ datasourceUrl: url })
}

async function clear(prisma) {
    await prisma.status_history.deleteMany()
    await prisma.job_postings.deleteMany()
    await prisma.applications.deleteMany()
    await prisma.watched_companies.deleteMany()
    await prisma.feed_unresolved.deleteMany()
    await prisma.promotion_dismissed.deleteMany()
}

export async function seed(url = DATABASE_URL) {
    const prisma = client(url)
    try {
        await clear(prisma)
        await prisma.applications.create({ data: EXISTING_APPLICATION })
        for (const p of POSTINGS) await prisma.job_postings.create({ data: p })
        for (const c of WATCHED_COMPANIES) await prisma.watched_companies.create({ data: c })
        for (const u of FEED_UNRESOLVED) await prisma.feed_unresolved.create({ data: u })
    } finally {
        await prisma.$disconnect()
    }
}

export async function seedEmpty(url = DATABASE_URL) {
    const prisma = client(url)
    try {
        await clear(prisma)
    } finally {
        await prisma.$disconnect()
    }
}
