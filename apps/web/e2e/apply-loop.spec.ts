import { expect, test } from '@playwright/test'
import { seed } from './helpers/seed.mjs'

test.beforeEach(async () => {
    await seed()
})

test('marking a posting applied removes it from the list and adds it to Applications', async ({ page }) => {
    await page.goto('/jobs')
    await page.locator('tr', { hasText: 'Acme Robotics' }).getByRole('button', { name: 'Mark applied' }).click()
    // Confirm in the category dialog (defaults to the first category).
    await page.getByRole('dialog').getByRole('button', { name: 'Mark Applied' }).click()
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toHaveCount(0)

    await page.getByRole('link', { name: 'Applications' }).click()
    await page.getByPlaceholder(/Search companies/i).fill('Acme Robotics')
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toHaveCount(1)
})
