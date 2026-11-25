'use server'

import { prisma } from '@/lib/db'
import { type Actor, VALID_SOURCES, RECIPE_SOURCES } from '@/lib/constants'
import { checkedActor } from '@/lib/action-helpers'
import { resolveBoardUrl, SLUG_OK } from '@/lib/board-url'
import { recipeErrors } from '@/lib/recipe-schema'
import { boardHealth } from '@/lib/board-health'
import { parseObject } from '@/lib/pass-record'

// --- Watchlist (DB-backed; the worker fetches these companies in full) ------
// The watchlist moved out of the worker's config.yaml into the DB. The Sources tab and
// the MCP write API (/api/v1/watchlist) both add (by careers URL or source+slug) and
// remove through these actions (#208).

type WatchedRow = { id: number; source: string; slug: string; name: string; recipe: string | null; created_at: string }

function watchlistAudit(actor: Actor, action: 'add' | 'remove', row: WatchedRow) {
    return {
        at: new Date().toISOString(), actor, action,
        entity: 'watched_companies', entity_id: row.id, payload: JSON.stringify(row),
    }
}

// The watchlist with each board's postings fetched in the last 30 days (the MCP
// list_sources figure: same source + company_slug, by created_at) and its last-pass
// record as one `health` state (lib/board-health.ts, the rule MCP applies too). A string
// compare against toISOString(): it agrees with MCP's ats_instant_cmp because the worker
// writes created_at as canonical UTC `...T..:..:..sssZ`; a hand-made non-UTC value could differ.
export async function getWatchedCompanies() {
    const cutoff = new Date(Date.now() - 30 * 86_400_000).toISOString()
    const [rows, total, counts] = await Promise.all([
        prisma.watched_companies.findMany({ orderBy: { name: 'asc' } }),
        prisma.watched_companies.count(),
        prisma.job_postings.groupBy({ by: ['source', 'company_slug'], where: { created_at: { gte: cutoff } }, _count: true }),
    ])
    const n = new Map(counts.map((c) => [`${c.source}/${c.company_slug}`, c._count]))
    return { data: rows.map((r) => ({
        ...r, postings_30d: n.get(`${r.source}/${r.slug}`) ?? 0, health: boardHealth(r),
    })), total }
}

// A browser-recipe board is fetched only while `enable_browser_sources` is on in the
// worker's config.yaml; the web reads that flag from the latest pass record (#233). The
// flag never refuses an add: the row is valid and waits for it.
async function browserWarning(source: string): Promise<string | null> {
    if (source !== 'browser') return null
    const run = await prisma.worker_runs.findFirst({ orderBy: [{ started_at: 'desc' }, { id: 'desc' }], select: { config_json: true } })
    const on = run ? parseObject(run.config_json).browser_sources : undefined
    if (on === true) return null
    return (on === false ? 'Browser sources were off in the latest worker pass'
        : 'No worker pass has recorded whether browser sources are on')
        + ': the worker skips this board unless it starts with enable_browser_sources on in config.yaml.'
}

// A watchlist add by careers/job URL (resolved by lib/board-url.ts, shared with MCP via
// /api/v1/watchlist) or by explicit source + slug. The web cannot fetch a board, so a
// web add is unverified: the row reads `never_fetched` until the next worker pass
// records its health. `dryRun` runs every check and returns the resolved board without
// adding it: MCP add_source calls it, fetches that board through the worker's adapter,
// and adds only a board that lists postings (#231). A board the worker would skip carries
// a `warning` in the returned data, dry run included.
const NEEDS_RECIPE = 'This site needs a custom recipe - set it up from your AI client with the onboard-board skill.'

export async function addWatchedCompany(input: {
    url?: string
    source?: string
    slug?: string
    name: string
    recipe?: string
    dryRun?: boolean
}, actor: Actor = 'web') {
    checkedActor(actor)
    try {
        const url = (input.url || '').trim()
        if (url && (input.source || input.slug)) return { success: false, error: 'give a url or a source and slug, not both' }
        const resolved = url ? resolveBoardUrl(url) : null
        if (url && !resolved) return { success: false, error: NEEDS_RECIPE }
        const source = (resolved?.source ?? input.source ?? '').trim()
        const slug = (resolved?.slug ?? input.slug ?? '').trim()
        const name = (input.name || '').trim()
        const recipeRaw = (input.recipe || '').trim()
        if (!source || !slug || !name) {
            return { success: false, error: 'source, slug, and name are required' }
        }
        // Slug is interpolated into a fetch URL host/path in the worker
        // (e.g. https://{slug}.icims.com). Allow alnum . _ - and single '/'-joined
        // segments (workday "tenant/dc/site", phenom "host/domain"); block host-injection
        // metacharacters (@ : ? # % \ whitespace) and path traversal.
        if (!SLUG_OK(slug, source)) {
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
        const recipeErrs = recipe ? recipeErrors(source, JSON.parse(recipe)) : []
        if (recipeErrs.length) {
            return { success: false, error: `invalid ${source} recipe: ${recipeErrs.join('; ')}` }
        }

        const existing = await prisma.watched_companies.findFirst({
            where: { source, slug },
        })
        if (existing) {
            return { success: false, error: `${source}/${slug} is already on the watchlist` }
        }
        const warning = await browserWarning(source)
        const warned = warning ? { warning } : {}
        if (input.dryRun) return { success: true, data: { source, slug, name, recipe, ...warned } }

        const created = await prisma.$transaction(async (tx) => {
            const row = await tx.watched_companies.create({
                data: { source, slug, name, recipe, created_at: new Date().toISOString() },
            })
            await tx.audit_log.create({ data: watchlistAudit(actor, 'add', row) })
            return row
        })
        return { success: true, data: { ...created, ...warned } }
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
