/**
 * Integration tests: promotion-suggestion server actions against a REAL throwaway
 * SQLite. Covers what mocked unit tests can't — the grouped/conditional-count
 * aggregation, the HAVING qualification rule, NOT EXISTS exclusions (watchlist +
 * dismissed), ordering, and the dismiss round-trip.
 */
import {
    getPromotionSuggestions,
    dismissPromotion,
} from '@/lib/promotion-actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeJobPosting, makeWatchedCompany } from '@/test-utils/factories'

beforeEach(async () => {
    await resetDb()
    // resetDb() doesn't touch promotion_dismissed; clear it for isolation.
    await prisma.$executeRawUnsafe('DELETE FROM promotion_dismissed')
})
afterAll(() => prisma.$disconnect())

// Seed one posting; external_id must be unique within a source.
let seq = 0
async function seedPosting(over: Record<string, unknown>) {
    seq += 1
    return prisma.job_postings.create({
        data: makeJobPosting({ external_id: `e${seq}`, ...over }) as any,
    })
}

test('aggregates qualifying companies with counts and ordering', async () => {
    // Acme (greenhouse): 1 applied + 1 notified -> qualifies (applied >= 1).
    await seedPosting({ source: 'greenhouse', company_slug: 'acme', company_name: 'Acme', pipeline_status: 'applied' })
    await seedPosting({ source: 'greenhouse', company_slug: 'acme', company_name: 'Acme', pipeline_status: 'notified' })
    await seedPosting({ source: 'greenhouse', company_slug: 'acme', company_name: 'Acme', pipeline_status: 'scored' })

    // Globex (lever): 2 tailored, 0 applied -> qualifies (highScores >= 2).
    await seedPosting({ source: 'lever', company_slug: 'globex', company_name: 'Globex', pipeline_status: 'tailored' })
    await seedPosting({ source: 'lever', company_slug: 'globex', company_name: 'Globex', pipeline_status: 'tailored' })

    // Initech (ashby): only 1 tailored, 0 applied -> does NOT qualify.
    await seedPosting({ source: 'ashby', company_slug: 'initech', company_name: 'Initech', pipeline_status: 'tailored' })
    await seedPosting({ source: 'ashby', company_slug: 'initech', company_name: 'Initech', pipeline_status: 'scored' })

    // Legacy null-slug rows are ignored entirely.
    await seedPosting({ source: 'greenhouse', company_slug: null, company_name: 'Legacy', pipeline_status: 'applied' })

    const { data } = await getPromotionSuggestions()

    expect(data.map((c) => `${c.source}/${c.slug}`)).toEqual([
        'greenhouse/acme', // applied=1 sorts first (applied DESC)
        'lever/globex',    // applied=0
    ])

    const acme = data.find((c) => c.slug === 'acme')!
    expect(acme).toMatchObject({ source: 'greenhouse', name: 'Acme', applied: 1, highScores: 2, total: 3 })

    const globex = data.find((c) => c.slug === 'globex')!
    expect(globex).toMatchObject({ source: 'lever', name: 'Globex', applied: 0, highScores: 2, total: 2 })

    // numeric coercion (no BigInt leaks through)
    expect(typeof acme.applied).toBe('number')
    expect(typeof acme.total).toBe('number')
})

test('orders by applied DESC then highScores DESC', async () => {
    // A: applied=1, highScores=1
    await seedPosting({ source: 'greenhouse', company_slug: 'a', company_name: 'A', pipeline_status: 'applied' })
    // B: applied=2, highScores=2  -> most applied, first
    await seedPosting({ source: 'lever', company_slug: 'b', company_name: 'B', pipeline_status: 'applied' })
    await seedPosting({ source: 'lever', company_slug: 'b', company_name: 'B', pipeline_status: 'applied' })
    // C: applied=0, highScores=3  -> qualifies via highScores, sorts last
    await seedPosting({ source: 'ashby', company_slug: 'c', company_name: 'C', pipeline_status: 'tailored' })
    await seedPosting({ source: 'ashby', company_slug: 'c', company_name: 'C', pipeline_status: 'notified' })
    await seedPosting({ source: 'ashby', company_slug: 'c', company_name: 'C', pipeline_status: 'tailored' })

    const { data } = await getPromotionSuggestions()
    expect(data.map((c) => c.slug)).toEqual(['b', 'a', 'c'])
})

test('excludes watchlisted and dismissed companies', async () => {
    // Watched (greenhouse/acme): excluded even though it qualifies.
    await seedPosting({ source: 'greenhouse', company_slug: 'acme', company_name: 'Acme', pipeline_status: 'applied' })
    await prisma.watched_companies.create({
        data: makeWatchedCompany({ source: 'greenhouse', slug: 'acme', name: 'Acme' }) as any,
    })

    // Dismissed (lever/globex): excluded.
    await seedPosting({ source: 'lever', company_slug: 'globex', company_name: 'Globex', pipeline_status: 'applied' })
    await prisma.promotion_dismissed.create({
        data: { source: 'lever', slug: 'globex', created_at: new Date().toISOString() },
    })

    // Surviving suggestion.
    await seedPosting({ source: 'ashby', company_slug: 'initech', company_name: 'Initech', pipeline_status: 'applied' })

    const { data } = await getPromotionSuggestions()
    expect(data.map((c) => `${c.source}/${c.slug}`)).toEqual(['ashby/initech'])
})

test('dismissPromotion excludes the company from later suggestions', async () => {
    await seedPosting({ source: 'greenhouse', company_slug: 'acme', company_name: 'Acme', pipeline_status: 'applied' })

    expect((await getPromotionSuggestions()).data.map((c) => c.slug)).toEqual(['acme'])

    const res = await dismissPromotion('greenhouse', 'acme')
    expect(res.success).toBe(true)

    expect((await getPromotionSuggestions()).data).toEqual([])
})

test('dismissPromotion is idempotent on a duplicate (source, slug)', async () => {
    const first = await dismissPromotion('greenhouse', 'acme')
    expect(first.success).toBe(true)

    const second = await dismissPromotion('greenhouse', 'acme')
    expect(second.success).toBe(true)

    const count = await prisma.promotion_dismissed.count()
    expect(count).toBe(1)
})
