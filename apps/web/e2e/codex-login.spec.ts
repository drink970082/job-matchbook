import { expect, test } from '@playwright/test'

test('Codex login notice appears and clears after the next healthy snapshot', async ({ page }) => {
    let authRequired = true
    await page.route('**/api/scorer-usage', route => route.fulfill({
        json: {
            backend: 'codex', auth_required: authRequired,
            limits: [], plan_type: null, as_of: null,
        },
    }))
    await page.goto('/')
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()
    await expect(page.getByRole('status')).toContainText('Codex login needs attention')
    await expect(page.getByText('CODEX_HOME="$HOME/.codex-ats" codex login --device-auth')).toBeVisible()
    authRequired = false
    await page.reload()
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()
    await expect(page.getByText('No scorer usage recorded yet.')).toBeVisible()
    await expect(page.getByText('Codex login needs attention', { exact: false })).toHaveCount(0)
})
