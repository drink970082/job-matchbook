#!/usr/bin/env node
// Dev/local seeder: APPENDS a realistic spread of applications (with status_history
// trails) so the dashboard, KPIs, and charts have something to render. Unlike the
// deterministic e2e fixture (e2e/helpers/seed.mjs) this does NOT clear any tables,
// so it is safe to run against a DB that holds real worker rows (job_postings).
//
// Lives under prisma/ so `@prisma/client` resolves from apps/web/node_modules.
// Usage (from anywhere):
//   node apps/web/prisma/seed-dev.mjs [file:/abs/path/to.db] [count]
// Defaults: url = $DATABASE_URL (or file:./applications.db), count = 40.
import { PrismaClient } from '@prisma/client'

const url = process.argv[2] || process.env.DATABASE_URL || 'file:./applications.db'
const count = Number(process.argv[3] || 40)

// Mirrors apps/web/src/lib/constants.ts (can't import the .ts at runtime).
const CATEGORIES = ['SWE', 'MLE', 'DS', 'DA', 'Quant Dev', 'Quant Analyst', 'Quant Trader', 'AI Engineer', 'Others']
const CATEGORY_WEIGHTS = [6, 4, 2, 1, 2, 1, 1, 2, 1] // SWE/MLE most common

const COMPANIES = [
    'Hooli', 'Pied Piper', 'Initech', 'Globex', 'Soylent', 'Umbrella', 'Stark Industries',
    'Wayne Enterprises', 'Wonka Industries', 'Cyberdyne', 'Tyrell', 'Aperture', 'Nakatomi',
    'Massive Dynamic', 'Vandelay', 'Gekko & Co', 'Bluth', 'Dunder Mifflin', 'Prestige Worldwide',
    'Vehement Capital', 'Acme', 'Black Mesa', 'Oscorp', 'Weyland-Yutani', 'Monarch Sciences',
]
const TITLES = [
    'Software Engineer', 'Backend Engineer', 'Frontend Engineer', 'Full Stack Engineer',
    'Machine Learning Engineer', 'Data Scientist', 'Data Analyst', 'Platform Engineer',
    'Quantitative Developer', 'Quantitative Researcher', 'AI Engineer', 'Infrastructure Engineer',
    'Senior Software Engineer', 'Research Engineer',
]
const LOCATIONS = ['Remote', 'NYC', 'SF Bay Area', 'Seattle', 'Austin', 'Boston', 'Chicago', 'London']

// Each trajectory is the full status path (always starts at "Applied"); the final
// element becomes the application's current status. Weighted toward the funnel
// shape you'd expect (lots of no-response / early rejects, few offers).
const TRAJECTORIES = [
    { path: ['Applied'], weight: 8 }, // awaiting response
    { path: ['Applied', 'Rejected'], weight: 5 },
    { path: ['Applied', 'Ghosted'], weight: 3 },
    { path: ['Applied', 'Online Assessment'], weight: 3 },
    { path: ['Applied', 'Online Assessment', 'Rejected'], weight: 3 },
    { path: ['Applied', 'Online Assessment', 'Phone Screen', 'Rejected'], weight: 2 },
    { path: ['Applied', 'Phone Screen', 'Interviewing: 1st round'], weight: 3 },
    { path: ['Applied', 'Phone Screen', 'Interviewing: 1st round', 'Rejected'], weight: 2 },
    { path: ['Applied', 'Phone Screen', 'Interviewing: 1st round', 'Interviewing: 2nd round', 'Final Round', 'Rejected'], weight: 1 },
    { path: ['Applied', 'Phone Screen', 'Interviewing: 1st round', 'Interviewing: 2nd round', 'Final Round', 'Offer'], weight: 1 },
    { path: ['Applied', 'Online Assessment', 'Phone Screen', 'Interviewing: 1st round', 'Final Round', 'Offer', 'Accepted'], weight: 1 },
    { path: ['Applied', 'Withdrew'], weight: 1 },
]

const pick = (arr) => arr[Math.floor(Math.random() * arr.length)]
const randInt = (lo, hi) => lo + Math.floor(Math.random() * (hi - lo + 1))

function weightedPick(items, weights) {
    const total = weights.reduce((a, b) => a + b, 0)
    let r = Math.random() * total
    for (let i = 0; i < items.length; i++) {
        r -= weights[i]
        if (r <= 0) return items[i]
    }
    return items[items.length - 1]
}

function weightedTrajectory() {
    const total = TRAJECTORIES.reduce((a, t) => a + t.weight, 0)
    let r = Math.random() * total
    for (const t of TRAJECTORIES) {
        r -= t.weight
        if (r <= 0) return t.path
    }
    return TRAJECTORIES[0].path
}

const isoDate = (d) => d.toISOString().slice(0, 10) // YYYY-MM-DD
const dayMs = 24 * 60 * 60 * 1000

async function main() {
    const prisma = new PrismaClient({ datasourceUrl: url })
    try {
        const before = await prisma.applications.count()
        for (let i = 0; i < count; i++) {
            const path = weightedTrajectory()
            // date_applied: random day within the last ~150 days
            const applied = new Date(Date.now() - randInt(1, 150) * dayMs)
            const category = weightedPick(CATEGORIES, CATEGORY_WEIGHTS)
            const company = pick(COMPANIES)
            const title = pick(TITLES)
            const currentStatus = path[path.length - 1]

            // Walk the path forward in time, building status_history timestamps.
            let cursor = applied.getTime()
            const history = path.map((status, idx) => {
                if (idx > 0) cursor += randInt(3, 14) * dayMs // gap between stages
                return { status, timestamp: new Date(cursor).toISOString() }
            })
            const lastUpdated = history[history.length - 1].timestamp

            await prisma.applications.create({
                data: {
                    company_name: company,
                    job_title: title,
                    application_url: `https://${company.toLowerCase().replace(/[^a-z]/g, '')}.example/jobs/${1000 + i}`,
                    date_applied: isoDate(applied),
                    category,
                    status: currentStatus,
                    notes: Math.random() < 0.25 ? `Referred via ${pick(['network', 'recruiter', 'alum', 'cold email'])} · ${pick(LOCATIONS)}` : '',
                    last_updated: lastUpdated,
                    // Only record a history trail when the app actually moved past "Applied".
                    status_history: path.length > 1
                        ? { create: history.map((h) => ({ status: h.status, timestamp: h.timestamp })) }
                        : undefined,
                },
            })
        }
        const after = await prisma.applications.count()
        console.log(`seeded ${after - before} applications (was ${before}, now ${after}) into ${url}`)
    } finally {
        await prisma.$disconnect()
    }
}

main().catch((err) => {
    console.error(err)
    process.exit(1)
})
