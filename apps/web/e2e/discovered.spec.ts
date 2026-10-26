import { expect, test } from '@playwright/test'
import { seed } from './helpers/seed.mjs'

// Migrated from the legacy discovered.mjs, with the stale selector fixed: the
// matched/missing keywords now live behind the "Match details" toggle. Fixed
// again for the S2.1 scorecard (JobDetailModal parseAssessment) — once
// score_detail carries an `assessment` object the toggle reads "Fit
// assessment" and shows must-haves met/missing + a summary, not the legacy
// "Match details & reasoning" flat keyword lists.
test.beforeEach(async () => {
    await seed()
})

test('All jobs starts with recent unscored work, supports full-text search, pages, and legacy buckets', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()

    // All jobs starts with discovery recency and includes new/unscored rows.
    const recent = page.locator('tr', { hasText: 'Recent Synthetic Systems' })
    await expect(recent).toBeVisible()
    await expect(page.locator('tr').nth(1)).toContainText('Recent Synthetic Systems')
    await expect(recent).toContainText('No standalone record')
    await expect(recent).toContainText('Needs review')
    await expect(page.getByLabel('Select all')).toHaveCount(0)

    // Open and inspect the full synthetic JD, including text omitted from the table.
    await recent.getByTitle('View JD').click()
    const newDialog = page.getByRole('dialog')
    await expect(newDialog).toContainText('SYNTHETIC FULL JD END.')
    await expect(newDialog).toContainText('No standalone record')
    await expect(newDialog).toContainText('Needs review')
    await page.keyboard.press('Escape')

    // Search the long description explicitly; metadata-only remains the default.
    await page.getByRole('combobox', { name: 'Search scope' }).click()
    await page.getByRole('option', { name: 'All text, including JD' }).click()
    const search = page.getByPlaceholder(/search companies, roles, or locations/i)
    await search.fill('inventory-long-jd-keyword')
    await expect(recent).toBeVisible()
    await expect(page.getByText('Showing 1–1 of 1')).toBeVisible()
    await page.getByRole('button', { name: /^Applications$/i }).click()
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()
    await expect(search).toHaveValue('inventory-long-jd-keyword')
    await expect(page.getByRole('combobox', { name: 'Search scope' })).toContainText('All text, including JD')

    // Clearing search restores the frozen 34-row fixture and allows page changes.
    await search.fill('')
    await expect(page.getByText('Showing 1–25 of 34')).toBeVisible()
    await page.getByRole('button', { name: 'Next page' }).click()
    await expect(page.getByText('Showing 26–34 of 34')).toBeVisible()
    await expect(page.getByText('Older Synthetic Company 22')).toBeVisible()
    await page.getByRole('button', { name: 'First page' }).click()

    // Existing fit buckets remain available and their detail stays intact.
    await page.getByRole('button', { name: 'Matched' }).click()
    await expect(page.getByText('Acme Robotics')).toBeVisible()
    await expect(page.getByText('Globex Analytics')).toBeVisible()
    // Initech is hard-disqualified (pipeline_status 'discarded' + disqualified
    // verdict in the seed) -> Discarded, not Matched — not a below-threshold score.
    await expect(page.getByText('Initech Cloud')).toHaveCount(0)

    // Open Acme's JD modal.
    const acme = page.locator('tr', { hasText: 'Acme Robotics' })
    await acme.getByTitle('View JD').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // The fix: the scorecard is collapsed behind the toggle — expand first.
    await dialog.getByRole('button', { name: /Fit assessment/i }).click()
    await expect(dialog.getByText('python', { exact: true })).toBeVisible()
    await expect(dialog.getByText('aws', { exact: true })).toBeVisible()
    await expect(dialog.getByText('kubernetes', { exact: true })).toBeVisible()
    await expect(dialog.getByText(/Strong backend match/i)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dialog).toBeHidden()

    // The hard-constraint disqualification lives under the Discarded bucket.
    await page.getByRole('button', { name: /^Discarded$/i }).click()
    await expect(page.getByText('Initech Cloud')).toBeVisible()
})
