import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Dashboard } from '@/components/Dashboard'

// Smoke test of Dashboard's own wiring (tabs, KPI grid, the two table views).
// Stub the server actions (no real Prisma) and the recharts-based charts (jsdom
// has no layout, so ResponsiveContainer renders nothing).
jest.mock('@/lib/actions')
jest.mock('@/components/SankeyChart', () => ({ SankeyChart: () => <div data-testid="sankey" /> }))
jest.mock('@/components/StatusFunnel', () => ({ StatusFunnel: () => <div data-testid="funnel" /> }))
jest.mock('@/components/TimelineHeatmap', () => ({ TimelineHeatmap: () => <div data-testid="heatmap" /> }))
jest.mock('@/components/CategoryDonut', () => ({ CategoryDonut: () => <div data-testid="donut" /> }))

const props = {
    initialApps: [],
    initialKpis: { applied: 3, active: 2, assessment: 0, interviewing: 1, rejected: 0, offer: 0 },
    totalApps: 0,
    initialStatusFlow: [],
    initialTimeline: [],
    initialCategories: [],
    initialJobPostings: [],
    totalJobPostings: 0,
}

test('renders both tabs and the KPI grid from initial props', () => {
    render(<Dashboard {...props} />)
    expect(screen.getByRole('button', { name: /Discovered Jobs/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Applications$/i })).toBeInTheDocument()
    expect(screen.getByText('Applied')).toBeInTheDocument() // KPI tile label
})

test('switching to the Discovered Jobs tab shows the discovered view', async () => {
    const user = userEvent.setup()
    render(<Dashboard {...props} />)
    await user.click(screen.getByRole('button', { name: /Discovered Jobs/i }))
    // Now "Discovered Jobs" appears twice — the tab button AND the panel heading.
    expect(screen.getAllByText('Discovered Jobs').length).toBeGreaterThanOrEqual(2)
    // The discovered table's search box (distinct "...or job titles" placeholder).
    expect(screen.getByPlaceholderText(/job titles/i)).toBeInTheDocument()
})
