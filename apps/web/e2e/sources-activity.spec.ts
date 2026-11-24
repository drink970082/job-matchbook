import { expect, test } from '@playwright/test'
import { seed } from './helpers/seed.mjs'

test.beforeEach(async () => {
    await seed()
})

test('Sources adds a board from a careers URL and removes one after a confirm', async ({ page }) => {
    await page.goto('/sources')
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toBeVisible()
    await expect(page.getByText('Unresolved feed listings')).toHaveCount(0)

    await page.getByLabel('Careers or job URL').fill('https://www.acme.com/careers')
    await expect(page.getByText(/needs a custom recipe/)).toBeVisible()
    await page.getByLabel('Careers or job URL').fill('https://jobs.lever.co/hooli-labs')
    await expect(page.getByLabel('Company name')).toHaveValue('Hooli Labs')
    await page.getByRole('button', { name: 'Add board' }).click()
    await expect(page.locator('tr', { hasText: 'Hooli Labs' })).toContainText('Never fetched')

    page.once('dialog', (d) => d.accept())
    await page.getByRole('button', { name: 'Remove Hooli Labs' }).click()
    await expect(page.locator('tr', { hasText: 'Hooli Labs' })).toHaveCount(0)

    await page.getByRole('link', { name: 'Activity' }).click()
    await expect(page).toHaveURL(/\/activity$/)
    await expect(page.getByText('Applied to Wayne Enterprises - Software Engineer')).toBeVisible()
    await expect(page.getByText('Added board Hooli Labs')).toBeVisible()
    await expect(page.getByText('Last pass', { exact: true })).toBeVisible()
    await expect(page.getByText('Aged out unevaluated')).toBeVisible()
})
