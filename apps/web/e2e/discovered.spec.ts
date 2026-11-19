import { expect, test } from '@playwright/test'
import { seed } from './helpers/seed.mjs'

test.beforeEach(async () => {
    await seed()
})

test('Discovered Jobs is a read-only funnel that opens on the JEV Keep queue', async ({ page }) => {
    await page.goto('/jobs')

    // Keep is the default view: only the posting JEV kept.
    await expect(page.getByRole('tab', { name: /^Keep/ })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('tab', { name: /^Keep/ })).toContainText('1')
    const acme = page.locator('tr', { hasText: 'Acme Robotics' })
    await expect(acme).toBeVisible()
    await expect(acme).toContainText('Keep')
    await expect(page.getByText('Globex Analytics')).toHaveCount(0)
    // No discard/reopen/bulk controls anywhere in the view.
    await expect(page.getByTitle(/^(Remove|Reopen)$/)).toHaveCount(0)
    await expect(page.getByLabel('Select all')).toHaveCount(0)

    // The Skip audit view says why.
    await page.getByRole('tab', { name: /^JEV skip/ }).click()
    const globex = page.locator('tr', { hasText: 'Globex Analytics' })
    await expect(globex).toContainText('weak match to your preferences')

    // Unassessed: the never-screened posting, with its full JD in the modal.
    await page.getByRole('tab', { name: /^Unassessed/ }).click()
    const recent = page.locator('tr', { hasText: 'Recent Synthetic Systems' })
    await expect(recent).toContainText('No standalone record')
    await recent.getByTitle('View JD').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText('SYNTHETIC FULL JD END.')
    await expect(dialog.getByRole('button', { name: /remove|reopen/i })).toHaveCount(0)
    await page.keyboard.press('Escape')

    // Screen rejected holds the failed hard requirement.
    await page.getByRole('tab', { name: /^Screen rejected/ }).click()
    await expect(page.locator('tr', { hasText: 'Initech Cloud' })).toBeVisible()

    // All: full-text search, and the 34-row inventory pages.
    await page.getByRole('tab', { name: /^All$/ }).click()
    await page.getByRole('combobox', { name: 'Search scope' }).click()
    await page.getByRole('option', { name: 'All text, including JD' }).click()
    const search = page.getByPlaceholder(/search companies, roles, or locations/i)
    await search.fill('inventory-long-jd-keyword')
    await expect(page.getByText('Showing 1–1 of 1')).toBeVisible()
    await search.fill('')
    await expect(page.getByText('Showing 1–25 of 34')).toBeVisible()
    await page.getByRole('button', { name: 'Next page' }).click()
    await expect(page.getByText('Showing 26–34 of 34')).toBeVisible()
})
