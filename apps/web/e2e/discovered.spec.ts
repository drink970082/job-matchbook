import { expect, test } from '@playwright/test'
import { seed } from './helpers/seed.mjs'

// Migrated from the legacy discovered.mjs, with the stale selector fixed: the
// matched/missing keywords now live behind the "Match details" toggle.
test.beforeEach(async () => {
    await seed()
})

test('discovered jobs render with scores and the JD modal shows match details', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()

    await expect(page.getByText('Acme Robotics')).toBeVisible()
    await expect(page.getByText('Globex Analytics')).toBeVisible()
    await expect(page.getByText('Initech Cloud')).toBeVisible()

    // Exactly one multi-page warning badge (Globex has resume_pages = 2).
    await expect(page.locator('[title*="pages"]')).toHaveCount(1)

    // Open Acme's JD modal.
    const acme = page.locator('tr', { hasText: 'Acme Robotics' })
    await acme.getByTitle('View JD').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // The fix: keywords/reasoning are collapsed behind the toggle — expand first.
    await dialog.getByRole('button', { name: /Match details/i }).click()
    await expect(dialog.getByText('python', { exact: true })).toBeVisible()
    await expect(dialog.getByText('aws', { exact: true })).toBeVisible()
    await expect(dialog.getByText('kubernetes', { exact: true })).toBeVisible()
    await expect(dialog.getByText(/Strong backend match/i)).toBeVisible()
})
