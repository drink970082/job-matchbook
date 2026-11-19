import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApplicationsView } from '@/components/ApplicationsView'
import { JobsView } from '@/components/JobsView'
import { SourcesTab } from '@/components/SourcesTab'
import { ActivityTab } from '@/components/ActivityTab'
import { Onboarding } from '@/components/Onboarding'
import * as applicationActions from '@/lib/application-actions'
import * as jobActions from '@/lib/job-actions'
import * as watchlistActions from '@/lib/watchlist-actions'
import * as activityActions from '@/lib/activity-actions'
import * as unresolvedActions from '@/lib/unresolved-actions'

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
jest.mock('@/lib/unresolved-actions')
jest.mock('@/components/SankeyChart', () => ({ SankeyChart: () => <div data-testid="sankey" /> }))
jest.mock('@/components/StatusFunnel', () => ({ StatusFunnel: () => <div data-testid="funnel" /> }))
jest.mock('@/components/TimelineHeatmap', () => ({ TimelineHeatmap: () => <div data-testid="heatmap" /> }))
jest.mock('@/components/CategoryDonut', () => ({ CategoryDonut: () => <div data-testid="donut" /> }))

// The mounted tables fire a debounced fetch on mount; give those actions a real
// resolved shape so Dashboard's `await getJobPostings()`/`getApplications()`
// destructure doesn't throw an unhandled rejection after the test.
beforeEach(() => {
    ;(jobActions.getJobPostings as jest.Mock).mockResolvedValue({ data: [], total: 0 })
    ;(jobActions.getJobStageCounts as jest.Mock).mockResolvedValue({ keep: 4, jev_skip: 9, unassessed: 0, screen_rejected: 0, rule_rejected: 0, other: 0 })
    ;(applicationActions.getApplications as jest.Mock).mockResolvedValue({ data: [], total: 0 })
    ;(watchlistActions.getWatchedCompanies as jest.Mock).mockResolvedValue({ data: [
        { id: 1, source: 'greenhouse', slug: 'acme', name: 'Acme', postings_30d: 12 },
    ], total: 1 })
    ;(activityActions.getRecentActivity as jest.Mock).mockResolvedValue({
        applications: [{ id: 5, company_name: 'Acme', job_title: 'Engineer', date_applied: '2026-11-18', actor: 'mcp' }],
        statusChanges: [],
        changes: [{ id: 9, at: '2026-11-19T00:00:00Z', actor: 'web', action: 'update', entity: 'jev_profile', entity_id: 1, label: 'JEV profile v2' }],
    })
    ;(unresolvedActions.getUnresolvedFeeds as jest.Mock).mockResolvedValue({ data: [], total: 0 })
})

const appProps = {
    initialApps: [],
    initialKpis: { applied: 3, active: 2, assessment: 0, interviewing: 1, rejected: 0, offer: 0 },
    totalApps: 0,
    initialStatusFlow: [],
    initialTimeline: [],
    initialCategories: [],
    categoryOptions: ['SWE', 'Others'],
}
const jobProps = { initialJobPostings: [], totalJobPostings: 0, categoryOptions: ['SWE', 'Others'] }

function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (reason?: unknown) => void
    const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
    return { promise, resolve, reject }
}

test('the Applications view shows the KPI grid and the CSV actions', () => {
    render(<ApplicationsView {...appProps} />)
    expect(screen.getByText('Applied')).toBeInTheDocument() // KPI tile label
    expect(screen.getByRole('button', { name: /Export CSV/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Import CSV/i })).toBeInTheDocument()
})

test('the Jobs view opens on the Keep stage and loads stage counts', async () => {
    render(<JobsView {...jobProps} />)
    expect(screen.getByPlaceholderText(/companies, roles, or locations/i)).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /^Keep/ })).toHaveAttribute('aria-selected', 'true')
    await waitFor(() => expect(screen.getByRole('tab', { name: /^JEV skip/ })).toHaveTextContent('9'))
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

test('the Sources view lists watched boards with 30-day postings and offers no add or remove', () => {
    render(<SourcesTab sources={[{ id: 1, source: 'greenhouse', slug: 'acme', name: 'Acme', postings_30d: 12 }]} unresolved={[]} />)
    expect(screen.getByText('Acme')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/board slug/i)).toBeNull()
    expect(screen.queryByRole('button', { name: /^(Add|Remove|Re-add)$/i })).toBeNull()
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
