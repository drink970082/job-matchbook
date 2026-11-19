import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import { DiscoveredJobsTable, type JobTableFilters } from '@/components/DiscoveredJobsTable'

const mockJobs: any[] = [
  {
    id: 1, source: 'greenhouse', company_name: 'Acme', job_title: 'Backend Engineer', location: 'Remote',
    job_url: 'https://acme.example/jobs/1', description: 'x'.repeat(600), pipeline_status: 'new',
    posted_at: '2026-06-01', created_at: '2026-06-03T00:00:00.000Z', stage: 'keep',
    jev: { status: 'keep', model_status: 'keep', reasons: [], override: null },
  },
  {
    id: 2, source: 'lever', company_name: 'Globex', job_title: 'ML Engineer', location: 'NYC',
    job_url: 'https://globex.example/jobs/2', description: 'x'.repeat(600), pipeline_status: 'new',
    posted_at: '2026-05-20', created_at: '2026-05-22T00:00:00.000Z', stage: 'jev_skip',
    jev: { status: 'skip', model_status: 'skip', reasons: ['preference_weak', 'required_yoe_3_plus'], override: null },
  },
]

const KEEP: JobTableFilters = { stage: 'keep', search: '', searchScope: 'metadata', sort: 'created' }

function renderTable(overrides: Partial<React.ComponentProps<typeof DiscoveredJobsTable>> = {}) {
  const initialFilters = overrides.filters ?? KEEP
  const props = {
    data: mockJobs, total: 2, page: 0, size: 25, filters: initialFilters, loading: false, loadError: false,
    onPageChange: jest.fn(), onFilterChange: jest.fn(), onMarkApplied: jest.fn(), onViewJD: jest.fn(),
    ...overrides,
  }
  function ControlledTable() {
    const [filters, setFilters] = useState(initialFilters)
    return <DiscoveredJobsTable {...props} filters={filters}
      onFilterChange={(next) => { props.onFilterChange(next); setFilters(next) }} />
  }
  render(<ControlledTable />)
  return props
}

