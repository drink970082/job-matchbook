import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Dashboard } from '@/components/Dashboard'
import * as actions from '@/lib/actions'
import * as promotionActions from '@/lib/promotion-actions'
import * as unresolvedActions from '@/lib/unresolved-actions'

// Smoke test of Dashboard's own wiring (tabs, KPI grid, the table views).
// Stub the server actions (no real Prisma) and the recharts-based charts (jsdom
// has no layout, so ResponsiveContainer renders nothing).
jest.mock('@/lib/actions')
jest.mock('@/lib/promotion-actions')
jest.mock('@/lib/unresolved-actions')
jest.mock('@/components/SankeyChart', () => ({ SankeyChart: () => <div data-testid="sankey" /> }))
jest.mock('@/components/StatusFunnel', () => ({ StatusFunnel: () => <div data-testid="funnel" /> }))
jest.mock('@/components/TimelineHeatmap', () => ({ TimelineHeatmap: () => <div data-testid="heatmap" /> }))
jest.mock('@/components/CategoryDonut', () => ({ CategoryDonut: () => <div data-testid="donut" /> }))

// The mounted tables fire a debounced fetch on mount; give those actions a real
// resolved shape so Dashboard's `await getJobPostings()`/`getApplications()`
// destructure doesn't throw an unhandled rejection after the test.
beforeEach(() => {
    ;(actions.getJobPostings as jest.Mock).mockResolvedValue({ data: [], total: 0 })
    ;(actions.getApplications as jest.Mock).mockResolvedValue({ data: [], total: 0 })
    ;(actions.getWatchedCompanies as jest.Mock).mockResolvedValue({ data: [], total: 0 })
    ;(promotionActions.getPromotionSuggestions as jest.Mock).mockResolvedValue({ data: [] })
    ;(unresolvedActions.getUnresolvedFeeds as jest.Mock).mockResolvedValue({ data: [], total: 0 })
})

const props = {
    initialApps: [],
    initialKpis: { applied: 3, active: 2, assessment: 0, interviewing: 1, rejected: 0, offer: 0 },
    totalApps: 0,
    initialStatusFlow: [],
    initialTimeline: [],
    initialCategories: [],
    initialJobPostings: [],
    totalJobPostings: 0,
    initialCategoryOptions: ['SWE', 'Others'],
    initialCategoriesConfigured: true,
}

function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (reason?: unknown) => void
    const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
    return { promise, resolve, reject }
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
    expect(screen.getByPlaceholderText(/companies, roles, or locations/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'All jobs' })).toHaveClass('bg-background')
})

test('selected legacy bucket and filters survive switching away from Discovered Jobs', async () => {
    const user = userEvent.setup()
    render(<Dashboard {...props} />)
    await user.click(screen.getByRole('button', { name: /Discovered Jobs/i }))
    await user.click(screen.getByRole('button', { name: 'Discarded' }))
    const search = screen.getByPlaceholderText(/search companies or job titles/i)
    fireEvent.change(search, { target: { value: 'kept selection' } })

    await user.click(screen.getByRole('button', { name: /^Applications$/i }))
    await user.click(screen.getByRole('button', { name: /Discovered Jobs/i }))

    expect(screen.getByRole('button', { name: 'Discarded' })).toHaveClass('bg-background')
    expect(screen.getByPlaceholderText(/search companies or job titles/i)).toHaveValue('kept selection')
})

test('overlapping inventory requests never show stale rows under newer filters', async () => {
    const first = deferred<{ data: any[]; total: number }>()
    const second = deferred<{ data: any[]; total: number }>()
    ;(actions.getJobPostings as jest.Mock).mockImplementation((query: any) =>
        query.search === 'A' ? first.promise : second.promise,
    )
    const initialRow = {
        id: 1, source: 'synthetic', company_name: 'Old', job_title: 'Old page row', job_url: 'https://example.test/old',
        description: 'Old synthetic description', pipeline_status: 'new', created_at: '2026-10-22T10:00:00Z',
        screen_summary: { outcome: 'not_screened', is_advisory: true, reason: null, assessment_time: null,
            backend: null, model: null, effort: null, evaluator_version: null, origin: 'none' },
        legacy_screen_evidence: { available: false, origin: null },
    }
    const user = userEvent.setup()
    render(<Dashboard {...props} initialJobPostings={[initialRow]} totalJobPostings={1} />)
    await user.click(screen.getByRole('button', { name: /Discovered Jobs/i }))
    expect(screen.getByText('Old page row')).toBeInTheDocument()

    const search = screen.getByPlaceholderText(/companies, roles, or locations/i)
    fireEvent.change(search, { target: { value: 'A' } })
    expect(screen.getByText('Loading jobs…')).toBeInTheDocument()
    expect(screen.queryByText('Old page row')).not.toBeInTheDocument()
    fireEvent.change(search, { target: { value: 'B' } })

    await act(async () => {
        first.resolve({ data: [{ ...initialRow, id: 2, company_name: 'A', job_title: 'A result' }], total: 1 })
    })
    expect(screen.getByText('Loading jobs…')).toBeInTheDocument()
    expect(screen.queryByText('A result')).not.toBeInTheDocument()

    await act(async () => {
        second.resolve({ data: [{ ...initialRow, id: 3, company_name: 'B', job_title: 'B result' }], total: 1 })
    })
    await waitFor(() => expect(screen.getByText('B result')).toBeInTheDocument())
    expect(screen.queryByText('A result')).not.toBeInTheDocument()
    expect(screen.queryByText('Old page row')).not.toBeInTheDocument()
})

test('switching to the Watchlist tab shows the watchlist add form', async () => {
    const user = userEvent.setup()
    render(<Dashboard {...props} />)
    await user.click(screen.getByRole('button', { name: /Watchlist/i }))
    // The watchlist add row's distinctive inputs.
    expect(screen.getByPlaceholderText(/board slug/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Add$/i })).toBeInTheDocument()
})
