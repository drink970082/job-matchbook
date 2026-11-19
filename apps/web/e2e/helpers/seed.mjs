// Deterministic e2e seed data + helpers, the single source of truth imported
// directly by every spec (re-seed in beforeEach for isolation). Schema init
// happens separately, in the webServer command (see playwright.config.ts).
// Seeds via a PrismaClient pointed at the throwaway DB.
import { PrismaClient } from '@prisma/client'
import { DATABASE_URL } from './db-path.mjs'

// One posting per Discovered Jobs stage (#158): Acme passed the screen and JEV kept it
// (Keep, the default view), Globex passed the screen and JEV skipped it (JEV skip),
// Recent Synthetic was never screened or assessed (Unassessed), Initech failed the
// screen (Screen rejected), and the 30 older legacy `scored` rows have moved on
// (Applied / closed). `screening` and `jev` are created as related rows in seed().
export const POSTINGS = [
    {
        source: 'synthetic', external_id: 'e2e-inventory-new', company_slug: 'inventory-new', company_name: 'Recent Synthetic Systems',
        job_title: 'Senior Systems Engineer', location: 'Remote',
        job_url: 'https://synthetic.example/jobs/recent',
        description:
            'SYNTHETIC FULL JD START. This role builds distributed storage, reliability tooling, and ' +
            'developer workflows. It includes a uniquely searchable phrase inventory-long-jd-keyword. ' +
            'The complete fixture description is intentionally long enough to exercise the detail ' +
            'view and includes operating production services, writing design documents, reviewing ' +
            'code, mentoring engineers, and partnering with security and product teams. ' +
            'SYNTHETIC FULL JD END.',
        score: null, score_detail: null,
        pipeline_status: 'new', created_at: '2026-01-03T00:00:00.000Z',
    },
    {
        source: 'greenhouse', external_id: 'e2e-1', company_slug: 'acme', company_name: 'Acme Robotics',
        job_title: 'Backend Engineer', location: 'Remote',
        job_url: 'https://acme.example/jobs/1',
        description:
            'We are looking for a Backend Engineer to design, build, and operate backend ' +
            "systems using Python and AWS. You'll partner with the platform team to scale " +
            'services, write tests, and ship production code that supports our core product.',
        score: null, score_detail: null, source_content_revision: 1,
        pipeline_status: 'new', created_at: '2026-01-02T00:00:00.000Z',
        screening: '{"disqualified":false,"screen":{"location":{"pass":true}}}',
        jev: { verdict: 'keep', reasons_json: '[]' },
    },
    {
        source: 'lever', external_id: 'e2e-2', company_slug: 'globex', company_name: 'Globex Analytics',
        job_title: 'ML Engineer', location: 'NYC',
        job_url: 'https://globex.example/jobs/2',
        description:
            'Train and deploy machine learning models for production workloads, working ' +
            'across the full lifecycle from data pipelines to monitoring. You will ' +
            'collaborate with backend and data teams to ship reliable, well-tested models at scale.',
        score: null, score_detail: null, source_content_revision: 1,
        pipeline_status: 'new', created_at: '2026-01-01T00:00:00.000Z',
        screening: '{"disqualified":false,"screen":{"location":{"pass":true}}}',
        jev: { verdict: 'skip', reasons_json: '["preference_weak"]' },
    },
    {
        source: 'ashby', external_id: 'e2e-3', company_slug: 'initech', company_name: 'Initech Cloud',
        job_title: 'Platform Engineer', location: 'Austin',
        job_url: 'https://initech.example/jobs/3', description: 'Run the platform.',
        score: null, score_detail: null,
        pipeline_status: 'discarded', created_at: '2026-01-01T00:00:00.000Z',
        screening: '{"disqualified":true,"disqualification_reason":"degree: requires a PhD","screen":{"degree":{"pass":false,"note":"requires a PhD"}}}',
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

// Every spec drives an ALREADY-CONFIGURED install. Without a stored categories
// row the dashboard treats the DB as a first run and auto-opens the category
// picker (Dashboard.tsx), whose overlay swallows the very first tab click — so
// omitting this fails every spec on `getByRole('button', {name:/Discovered Jobs/})`.
const CATEGORIES = {
    key: 'categories',
    value: JSON.stringify(['SWE', 'Quant', 'Data', 'Others']),
    updated_at: '2026-01-01T00:00:00.000Z',
}

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
    await prisma.app_settings.deleteMany()
    await prisma.app_settings.create({ data: CATEGORIES })
}

export async function seed(url = DATABASE_URL) {
    const prisma = client(url)
    try {
        await clear(prisma)
        await prisma.applications.create({ data: EXISTING_APPLICATION })
        for (const { screening, jev, ...p } of POSTINGS) {
            const row = await prisma.job_postings.create({ data: p })
            if (screening) {
                await prisma.job_screenings.create({ data: { job_posting_id: row.id, state: 'complete',
                    result_json: screening, backend: 'synthetic', evaluator_version: 'screen-v1',
                    last_attempted_at: '2026-01-03T00:00:00.000Z', completed_at: '2026-01-03T00:00:00.000Z',
                    source_content_revision: p.source_content_revision ?? null, created_at: '2026-01-03T00:00:00.000Z' } })
            }
            if (jev) {
                await prisma.job_jev_assessments.create({ data: { job_posting_id: row.id, state: 'complete', ...jev,
                    policy_sha256: 'e2e-policy', source_content_revision: p.source_content_revision ?? null,
                    last_attempted_at: '2026-01-03T00:00:00.000Z', created_at: '2026-01-03T00:00:00.000Z' } })
            }
        }
        // A deterministic second page proves All jobs recency and pagination without
        // depending on any provider or production database.
        for (let i = 1; i <= 30; i++) {
            await prisma.job_postings.create({ data: {
                source: 'synthetic', external_id: `e2e-inventory-old-${i}`, company_slug: `fixture-${i}`,
                company_name: `Older Synthetic Company ${String(i).padStart(2, '0')}`,
                job_title: `Synthetic Engineer ${String(i).padStart(2, '0')}`,
                location: 'Remote', job_url: `https://synthetic.example/jobs/old-${i}`,
                description: `Synthetic older listing ${i}.`,
                score: 72, score_detail: null, pipeline_status: 'scored',
                created_at: `2025-12-${String(31 - Math.floor((i - 1) / 1)).padStart(2, '0')}T00:00:00.000Z`,
            } })
        }
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