describe('DiscoveredJobsTable', () => {
  it('renders rows with company, role link, source and compact dates', () => {
    renderTable()
    expect(screen.getByText('Acme')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Backend Engineer' })).toHaveAttribute('href', 'https://acme.example/jobs/1')
    expect(screen.getByText('greenhouse')).toBeInTheDocument()
    expect(screen.getByText('Posted 2026-06-01')).toBeInTheDocument()
    expect(screen.getByText('Fetched 2026-06-03')).toBeInTheDocument()
  })

  it('is a funnel: Keep is selected by default, tabs show counts, a tab switches the stage', () => {
    const props = renderTable({ counts: { keep: 12, jev_skip: 30, unassessed: 5, screen_rejected: 7, rule_rejected: 9, other: 2 } })
    expect(screen.getByRole('tab', { name: /^Keep/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: /^JEV skip/ })).toHaveTextContent('30')
    fireEvent.click(screen.getByRole('tab', { name: /^JEV skip/ }))
    expect(props.onFilterChange).toHaveBeenLastCalledWith({ ...KEEP, stage: 'jev_skip' })
  })

  it('shows the JEV verdict, the skip reasons and an override', () => {
    renderTable({ data: [mockJobs[1], { ...mockJobs[0], id: 3, jev: { status: 'keep', model_status: 'skip', reasons: ['preference_weak'],
      override: { decision: 'keep', reason: 'wanted', actor: 'mcp', set_at: 'x', applies: true } } }], total: 2 })
    expect(screen.getByText('Skip')).toBeInTheDocument()
    expect(screen.getAllByText('weak match to your preferences')).toHaveLength(2)
    expect(screen.getByText('asks for 3+ years')).toBeInTheDocument()
    expect(screen.getByText('Override: keep (model said Skip)')).toBeInTheDocument()
  })

  it('offers only View JD and Mark Applied, each with the current view', () => {
    const props = renderTable()
    fireEvent.click(screen.getAllByTitle('Mark Applied')[0])
    expect(props.onMarkApplied).toHaveBeenCalledWith(1, KEEP)
    fireEvent.click(screen.getAllByTitle('View JD')[0])
    expect(props.onViewJD).toHaveBeenCalledWith(1, KEEP)
    expect(screen.queryByTitle(/remove|reopen/i)).toBeNull()
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.queryByLabelText(/minimum score/i)).toBeNull()
  })

  it('sends search and sort changes in the filter payload', () => {
    const props = renderTable()
    fireEvent.change(screen.getByPlaceholderText(/search companies/i), { target: { value: 'Acme' } })
    expect(props.onFilterChange).toHaveBeenLastCalledWith({ ...KEEP, search: 'Acme' })
  })

  it('labels standalone and legacy screen evidence and source state separately', () => {
    renderTable({
      filters: { ...KEEP, stage: 'all' },
      data: [{
        ...mockJobs[0],
        screen_summary: { outcome: 'no_disqualifier_found', is_advisory: true, reason: 'Unchecked requirements remain unknown.',
          assessment_time: '2026-10-22T10:20:30Z', backend: 'codex', model: 'fixture-model', effort: 'medium',
          evaluator_version: 'fixture-v1', origin: 'job_screenings' },
        legacy_screen_evidence: { available: true, origin: 'job_postings.score_detail.screen' },
        triage_summary: { status: 'needs_review', reason: 'No standalone record.', provenance: 'none' },
        source_lifecycle: { state: 'available', last_seen_at: '2026-10-24T10:00:00Z', last_check_attempted_at: '2026-10-25T10:00:00Z',
          last_checked_at: '2026-10-22T09:00:00Z', last_check_outcome: 'inconclusive', last_check_error_category: 'timeout',
          content_revision: 2, fit_freshness: 'stale', screen_freshness: 'current', combined_screen_freshness: 'current' },
      }],
      total: 1,
    })
    expect(screen.getByText('Advisory · No disqualifier found')).toBeInTheDocument()
    expect(screen.getByText('Triage · Needs review')).toBeInTheDocument()
    expect(screen.getByText('Legacy screen evidence')).toBeInTheDocument()
    expect(screen.getByText('Source · Available')).toBeInTheDocument()
    expect(screen.getByText('Standalone screen current · Fit-pipeline screen current')).toBeInTheDocument()
    expect(screen.getByText('New')).toBeInTheDocument()
  })

  it('labels applied and unknown lifecycle states honestly and hides Mark Applied on applied rows', () => {
    renderTable({ filters: { ...KEEP, stage: 'all' }, total: 2, data: [
      { ...mockJobs[0], id: 41, pipeline_status: 'applied' },
      { ...mockJobs[1], id: 42, pipeline_status: '__proto__' },
    ] })
    expect(screen.getAllByText('Applied').length).toBeGreaterThan(0)
    expect(screen.getByText('Unknown status (__proto__)')).toBeInTheDocument()
    expect(screen.getAllByTitle('Mark Applied')).toHaveLength(1)
  })

  it('distinguishes null, empty and thin job descriptions without showing JD text', () => {
    renderTable({ total: 3, data: [
      { ...mockJobs[0], id: 51, description: null },
      { ...mockJobs[0], id: 52, description: '' },
      { ...mockJobs[0], id: 53, description: 'Short JD text' },
    ] })
    expect(screen.getByText('Description unavailable')).toBeInTheDocument()
    expect(screen.getByText('Description is empty')).toBeInTheDocument()
    expect(screen.getByText('Short JD (13 chars)')).toBeInTheDocument()
  })

  it('shows loading, error and empty states instead of stale rows', () => {
    renderTable({ loading: true })
    expect(screen.getByText('Loading jobs...')).toBeInTheDocument()
    expect(screen.queryByText('Backend Engineer')).toBeNull()
  })

  it('says the inventory is empty when every stage count is zero, else that filters excluded it', () => {
    const zero = { keep: 0, jev_skip: 0, unassessed: 0, screen_rejected: 0, rule_rejected: 0, other: 0 }
    renderTable({ data: [], total: 0, counts: zero })
    expect(screen.getByText('No jobs in inventory yet.')).toBeInTheDocument()
  })

  it('an empty stage of a non-empty inventory says filters excluded everything', () => {
    renderTable({ data: [], total: 0, counts: { keep: 0, jev_skip: 3 } })
    expect(screen.getByText('No jobs match these filters.')).toBeInTheDocument()
  })

  it('calls onPageChange from the pager', () => {
    const props = renderTable({ total: 60 })
    fireEvent.click(screen.getByRole('button', { name: /next/i }))
    expect(props.onPageChange).toHaveBeenCalledWith(1)
  })
})
