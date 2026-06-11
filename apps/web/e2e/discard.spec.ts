import { expect, test } from '@playwright/test'
import { seed } from './helpers/seed.mjs'

test.beforeEach(async () => {
    await seed()
})

test('discarding a posting removes it from the actionable queue', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()

    const initech = page.locator('tr', { hasText: 'Initech Cloud' })
    await expect(initech).toBeVisible()
    await initech.getByTitle('Discard').click()

    await expect(page.locator('tr', { hasText: 'Initech Cloud' })).toHaveCount(0)
})
