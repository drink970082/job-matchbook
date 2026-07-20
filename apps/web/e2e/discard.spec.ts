import { expect, test } from '@playwright/test'
import { seed } from './helpers/seed.mjs'

test.beforeEach(async () => {
    await seed()
})

test('discarding a posting removes it from the Matched view', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()

    // Globex (score 78) sits in the default Matched bucket; discard it from there.
    // (The row action is titled "Remove" — it writes pipeline_status='removed',
    // distinct from the auto-disqualified 'discarded' status/bucket; see
    // actions.ts discardJobPosting.)
    const globex = page.locator('tr', { hasText: 'Globex Analytics' })
    await expect(globex).toBeVisible()
    await globex.getByTitle('Remove').click()

    await expect(page.locator('tr', { hasText: 'Globex Analytics' })).toHaveCount(0)
})
