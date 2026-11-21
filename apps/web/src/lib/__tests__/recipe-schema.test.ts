import fs from 'fs'
import path from 'path'
import { recipeErrors } from '../recipe-schema'
import schema from '../recipe.schema.json'

// Same case list as the worker's test_recipe_schema.py, so the two validators agree.
type Case = { source: string; slug?: string; error?: string; recipe: unknown }
const cases: { valid: Case[]; invalid: Case[] } = JSON.parse(fs.readFileSync(
    path.join(__dirname, '../../../../worker/tests/fixtures/recipe-cases.json'), 'utf8'))

describe('recipe schema', () => {
    it.each(cases.valid.map((c) => [`${c.source}/${c.slug}`, c]))('%s validates', (_, c) => {
        expect(recipeErrors(c.source, c.recipe)).toEqual([])
    })

    it.each(cases.invalid.map((c) => [`${c.source} ${c.error}`, c]))('%s is rejected naming it', (_, c) => {
        const errs = recipeErrors(c.source, c.recipe)
        expect(errs.length).toBeGreaterThan(0)
        expect(errs.some((e) => e.includes(c.error!))).toBe(true)
    })

    it.each(['custom', 'browser'] as const)('the %s examples validate', (source) => {
        const examples = (schema.$defs[source] as { examples: unknown[] }).examples
        expect(examples.length).toBeGreaterThan(0)
        for (const ex of examples) expect(recipeErrors(source, ex)).toEqual([])
    })

    it('does not check a source that takes no recipe', () => {
        expect(recipeErrors('greenhouse', { anything: 1 })).toEqual([])
    })
})
