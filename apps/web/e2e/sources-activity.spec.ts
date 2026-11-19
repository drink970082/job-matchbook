import { expect, test } from '@playwright/test'
import { seed } from './helpers/seed.mjs'

test.beforeEach(async () => {
    await seed()
})

test('Sources and Activity are read-only views of what the worker fetches and who wrote what', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /^Sources/ }).click()
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toBeVisible()
    await expect(page.getByText('BigCo')).toBeVisible()
    await expect(page.getByPlaceholder(/board slug/i)).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^(Add|Remove|Re-add)$/ })).toHaveCount(0)

    await page.getByRole('button', { name: /^Activity/ }).click()
    await expect(page.getByText('Wayne Enterprises - Software Engineer')).toBeVisible()
})
