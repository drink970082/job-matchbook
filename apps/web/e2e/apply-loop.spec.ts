import { expect, test } from '@playwright/test'
import { PrismaClient } from '@prisma/client'
import { DATABASE_URL } from './helpers/db-path.mjs'
import { seed } from './helpers/seed.mjs'

// Recorded by hand, not linked: the same job as the seeded Acme posting (#241).
async function seedUnlinkedApplication() {
    const prisma = new PrismaClient({ datasources: { db: { url: DATABASE_URL } } })
    await prisma.applications.create({ data: { company_name: 'ACME Robotics, Inc.', job_title: 'Backend engineer',
        date_applied: '2026-01-05', category: 'SWE', status: 'Applied', last_updated: '2026-01-05T00:00:00.000Z' } })
    await prisma.$disconnect()
}

test.beforeEach(async () => {
    await seed()
})

test('marking a posting applied removes it from the list and adds it to Applications', async ({ page }) => {
    await page.goto('/jobs')
    await page.locator('tr', { hasText: 'Acme Robotics' }).getByRole('button', { name: /^Mark applied/ }).click()
    // Confirm in the category dialog (defaults to the first category).
    await page.getByRole('dialog').getByRole('button', { name: 'Mark Applied' }).click()
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toHaveCount(0)

    await page.getByRole('link', { name: 'Applications' }).click()
    await page.getByPlaceholder(/Search companies/i).fill('Acme Robotics')
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toHaveCount(1)
})

test('a posting already applied to by hand links to that application from Mark applied', async ({ page }) => {
    await seedUnlinkedApplication()
    await page.goto('/jobs')
    const row = page.locator('tr', { hasText: 'Acme Robotics' })
    await expect(row.getByText(/You may have applied already \(application #\d+\)/)).toBeVisible()
    await row.getByRole('button', { name: /^Mark applied/ }).click()
    await page.getByRole('dialog').getByRole('button', { name: /^Link to application #/ }).click()
    await expect(row).toHaveCount(0)

    await page.getByRole('link', { name: 'Applications' }).click()
    await page.getByPlaceholder(/Search companies/i).fill('Acme Robotics')
    await expect(page.locator('tr', { hasText: 'ACME Robotics' })).toHaveCount(1)
})

test('Applications lists the postings an unlinked application may belong to; one click links', async ({ page }) => {
    await seedUnlinkedApplication()
    await page.goto('/applications')
    const row = page.locator('tr', { hasText: 'ACME Robotics' })
    await expect(row.getByRole('button', { name: /^Link to a posting/ })).toBeVisible()
    await page.getByRole('button', { name: 'Link postings' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText(/Same company and title/)).toBeVisible()
    await dialog.getByRole('button', { name: /^Link ACME Robotics, Inc/ }).click()
    await expect(dialog).toHaveCount(0)
    await expect(row.getByRole('button', { name: /^Link to a posting/ })).toHaveCount(0)
    await page.goto('/jobs')
    await expect(page.locator('tr', { hasText: 'Acme Robotics' })).toHaveCount(0)
})
