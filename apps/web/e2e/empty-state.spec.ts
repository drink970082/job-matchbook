import { expect, test } from '@playwright/test'
import { seedEmpty } from './helpers/seed.mjs'

// Re-seeds an EMPTY DB in its own beforeEach, so it's order-independent from the
// other specs (which each seed the standard fixtures in their beforeEach).
test.beforeEach(async () => {
    await seedEmpty()
})

test('the discovered queue shows an empty state when there are no postings', async ({ page }) => {
    await page.goto('/jobs')
    await expect(page.getByText('No postings for you yet.')).toBeVisible()
    await expect(page.getByText(/passed your hard requirements/)).toBeVisible()
})

test('/ lands on Applications, each tab is its own route, and a fresh install shows the setup checklist', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/applications$/)
    await expect(page.getByText('Get set up')).toBeVisible()
    await page.getByRole('link', { name: 'Settings', exact: true }).first().click()
    await expect(page).toHaveURL(/\/settings$/)
    await expect(page.getByText('Application categories')).toBeVisible()
    await page.reload()
    await expect(page.getByRole('link', { name: 'Settings', exact: true }).first()).toHaveAttribute('aria-current', 'page')
})
