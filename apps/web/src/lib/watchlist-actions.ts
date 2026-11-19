'use server'

import { prisma } from '@/lib/db'
import { type Actor, VALID_SOURCES, RECIPE_SOURCES } from '@/lib/constants'
import { checkedActor } from '@/lib/action-helpers'

// --- Watchlist (DB-backed; the worker fetches these companies in full) ------
// The watchlist moved out of the worker's config.yaml into the DB so it can be
// managed here: manual list / add / remove. Promotion suggestions
// (feed -> watchlist) shipped since, and live in lib/promotion-actions.ts.

type WatchedRow = { id: number; source: string; slug: string; name: string; recipe: string | null; created_at: string }

function watchlistAudit(actor: Actor, action: 'add' | 'remove', row: WatchedRow) {
    return {
        at: new Date().toISOString(), actor, action,
        entity: 'watched_companies', entity_id: row.id, payload: JSON.stringify(row),
    }
}

// Recent watchlist adds/removes, newest first, with the row as it was then.
export async function getWatchlistActivity(limit = 20) {
    const take = Number.isInteger(limit) ? Math.min(Math.max(limit, 1), 100) : 20
    const rows = await prisma.audit_log.findMany({
        where: { entity: 'watched_companies' }, orderBy: { id: 'desc' }, take,
    })
    return { data: rows.map((r) => ({ ...r, payload: JSON.parse(r.payload) as WatchedRow })) }
}

export async function getWatchedCompanies() {
    const [data, total] = await Promise.all([
        prisma.watched_companies.findMany({ orderBy: { name: 'asc' } }),
        prisma.watched_companies.count(),
    ])
    return { data, total }
}

export async function addWatchedCompany(input: {
    source: string
    slug: string
    name: string
    recipe?: string
}, actor: Actor = 'web') {
    checkedActor(actor)
    try {
        const source = (input.source || '').trim()
        const slug = (input.slug || '').trim()
        const name = (input.name || '').trim()
        const recipeRaw = (input.recipe || '').trim()
        if (!source || !slug || !name) {
            return { success: false, error: 'source, slug, and name are required' }
        }
        // Slug is interpolated into a fetch URL host/path in the worker
        // (e.g. https://{slug}.icims.com). Allow alnum . _ - and single '/'-joined
        // segments (workday "tenant/dc/site", phenom "host/domain"); block host-injection
        // metacharacters (@ : ? # % \ whitespace) and path traversal.
        if (!/^[A-Za-z0-9._/-]+$/.test(slug) || slug.includes('..') ||
            slug.startsWith('/') || slug.endsWith('/') || slug.includes('//')) {
            return { success: false, error: 'slug contains invalid characters' }
        }
        if (!(VALID_SOURCES as readonly string[]).includes(source)) {
            return { success: false, error: `Unknown source: ${source}` }
        }

        // custom/browser rows are recipe-driven: parse the JSON and require it.
        let recipe: string | null = null
        if (recipeRaw) {
            let parsed: unknown
            try {
                parsed = JSON.parse(recipeRaw)
            } catch {
                return { success: false, error: 'recipe must be valid JSON' }
            }
            if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
                return { success: false, error: 'recipe must be a JSON object' }
            }
            recipe = JSON.stringify(parsed)   // store normalized JSON
        }
        if ((RECIPE_SOURCES as readonly string[]).includes(source) && !recipe) {
            return { success: false, error: `source '${source}' requires a recipe (JSON object)` }
        }

        const existing = await prisma.watched_companies.findFirst({
            where: { source, slug },
        })
        if (existing) {
            return { success: false, error: `${source}/${slug} is already on the watchlist` }
        }

        const created = await prisma.$transaction(async (tx) => {
            const row = await tx.watched_companies.create({
                data: { source, slug, name, recipe, created_at: new Date().toISOString() },
            })
            await tx.audit_log.create({ data: watchlistAudit(actor, 'add', row) })
            return row
        })
        return { success: true, data: created }
    } catch (error: any) {
        return { success: false, error: error.message }
    }
}

export async function removeWatchedCompany(id: number, actor: Actor = 'web') {
    checkedActor(actor)
    try {
        // The full row goes into the audit so the removal can be re-added from web.
        const removed = await prisma.$transaction(async (tx) => {
            const row = await tx.watched_companies.delete({ where: { id } })
            await tx.audit_log.create({ data: watchlistAudit(actor, 'remove', row) })
            return row
        })
        return { success: true, data: removed }
    } catch (error: any) {
        if (error?.code === 'P2025') return { success: false, error: `Watchlist entry ${id} not found` }
        return { success: false, error: error.message }
    }
}
