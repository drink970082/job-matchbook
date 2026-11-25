import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApplicationsView } from '@/components/ApplicationsView'
import { JobsView } from '@/components/JobsView'
import { ActivityTab } from '@/components/ActivityTab'
import { Onboarding } from '@/components/Onboarding'
import * as applicationActions from '@/lib/application-actions'
import * as analyticsActions from '@/lib/analytics-actions'
import * as jobActions from '@/lib/job-actions'
import * as linkActions from '@/lib/link-actions'
import * as watchlistActions from '@/lib/watchlist-actions'
import * as activityActions from '@/lib/activity-actions'

// Smoke tests of the per-route views (#211): each page renders its own view.
// Stub the server actions (no real Prisma) and the recharts-based charts (jsdom
// has no layout, so ResponsiveContainer renders nothing).
jest.mock('@/lib/application-actions')
jest.mock('@/lib/analytics-actions')
jest.mock('@/lib/csv-actions')
jest.mock('@/lib/watchlist-actions')
jest.mock('@/lib/job-actions')
jest.mock('@/lib/link-actions')
jest.mock('@/lib/profile-actions')
jest.mock('@/lib/category-actions')
jest.mock('@/lib/activity-actions')
jest.mock('@/components/QuotaBar', () => ({ QuotaBar: () => <div data-testid="quota" /> }))
jest.mock('@/components/SankeyChart', () => ({ SankeyChart: () => <div data-testid="sankey" /> }))
jest.mock('@/components/TimelineHeatmap', () => ({ TimelineHeatmap: () => <div data-testid="heatmap" /> }))
jest.mock('@/components/CategoryDonut', () => ({ CategoryDonut: () => <div data-testid="donut" /> }))

// The mounted tables fire a debounced fetch on mount; give those actions a real
// resolved shape so Dashboard's `await getJobPostings()`/`getApplications()`
// destructure doesn't throw an unhandled rejection after the test.
beforeEach(() => {
    ;(jobActions.getJobPostings as jest.Mock).mockResolvedValue({ data: [], total: 0 })
    ;(applicationActions.getApplications as jest.Mock).mockResolvedValue({ data: [], total: 0 })
    ;(watchlistActions.getWatchedCompanies as jest.Mock).mockResolvedValue({ data: [
        { id: 1, source: 'greenhouse', slug: 'acme', name: 'Acme', postings_30d: 12 },
    ], total: 1 })
})

const appProps = {
    initialApps: [],
    initialKpis: { total: 3, active: 2, screening: 0, interviewing: 1, rejected: 0, offer: 0 },
    totalApps: 0,
    initialStatusFlow: [],
    initialTimeline: [],
    initialCategories: [],
    categoryOptions: ['SWE', 'Others'],
}
const jobProps = { initialJobPostings: [], totalJobPostings: 0, categoryOptions: ['SWE', 'Others'], mode: 'jev' as const }

function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (reason?: unknown) => void
    const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
    return { promise, resolve, reject }
}

test('the Applications view shows the KPI grid and the CSV actions', () => {
    render(<ApplicationsView {...appProps} />)
    expect(screen.getByText('Total')).toBeInTheDocument() // KPI tile label
    expect(screen.getByRole('button', { name: /Export CSV/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Import CSV/i })).toBeInTheDocument()
})

test('the Jobs view states its mode and the 7-day window, and has no stage tabs', () => {
    const { unmount } = render(<JobsView {...jobProps} />)
    expect(screen.getByText(/Triage assesses postings from the last 7 days only/)).toBeInTheDocument()
    expect(screen.queryByRole('tab')).not.toBeInTheDocument()
    unmount()
    render(<JobsView {...jobProps} mode="screen" />)
    expect(screen.getByText(/showing postings that passed your hard requirements/)).toBeInTheDocument()
})

