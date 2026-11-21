// Deterministic e2e seed data + helpers, the single source of truth imported
// directly by every spec (re-seed in beforeEach for isolation). Schema init
// happens separately, in the webServer command (see playwright.config.ts).
// Seeds via a PrismaClient pointed at the throwaway DB.
import { PrismaClient } from '@prisma/client'
import { DATABASE_URL } from './db-path.mjs'

// A candidate profile exists, so Discovered Jobs is in JEV mode (#207): only Acme (passed the
// screen, JEV keep) is "for you". Globex (JEV skip), Recent Synthetic (never screened
// or assessed), Initech (failed the screen) and the 30 legacy `scored` rows are not. `screening` and `jev` are created as related rows in seed().
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
        score_detail: null,
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
        score_detail: null, source_content_revision: 1,
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
        score_detail: null, source_content_revision: 1,
        pipeline_status: 'new', created_at: '2026-01-01T00:00:00.000Z',
        screening: '{"disqualified":false,"screen":{"location":{"pass":true}}}',
        jev: { verdict: 'skip', reasons_json: '["preference_weak"]' },
    },
    {
        source: 'ashby', external_id: 'e2e-3', company_slug: 'initech', company_name: 'Initech Cloud',
        job_title: 'Platform Engineer', location: 'Austin',
        job_url: 'https://initech.example/jobs/3', description: 'Run the platform.',
        score_detail: null,
        pipeline_status: 'discarded', created_at: '2026-01-01T00:00:00.000Z',
        screening: '{"disqualified":true,"disqualification_reason":"degree: requires a PhD","screen":{"degree":{"pass":false,"note":"requires a PhD"}}}',
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
    await prisma.audit_log.deleteMany()
    await prisma.job_postings.deleteMany()
    await prisma.applications.deleteMany()
    await prisma.watched_companies.deleteMany()
    await prisma.feed_unresolved.deleteMany()
    await prisma.app_settings.deleteMany()
    await prisma.app_settings.create({ data: CATEGORIES })
    await prisma.job_triage_overrides.deleteMany()
    await prisma.candidate_profile.deleteMany()
}

export async function seed(url = DATABASE_URL) {
    const prisma = client(url)
    try {
        await clear(prisma)
        await prisma.applications.create({ data: EXISTING_APPLICATION })
        await prisma.candidate_profile.create({ data: { id: 1, target_roles: '["Engineer"]',
            actor: 'config', updated_at: '2026-01-01T00:00:00.000Z' } })
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
                score_detail: null, pipeline_status: 'scored',
                created_at: `2025-12-${String(31 - Math.floor((i - 1) / 1)).padStart(2, '0')}T00:00:00.000Z`,
            } })
        }
        for (const c of WATCHED_COMPANIES) await prisma.watched_companies.create({ data: c })
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

// A triage override on a seeded posting, as MCP override_triage would write it.
export async function addOverride(companyName, decision, url = DATABASE_URL) {
    const prisma = client(url)
    try {
        const p = await prisma.job_postings.findFirstOrThrow({ where: { company_name: companyName } })
        await prisma.job_triage_overrides.create({ data: { job_posting_id: p.id, decision, actor: 'mcp',
            source_content_revision: p.source_content_revision, created_at: '2026-01-04T00:00:00.000Z' } })
    } finally {
        await prisma.$disconnect()
    }
}
