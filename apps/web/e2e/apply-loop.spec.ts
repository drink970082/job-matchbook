import { expect, test } from '@playwright/test'
import { seed } from './helpers/seed.mjs'

test.beforeEach(async () => {
    await seed()
})

test('marking an All jobs row applied keeps it visibly applied and adds it to Applications', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()

    const recent = page.locator('tr', { hasText: 'Recent Synthetic Systems' })
    await recent.getByTitle('Mark Applied').click()

    // Confirm in the category dialog (defaults to the first category). Scope to the
    // dialog: the row's icon button also has the accessible name "Mark Applied".
    await page.getByRole('dialog').getByRole('button', { name: 'Mark Applied' }).click()

    // All jobs keeps the row visible with its applied lifecycle status.
    await expect(page.locator('tr', { hasText: 'Recent Synthetic Systems' })).toContainText('Applied')

    // ...and shows up under Applications.
    await page.getByRole('button', { name: /^Applications$/i }).click()
    await page.getByPlaceholder(/Search companies/i).fill('Recent Synthetic Systems')
    await expect(page.locator('tr', { hasText: 'Recent Synthetic Systems' })).toHaveCount(1)
})