test('Not interested writes a skip override and offers Undo', async () => {
    const row = { id: 7, source: 's', company_name: 'Acme', job_title: 'Eng', job_url: 'https://x.test/7', pipeline_status: 'new' }
    ;(jobActions.setTriageOverride as jest.Mock).mockResolvedValue({ success: true })
    render(<JobsView {...jobProps} initialJobPostings={[row]} totalJobPostings={1} />)
    fireEvent.click(screen.getByRole('button', { name: 'Not interested: Eng' }))
    fireEvent.click(screen.getByRole('button', { name: 'Not interested: Eng' }))    // double click: one write
    await waitFor(() => expect(jobActions.getJobPostings).toHaveBeenCalled())
    expect(jobActions.setTriageOverride).toHaveBeenCalledTimes(1)
    expect(jobActions.setTriageOverride).toHaveBeenCalledWith(7, 'skip', 'Not interested (web)')
})

const MATCH = { id: 9, tier: 2 as const, company_name: 'ACME', job_title: 'eng', date_applied: '2026-11-02' }
const applyRow = { id: 7, source: 's', company_name: 'Acme', job_title: 'Eng', job_url: 'https://x.test/7', pipeline_status: 'new' }

test('a posting that matches an application says so and offers to link it', async () => {
    ;(linkActions.linkApplication as jest.Mock).mockResolvedValue({ success: true })
    render(<JobsView {...jobProps} initialJobPostings={[{ ...applyRow, applied_match: MATCH }]} totalJobPostings={1} />)
    expect(screen.getByText('You may have applied already (application #9)')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Mark applied: Eng' }))
    fireEvent.click(screen.getByRole('button', { name: 'Link to application #9' }))
    await waitFor(() => expect(linkActions.linkApplication).toHaveBeenCalledWith(9, 7))
    expect(jobActions.markJobApplied).not.toHaveBeenCalled()
})

test('a match found at write time turns the dialog into the same choice; New keeps the chosen date', async () => {
    ;(jobActions.markJobApplied as jest.Mock).mockResolvedValueOnce({ success: false, error: 'x', match: MATCH }).mockResolvedValueOnce({ success: true })
    render(<JobsView {...jobProps} initialJobPostings={[applyRow]} totalJobPostings={1} />)
    fireEvent.click(screen.getByRole('button', { name: 'Mark applied: Eng' }))
    fireEvent.change(screen.getByLabelText('Date applied'), { target: { value: '2026-11-03' } })
    fireEvent.click(screen.getByRole('button', { name: 'Mark Applied' }))
    await screen.findByRole('button', { name: 'Link to application #9' })
    fireEvent.click(screen.getByRole('button', { name: 'It is a new application' }))
    await waitFor(() => expect(jobActions.markJobApplied).toHaveBeenCalledTimes(2))
    const calls = (jobActions.markJobApplied as jest.Mock).mock.calls
    expect(calls.map((c) => [c[0], c[1], c[4]])).toEqual([
        [7, 'SWE', { date: '2026-11-03', createNew: false }], [7, 'SWE', { date: '2026-11-03', createNew: true }]])
})

test('cancelling Mark Applied while it is in flight: a late match does not reopen the dialog', async () => {
    const late = deferred<any>()
    ;(jobActions.markJobApplied as jest.Mock).mockReturnValueOnce(late.promise)
    render(<JobsView {...jobProps} initialJobPostings={[applyRow]} totalJobPostings={1} />)
    fireEvent.click(screen.getByRole('button', { name: 'Mark applied: Eng' }))
    fireEvent.click(screen.getByRole('button', { name: 'Mark Applied' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await act(async () => { late.resolve({ success: false, error: 'x', match: MATCH }) })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('adding an application opens its candidates when it has any, and only then', async () => {
    const add = async () => {
        fireEvent.change(screen.getByPlaceholderText('Company Name'), { target: { value: 'Acme' } })
        fireEvent.change(screen.getByPlaceholderText('Job Title'), { target: { value: 'Eng' } })
        fireEvent.click(screen.getByRole('button', { name: /Add Application/ }))
        await waitFor(() => expect(linkActions.getLinkSuggestions).toHaveBeenCalledWith({ applicationId: 5 }))
    }
    ;(analyticsActions.getKPIs as jest.Mock).mockResolvedValue(appProps.initialKpis)
    for (const read of [analyticsActions.getStatusFlow, analyticsActions.getTimelineData, analyticsActions.getCategoryData]) {
        ;(read as jest.Mock).mockResolvedValue({ success: true, data: [] })
    }
    ;(applicationActions.addApplication as jest.Mock).mockResolvedValue({ success: true, data: { id: 5 } })
    const application = { id: 5, company_name: 'Acme', job_title: 'Eng', application_url: '', date_applied: '2026-11-02', status: 'Applied' }
    ;(linkActions.getLinkSuggestions as jest.Mock).mockResolvedValue({ success: true, data: [{ application, suggestions: [], more: 0 }] })
    const { unmount } = render(<ApplicationsView {...appProps} />)
    await add()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    unmount()

    ;(linkActions.getLinkSuggestions as jest.Mock).mockReset().mockResolvedValue({ success: true, data: [{ application, more: 0, suggestions: [
        { tier: 2, job_id: 7, company_name: 'Acme', job_title: 'Eng', job_url: 'https://x.test/7', location: null, posted_at: null, source_state: 'available' }] }] })
    render(<ApplicationsView {...appProps} />)
    await add()
    expect(await screen.findByRole('button', { name: /^Link Acme - Eng to Eng/ })).toBeInTheDocument()
})

test('overlapping inventory requests never show stale rows under newer filters', async () => {
    const first = deferred<{ data: any[]; total: number }>()
    const second = deferred<{ data: any[]; total: number }>()
    ;(jobActions.getJobPostings as jest.Mock).mockImplementation((query: any) =>
        query.search === 'A' ? first.promise : second.promise,
    )
    const initialRow = {
        id: 1, source: 'synthetic', company_name: 'Old', job_title: 'Old page row', job_url: 'https://example.test/old',
        description: 'Old synthetic description', pipeline_status: 'new', created_at: '2026-10-22T10:00:00Z',
        screen_summary: { outcome: 'not_screened', is_advisory: true, reason: null, assessment_time: null,
            backend: null, model: null, effort: null, evaluator_version: null, origin: 'none' },
        legacy_screen_evidence: { available: false, origin: null },
    }
    render(<JobsView {...jobProps} initialJobPostings={[initialRow]} totalJobPostings={1} />)
    expect(screen.getByText('Old page row')).toBeInTheDocument()

    const search = screen.getByPlaceholderText(/companies, roles, or locations/i)
    fireEvent.change(search, { target: { value: 'A' } })
    expect(screen.getByText('Loading jobs...')).toBeInTheDocument()
    expect(screen.queryByText('Old page row')).not.toBeInTheDocument()
    fireEvent.change(search, { target: { value: 'B' } })

    await act(async () => {
        first.resolve({ data: [{ ...initialRow, id: 2, company_name: 'A', job_title: 'A result' }], total: 1 })
    })
    expect(screen.getByText('Loading jobs...')).toBeInTheDocument()
    expect(screen.queryByText('A result')).not.toBeInTheDocument()

    await act(async () => {
        second.resolve({ data: [{ ...initialRow, id: 3, company_name: 'B', job_title: 'B result' }], total: 1 })
    })
    await waitFor(() => expect(screen.getByText('B result')).toBeInTheDocument())
    expect(screen.queryByText('A result')).not.toBeInTheDocument()
    expect(screen.queryByText('Old page row')).not.toBeInTheDocument()
})

test('the Activity view: status strip, one timeline marking only MCP, Load more', async () => {
    // The shape a dying pass leaves: it is marked abandoned as the next one starts running.
    const lastPass = { startedAt: new Date().toISOString(), finishedAt: null, status: 'running', errorCategory: null,
        fetchOnly: true, jevEnabled: false, config: {}, counts: { fetch: { boards_attempted: 5, boards_failed: 1, inserted: 2 } } }
    const lastFailure = { startedAt: new Date(Date.now() - 86_400_000).toISOString(), errorCategory: 'abandoned', since: 1 }
    const funnelWindow = { passes: 1, passes_without_intake: 0, since: '2026-11-24T05:00:00.000Z', open: 3, stages: [
        { stage: 'filters', input: 1070, removed: 1037, reasons: { title: 1019, age: 8, feed_gate: 10 } as Record<string, number>, output: 33 },
        { stage: 'requirements', input: 33, removed: 30, reasons: { authorization: 30, degree: 1 } as Record<string, number>, output: 3 },
    ] }
    const status = { lastPass, lastFailure, new24h: 3, new7d: 40, assessed24h: 12, failures24h: 1, spend7dUsd: 0.0042,
        agedOut7d: 2, agedOutTotal: 9, funnel: { latest_pass: funnelWindow, last_7_days: { ...funnelWindow, passes: 4, passes_without_intake: 1 } } }
    const initial = { items: [
        { key: 'c9', at: '2026-11-19T00:00:00Z', actor: 'web', text: 'Updated the JEV profile' },
        { key: 'a5', at: '2026-11-18', actor: 'mcp', text: 'Applied to Acme - Engineer' },
    ], hasMore: true, nextOffset: 2, capped: false }
    const loadMore = jest.fn().mockResolvedValue({ items: [{ key: 'h1', at: '2026-11-01', actor: 'web', text: 'Acme - Engineer -> Interviewing' }],
        hasMore: false, nextOffset: 3, capped: false })
    render(<ActivityTab status={status} initial={initial} loadMore={loadMore} />)
    expect(screen.getByText('USD 0.0042')).toBeInTheDocument()
    expect(screen.getByText('2 in 7d, 9 total')).toBeInTheDocument()
    expect(screen.getByText(/^A pass failed since the last finished one, 24h 0m ago: abandoned/)).toBeInTheDocument()
    expect(screen.getByText(/^running for/)).toBeInTheDocument()
    expect(screen.getByText('Fetch: 5 boards, 1 failed; 2 new postings')).toBeInTheDocument()
    expect(screen.getByText('Screen: not run (fetch only)')).toBeInTheDocument()
    expect(screen.getByText(/fetch only; every 24h/)).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Latest pass' })).toHaveTextContent('Listings seen1,070')
    expect(screen.getByRole('table', { name: 'Latest pass' })).toHaveTextContent('Removed by a requirementauthorization 30, degree 1-30')
    expect(screen.getByRole('table', { name: 'Last 7 days, passes: 4' })).toHaveTextContent('Open and eligible3')
    expect(screen.getByText(/stopped before recording their intake: 1/)).toBeInTheDocument()
    expect(screen.getAllByText('via MCP')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
    await waitFor(() => expect(screen.getByText('Acme - Engineer -> Interviewing')).toBeInTheDocument())
    expect(loadMore).toHaveBeenCalledWith(2)
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
})

const TEMPLATES = Object.fromEntries(['claude-code.txt', 'claude-desktop.json', 'codex.txt', 'chatgpt.txt',
    'prompt-set-me-up.txt', 'prompt-log-application.txt', 'prompt-update-from-email.txt'].map((f) => [f, `template ${f}`])) as any

test('onboarding ticks done steps and hides their help; open steps link to their page', () => {
    render(<Onboarding templates={TEMPLATES}
        steps={{ aiClient: false, requirements: true, sources: false, triage: false, firstFetch: false }} />)
    expect(screen.getByText('template claude-code.txt')).toBeInTheDocument()
    expect(screen.getByText('template prompt-set-me-up.txt')).toBeInTheDocument()
    expect(screen.getAllByLabelText('done')).toHaveLength(1)
    expect(screen.queryByText(/discarded for free/)).toBeNull()
    expect(screen.getByRole('link', { name: 'Sources' })).toHaveAttribute('href', '/sources')
})
