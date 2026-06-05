// Standalone Playwright verification for the Discovered Jobs feature.
// Run with the dev server up: `node e2e/discovered.mjs [baseURL]`
import { chromium } from 'playwright'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SHOTS = path.join(__dirname, 'screenshots')
const BASE = process.argv[2] || 'http://localhost:3001'

function assert(cond, msg) {
    if (!cond) throw new Error('ASSERTION FAILED: ' + msg)
    console.log('  ok -', msg)
}

const run = async () => {
    const browser = await chromium.launch()
    const page = await browser.newPage({ viewport: { width: 1280, height: 1200 } })

    console.log('1. Load app')
    await page.goto(BASE, { waitUntil: 'networkidle' })

    console.log('2. Switch to Discovered Jobs tab')
    await page.getByRole('button', { name: /Discovered Jobs/i }).click()
    await page.getByText('Discovered Jobs', { exact: false }).first().waitFor()
    // Assert seeded postings render with scores
    await assert(await page.getByText('Acme Robotics').isVisible(), 'Acme Robotics row visible')
    await assert(await page.getByText('Globex Analytics').isVisible(), 'Globex Analytics row visible')
    await assert(await page.getByText('Initech Cloud').isVisible(), 'Initech Cloud row visible')
    await assert(await page.getByText('91', { exact: true }).first().isVisible(), 'score 91 visible')
    await assert(await page.getByText('78', { exact: true }).first().isVisible(), 'score 78 visible')

    // Single-page warning badge on the 2-page row (Globex)
    const warnBadge = page.locator('[title*="pages"]')
    await assert((await warnBadge.count()) === 1, 'exactly one multi-page warning badge')
    await assert(/2/.test(await warnBadge.first().innerText()), 'warning badge mentions 2 pages')

    await page.screenshot({ path: path.join(SHOTS, '1-discovered-tab.png'), fullPage: true })

    console.log('3. Open JD dialog for Acme and assert matched/missing keywords')
    const acmeRow = page.locator('tr', { hasText: 'Acme Robotics' })
    await acmeRow.getByTitle('View JD').click()
    const dialog = page.getByRole('dialog')
    await dialog.waitFor()
    await assert(await dialog.getByText('Match Analysis').isVisible(), 'Match Analysis section visible')
    await assert(await dialog.getByText('python', { exact: true }).isVisible(), 'matched keyword python visible')
    await assert(await dialog.getByText('aws', { exact: true }).isVisible(), 'matched keyword aws visible')
    await assert(await dialog.getByText('kubernetes', { exact: true }).isVisible(), 'missing keyword kubernetes visible')
    await assert(await dialog.getByText(/Strong backend match/i).isVisible(), 'reasoning text visible')
    await page.screenshot({ path: path.join(SHOTS, '2-jd-dialog.png'), fullPage: true })

    // Close dialog
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'hidden' })

    console.log('4. Mark Applied on Acme row, assert it leaves the discovered list')
    await acmeRow.getByTitle('Mark Applied').click()
    await page.getByText('Acme Robotics').waitFor({ state: 'detached' }).catch(() => {})
    await page.waitForTimeout(800)
    await assert((await page.locator('tr', { hasText: 'Acme Robotics' }).count()) === 0,
        'Acme Robotics removed from discovered queue after Mark Applied')
    await page.screenshot({ path: path.join(SHOTS, '3-after-mark-applied.png'), fullPage: true })

    console.log('5. Switch to Applications tab, assert the new application appears')
    await page.getByRole('button', { name: /^Applications$/i }).click()
    await page.waitForTimeout(500)
    // Search to ensure visibility regardless of pagination
    const search = page.getByPlaceholder(/Search companies/i)
    await search.fill('Acme Robotics')
    await page.waitForTimeout(700)
    await assert((await page.locator('tr', { hasText: 'Acme Robotics' }).count()) > 0,
        'Acme Robotics now appears under Applications')
    await page.screenshot({ path: path.join(SHOTS, '4-applications-tab.png'), fullPage: true })

    await browser.close()
    console.log('\nALL CHECKS PASSED')
}

run().catch((err) => {
    console.error(err)
    process.exit(1)
})
