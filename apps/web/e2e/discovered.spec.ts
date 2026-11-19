import { expect, test } from '@playwright/test'
import { seed } from './helpers/seed.mjs'

test.beforeEach(async () => {
    await seed()
})

test('Discovered Jobs lists only postings for you, as job-board rows', async ({ page }) => {
    await page.goto('/jobs')
    await expect(page.getByText(/JEV assesses postings from the last 7 days only/)).toBeVisible()
    const acme = page.locator('tr', { hasText: 'Acme Robotics' })
    await expect(acme).toBeVisible()
    await expect(acme.getByRole('link', { name: 'Apply' })).toHaveAttribute('href', 'https://acme.example/jobs/1')
    for (const hidden of ['Globex Analytics', 'Recent Synthetic Systems', 'Initech Cloud', 'Older Synthetic Company 01']) {
        await expect(page.getByText(hidden)).toHaveCount(0)
    }
    await expect(page.getByRole('tab')).toHaveCount(0)

    // View JD opens the full description.
    await acme.getByTitle('View JD').click()
    await expect(page.getByRole('dialog')).toContainText('Backend Engineer')
    await page.keyboard.press('Escape')

    // Not interested hides the row; Undo brings it back.
    await acme.getByRole('button', { name: 'Not interested' }).click()
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Undo' }).click()
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toBeVisible()

    // Search in JD reaches description text.
    const search = page.getByPlaceholder(/search companies, roles, or locations/i)
    await search.fill('platform team')
    await expect(page.getByText('No postings match these filters.')).toBeVisible()
    await page.getByLabel('Search in JD').check()
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toBeVisible()
})
