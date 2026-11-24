import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import { DiscoveredJobsTable, localDateDaysAgo, postedAgo, type JobTableFilters } from '@/components/DiscoveredJobsTable'

const mockJobs: any[] = [
  {
    id: 1, source: 'greenhouse', company_name: 'Acme', job_title: 'Backend Engineer', location: 'Remote',
    job_url: 'https://acme.example/jobs/1', description: 'x'.repeat(600), pipeline_status: 'new',
    posted_at: '2026-06-01', created_at: '2026-06-03T00:00:00.000Z', stage: 'keep',
    status: 'keep', verdict: 'keep', profile_version: 2,
    jev: { reasons: [], override: null },
  },
  {
    id: 2, source: 'lever', company_name: 'Globex', job_title: 'ML Engineer', location: 'NYC',
    job_url: 'javascript:alert(1)', pipeline_status: 'new', posted_at: null,
  },
]

const BASE: JobTableFilters = { search: '', searchScope: 'metadata' }

function renderTable(overrides: Partial<React.ComponentProps<typeof DiscoveredJobsTable>> = {}) {
  const initialFilters = overrides.filters ?? BASE
  const props = {
    data: mockJobs, total: 2, page: 0, size: 25, filters: initialFilters, loading: false, loadError: false,
    onPageChange: jest.fn(), onFilterChange: jest.fn(), onMarkApplied: jest.fn(), onViewJD: jest.fn(),
    onNotInterested: jest.fn(), ...overrides,
  }
  function ControlledTable() {
    const [filters, setFilters] = useState(initialFilters)
    return <DiscoveredJobsTable {...props} filters={filters}
      onFilterChange={(next) => { props.onFilterChange(next); setFilters(next) }} />
  }
  render(<ControlledTable />)
  return props
}

// Local calendar days (a runtime TZ change is not honored under jest, so the clock is
// built in local time; the late-evening hour is where UTC days would disagree west of UTC).
test('postedAgo renders a relative age in local days, matching the filter cutoff', () => {
  const now = new Date(2026, 5, 4, 23, 30).getTime()
  expect(postedAgo('2026-06-01', now)).toBe('3d ago')
  expect(postedAgo('2026-06-04', now)).toBe('today')
  expect(localDateDaysAgo(1, now)).toBe('2026-06-03')
  expect(postedAgo(localDateDaysAgo(7, now), now)).toBe('7d ago')
  expect(postedAgo(null, now)).toBe('')
})

test('a row is a job-board row: title link, company, location, Apply via safeHref', () => {
  renderTable()
  expect(screen.getByRole('link', { name: 'Backend Engineer' })).toHaveAttribute('href', 'https://acme.example/jobs/1')
  expect(screen.getByText('Acme')).toBeInTheDocument()
  expect(screen.getByText('NYC')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Apply: Backend Engineer' })).toHaveAttribute('target', '_blank')
  expect(screen.queryByRole('link', { name: 'Apply: ML Engineer' })).not.toBeInTheDocument()   // unsafe scheme: no link
  expect(screen.queryByRole('link', { name: 'ML Engineer' })).not.toBeInTheDocument()
  expect(screen.queryByText('greenhouse')).not.toBeInTheDocument()
  expect(screen.queryByRole('tab')).not.toBeInTheDocument()
})

test('row actions call back with the posting id', () => {
  const props = renderTable()
  fireEvent.click(screen.getByRole('button', { name: 'Not interested: Backend Engineer' }))
  expect(props.onNotInterested).toHaveBeenCalledWith(1)
  fireEvent.click(screen.getByRole('button', { name: 'Mark applied: ML Engineer' }))
  expect(props.onMarkApplied).toHaveBeenCalledWith(2, BASE)
  fireEvent.click(screen.getByRole('button', { name: 'View JD: Backend Engineer' }))
  expect(props.onViewJD).toHaveBeenCalledWith(1, BASE)
})

test('filters: search, Search in JD, posted within', () => {
  const props = renderTable()
  fireEvent.change(screen.getByPlaceholderText(/Search companies/), { target: { value: 'acme' } })
  expect(props.onFilterChange).toHaveBeenLastCalledWith({ ...BASE, search: 'acme' })
  fireEvent.click(screen.getByLabelText('Search in JD'))
  expect(props.onFilterChange).toHaveBeenLastCalledWith({ ...BASE, search: 'acme', searchScope: 'all_text' })
  fireEvent.change(screen.getByLabelText('Posted within'), { target: { value: '7' } })
  expect(props.onFilterChange).toHaveBeenLastCalledWith({ search: 'acme', searchScope: 'all_text', postedSince: localDateDaysAgo(7) })
  expect(screen.getByLabelText('Posted within')).toHaveValue('7')
})

test('empty states distinguish filtered from no postings', () => {
  renderTable({ data: [], total: 0 })
  expect(screen.getByText('No postings for you yet.')).toBeInTheDocument()
})

test('each row shows the profile version its verdict was judged under', () => {
  renderTable()
  expect(screen.getByText('Judged under profile v2')).toBeInTheDocument()
  expect(screen.getAllByText(/Judged under profile/)).toHaveLength(1)
})
