import { expect, test } from '@playwright/test'
import { seedEmpty } from './helpers/seed.mjs'

// Re-seeds an EMPTY DB in its own beforeEach, so it's order-independent from the
// other specs (which each seed the standard fixtures in their beforeEach).
test.beforeEach(async () => {
    await seedEmpty()
})

test('the discovered queue shows an empty state when there are no postings', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()
    await expect(page.getByText('No results.')).toBeVisible()
})
