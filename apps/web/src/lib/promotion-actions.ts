'use server'

import { prisma } from '@/lib/db'
import { Prisma } from '@prisma/client'

// --- Promotion suggestions (feed -> watchlist) ------------------------------
// Surface non-watchlisted companies whose feed-discovered postings keep scoring
// well / getting applied to, so the user can promote them to the watchlist
// (approve, via the existing addWatchedCompany) or dismiss them.
//
// A company (source, company_slug) qualifies when its postings show repeated
// downstream traction: >= 2 postings reached tailored/notified/applied, OR
// >= 1 posting was actually applied to. Companies already on the watchlist or
// previously dismissed are excluded.

export interface PromotionSuggestion {
    source: string
    slug: string
    name: string
    applied: number
    highScores: number
    total: number
}

// Raw SQL: conditional counts + NOT EXISTS subqueries are far cleaner than the
// Prisma query API here. Table names match the Prisma model names (no @@map).
const SUGGESTIONS_SQL = `
  SELECT jp.source AS source, jp.company_slug AS slug, MAX(jp.company_name) AS name,
    SUM(CASE WHEN jp.pipeline_status='applied' THEN 1 ELSE 0 END) AS applied,
    SUM(CASE WHEN jp.pipeline_status IN ('tailored','notified','applied') THEN 1 ELSE 0 END) AS highScores,
    COUNT(*) AS total
  FROM job_postings jp
  WHERE jp.company_slug IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM watched_companies w WHERE w.source=jp.source AND w.slug=jp.company_slug)
    AND NOT EXISTS (SELECT 1 FROM promotion_dismissed d WHERE d.source=jp.source AND d.slug=jp.company_slug)
  GROUP BY jp.source, jp.company_slug
  HAVING SUM(CASE WHEN jp.pipeline_status IN ('tailored','notified','applied') THEN 1 ELSE 0 END) >= 2
      OR SUM(CASE WHEN jp.pipeline_status='applied' THEN 1 ELSE 0 END) >= 1
  ORDER BY applied DESC, highScores DESC
`

export async function getPromotionSuggestions(): Promise<{ data: PromotionSuggestion[] }> {
    // SQLite returns SUM/COUNT as number or BigInt depending on magnitude —
    // coerce every numeric field with Number(...) so callers see plain numbers.
    const rows = await prisma.$queryRawUnsafe<
        Array<{
            source: string
            slug: string
            name: string
            applied: number | bigint
            highScores: number | bigint
            total: number | bigint
        }>
    >(SUGGESTIONS_SQL)

    const data: PromotionSuggestion[] = rows.map((r) => ({
        source: r.source,
        slug: r.slug,
        name: r.name,
        applied: Number(r.applied),
        highScores: Number(r.highScores),
        total: Number(r.total),
    }))

    return { data }
}

export async function dismissPromotion(source: string, slug: string) {
    try {
        const cleanSource = (source || '').trim()
        const cleanSlug = (slug || '').trim()
        if (!cleanSource || !cleanSlug) {
            return { success: false, error: 'source and slug are required' }
        }

        try {
            await prisma.promotion_dismissed.create({
                data: {
                    source: cleanSource,
                    slug: cleanSlug,
                    created_at: new Date().toISOString(),
                },
            })
        } catch (error: any) {
            // Idempotent: a duplicate (source, slug) is a no-op success.
            if (
                error instanceof Prisma.PrismaClientKnownRequestError &&
                error.code === 'P2002'
            ) {
                return { success: true }
            }
            throw error
        }

        return { success: true }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}
