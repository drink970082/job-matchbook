/**
 * Integration tests for the chart-data aggregations (getStatusFlow / getTimelineData
 * / getCategoryData) against a REAL throwaway SQLite. These actions feed the Sankey /
 * heatmap / donut and had no unit, integration, or e2e coverage — only their
 * components render — so a regression in the aggregation would have passed CI.
 */
import { getStatusFlow, getTimelineData, getCategoryData } from '@/lib/actions'
import { prisma, resetDb } from '@/test-utils/db'
import { makeApplication, makeStatusHistory } from '@/test-utils/factories'

beforeEach(resetDb)
afterAll(() => prisma.$disconnect())

// Create an application plus its ordered status_history chain, returning the app id.
async function appWithHistory(status: string, historyStatuses: string[]) {
    const app = await prisma.applications.create({ data: makeApplication({ status }) })
    for (let i = 0; i < historyStatuses.length; i++) {
        await prisma.status_history.create({
            data: makeStatusHistory({
                application_id: app.id,
                status: historyStatuses[i],
                // Distinct ascending timestamps so the `orderBy timestamp asc` is exercised.
                timestamp: `2026-01-0${i + 1}T00:00:00.000Z`,
            }),
        })
    }
    return app.id
}

// --- getStatusFlow --------------------------------------------------------

test('getStatusFlow returns no flows for an empty DB', async () => {
    const res = await getStatusFlow()
    expect(res.success).toBe(true)
    expect(res.data).toEqual([])
})

test('getStatusFlow: no history + Applied collapses to Applied -> No Response', async () => {
    await prisma.applications.create({ data: makeApplication({ status: 'Applied' }) })
    const res = await getStatusFlow()
    expect(res.data).toEqual([{ from: 'Applied', to: 'No Response', value: 1 }])
})

test('getStatusFlow: no history + non-Applied status flows Applied -> status', async () => {
    await prisma.applications.create({ data: makeApplication({ status: 'Interview' }) })
    const res = await getStatusFlow()
    expect(res.data).toEqual([{ from: 'Applied', to: 'Interview', value: 1 }])
})

test('getStatusFlow: a history chain becomes consecutive transitions (dedup)', async () => {
    // history starts with a redundant 'Applied' — must be de-duped against the seed.
    await appWithHistory('Offer', ['Applied', 'Interview', 'Offer'])
    const res = await getStatusFlow()
    expect(res.data).toEqual([
        { from: 'Applied', to: 'Interview', value: 1 },
        { from: 'Interview', to: 'Offer', value: 1 },
    ])
})

test('getStatusFlow: a chain that collapses to just Applied -> No Response', async () => {
    await appWithHistory('Applied', ['Applied'])
    const res = await getStatusFlow()
    expect(res.data).toEqual([{ from: 'Applied', to: 'No Response', value: 1 }])
})

test('getStatusFlow: identical transitions across apps are counted', async () => {
    await prisma.applications.create({ data: makeApplication({ status: 'Applied' }) })
    await prisma.applications.create({ data: makeApplication({ status: 'Applied' }) })
    const res = await getStatusFlow()
    expect(res.data).toEqual([{ from: 'Applied', to: 'No Response', value: 2 }])
})

// --- getTimelineData ------------------------------------------------------

test('getTimelineData counts per day (T-split) sorted ascending', async () => {
    await prisma.applications.create({ data: makeApplication({ date_applied: '2026-01-02' }) })
    await prisma.applications.create({ data: makeApplication({ date_applied: '2026-01-01' }) })
    // A timestamped value must bucket to the same day as the bare date.
    await prisma.applications.create({ data: makeApplication({ date_applied: '2026-01-01T09:00:00.000Z' }) })
    const res = await getTimelineData()
    expect(res.success).toBe(true)
    expect(res.data).toEqual([
        { date: '2026-01-01', count: 2 },
        { date: '2026-01-02', count: 1 },
    ])
})

// --- getCategoryData ------------------------------------------------------

test('getCategoryData counts per category (null -> Others) sorted desc', async () => {
    for (const category of ['SWE', 'SWE', 'SWE', 'MLE', 'MLE']) {
        await prisma.applications.create({ data: makeApplication({ category }) })
    }
    await prisma.applications.create({ data: makeApplication({ category: null }) })
    const res = await getCategoryData()
    expect(res.success).toBe(true)
    expect(res.data).toEqual([
        { name: 'SWE', value: 3 },
        { name: 'MLE', value: 2 },
        { name: 'Others', value: 1 },
    ])
})
