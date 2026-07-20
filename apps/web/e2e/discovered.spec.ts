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

test('discovered jobs render in score buckets and the JD modal shows match details', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()

    // Default = Matched bucket: only high scorers (>=75).
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

    // The low scorer lives under the Discarded bucket.
    await page.getByRole('button', { name: /^Discarded$/i }).click()
    await expect(page.getByText('Initech Cloud')).toBeVisible()
})
