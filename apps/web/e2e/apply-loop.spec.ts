import { expect, test } from '@playwright/test'
import { seed } from './helpers/seed.mjs'

test.beforeEach(async () => {
    await seed()
})

test('marking a discovered job applied moves it into Applications', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()

    const acme = page.locator('tr', { hasText: 'Acme Robotics' })
    await acme.getByTitle('Mark Applied').click()

    // It leaves the actionable queue...
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toHaveCount(0)

    // ...and shows up under Applications.
    await page.getByRole('button', { name: /^Applications$/i }).click()
    await page.getByPlaceholder(/Search companies/i).fill('Acme Robotics')
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toHaveCount(1)
})
