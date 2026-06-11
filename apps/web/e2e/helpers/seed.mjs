// Deterministic e2e seed data + helpers, the single source of truth reused by
// global-setup, every spec (re-seed in beforeEach for isolation), and the CLI
// seeder (tools/seed_db.mjs). Seeds via a PrismaClient pointed at the throwaway DB.
import { PrismaClient } from '@prisma/client'
import { DATABASE_URL } from './db-path.mjs'

export const POSTINGS = [
    {
        source: 'greenhouse', external_id: 'e2e-1', company_name: 'Acme Robotics',
        job_title: 'Backend Engineer', location: 'Remote',
        job_url: 'https://acme.example/jobs/1',
        description: 'Build backend systems with Python and AWS.',
        score: 91,
        score_detail: JSON.stringify({
            matched_keywords: ['python', 'aws'],
            missing_keywords: ['kubernetes'],
            reasoning: 'Strong backend match on the core stack.',
        }),
        resume_path: '/resumes/acme.pdf', resume_pages: 1,
        pipeline_status: 'scored', created_at: '2026-01-01T00:00:00.000Z',
    },
    {
        source: 'lever', external_id: 'e2e-2', company_name: 'Globex Analytics',
        job_title: 'ML Engineer', location: 'NYC',
        job_url: 'https://globex.example/jobs/2', description: 'Train models.',
        score: 78, score_detail: null,
        resume_path: '/resumes/globex.pdf', resume_pages: 2, // multi-page warning row
        pipeline_status: 'tailored', created_at: '2026-01-01T00:00:00.000Z',
    },
    {
        source: 'ashby', external_id: 'e2e-3', company_name: 'Initech Cloud',
        job_title: 'Platform Engineer', location: 'Austin',
        job_url: 'https://initech.example/jobs/3', description: 'Run the platform.',
        score: 65, score_detail: null,
        resume_path: null, resume_pages: null,
        pipeline_status: 'scored', created_at: '2026-01-01T00:00:00.000Z',
    },
]

export const EXISTING_APPLICATION = {
    company_name: 'Wayne Enterprises', job_title: 'Software Engineer',
    application_url: 'https://wayne.example', date_applied: '2026-01-02',
    category: 'SWE', status: 'Applied', notes: '',
    last_updated: '2026-01-02T00:00:00.000Z',
}

function client(url) {
    return new PrismaClient({ datasourceUrl: url })
}

async function clear(prisma) {
    await prisma.status_history.deleteMany()
    await prisma.job_postings.deleteMany()
    await prisma.applications.deleteMany()
}

export async function seed(url = DATABASE_URL) {
    const prisma = client(url)
    try {
        await clear(prisma)
        await prisma.applications.create({ data: EXISTING_APPLICATION })
        for (const p of POSTINGS) await prisma.job_postings.create({ data: p })
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
