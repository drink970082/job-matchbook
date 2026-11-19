import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApplicationsView } from '@/components/ApplicationsView'
import { JobsView } from '@/components/JobsView'
import { ActivityTab } from '@/components/ActivityTab'
import { Onboarding } from '@/components/Onboarding'
import * as applicationActions from '@/lib/application-actions'
import * as jobActions from '@/lib/job-actions'
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
jest.mock('@/lib/preference-actions')
jest.mock('@/lib/category-actions')
jest.mock('@/lib/activity-actions')
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
    ;(activityActions.getRecentActivity as jest.Mock).mockResolvedValue({
        applications: [{ id: 5, company_name: 'Acme', job_title: 'Engineer', date_applied: '2026-11-18', actor: 'mcp' }],
        statusChanges: [],
        changes: [{ id: 9, at: '2026-11-19T00:00:00Z', actor: 'web', action: 'update', entity: 'jev_profile', entity_id: 1, label: 'JEV profile v2' }],
    })
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
    expect(screen.getByText(/JEV assesses postings from the last 7 days only/)).toBeInTheDocument()
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

test('the Activity view marks MCP writes', async () => {
    render(<ActivityTab activity={await activityActions.getRecentActivity()} />)
    expect(screen.getByText('Acme - Engineer')).toBeInTheDocument()
    expect(screen.getByText('via MCP')).toBeInTheDocument()
    expect(screen.getByText('update JEV profile v2')).toBeInTheDocument()
})

const TEMPLATES = Object.fromEntries(['claude-code.txt', 'claude-desktop.json', 'codex.txt', 'chatgpt.txt',
    'prompt-set-me-up.txt', 'prompt-log-application.txt', 'prompt-update-from-email.txt'].map((f) => [f, `template ${f}`])) as any

test('onboarding ticks done steps and hides their help; open steps link to their page', () => {
    render(<Onboarding templates={TEMPLATES}
        steps={{ aiClient: false, requirements: true, sources: false, jev: false, firstFetch: false }} />)
    expect(screen.getByText('template claude-code.txt')).toBeInTheDocument()
    expect(screen.getByText('template prompt-set-me-up.txt')).toBeInTheDocument()
    expect(screen.getAllByLabelText('done')).toHaveLength(1)
    expect(screen.queryByText(/discarded for free/)).toBeNull()
    expect(screen.getByRole('link', { name: 'Sources' })).toHaveAttribute('href', '/sources')
})
