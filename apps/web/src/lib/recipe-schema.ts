import { z } from 'zod'
import schema from './recipe.schema.json'

// The recipe JSON Schema (recipe.schema.json) on the web side: the one check behind the
// Sources add path, /api/v1/watchlist and so MCP. The worker validates the same file
// (ats_worker/recipe_schema.py); worker/tests/fixtures/recipe-cases.json runs on both.

const VALIDATORS = Object.fromEntries(
    (['custom', 'browser'] as const).map((source) => [
        source,
        z.fromJSONSchema({ ...schema, $ref: `#/$defs/${source}` } as Parameters<typeof z.fromJSONSchema>[0]),
    ]),
) as Record<string, z.ZodType>

function describe(issue: z.core.$ZodIssue): string {
    const where = issue.path.length ? issue.path.join('.') : 'recipe'
    return `${where}: ${issue.message}`
}

/** Every schema violation as '<dotted.path>: <message>'; [] when valid or when the
 * source takes no recipe. */
export function recipeErrors(source: string, recipe: unknown): string[] {
    const validator = VALIDATORS[source]
    if (!validator) return []
    const result = validator.safeParse(recipe)
    return result.success ? [] : result.error.issues.map(describe)
}
