import { render, screen, fireEvent, act } from '@testing-library/react'
import { DiscoveredJobsTable } from '@/components/DiscoveredJobsTable'

const mockJobs = [
  {
    id: 1,
    source: 'greenhouse',
    company_name: 'Acme',
    job_title: 'Backend Engineer',
    location: 'Remote',
    job_url: 'https://acme.example/jobs/1',
    description: 'Build things',
    score: 91,
    score_detail: '{"matched":["python","aws"],"missing":["kubernetes"],"reasoning":"Strong match"}',
    pipeline_status: 'scored',
    posted_at: '2026-06-01',
    created_at: '2026-06-03T00:00:00.000Z',
  },
  {
    id: 2,
    source: 'lever',
    company_name: 'Globex',
    job_title: 'ML Engineer',
    location: 'NYC',
    job_url: 'https://globex.example/jobs/2',
    description: 'Train models',
    score: 78,
    score_detail: null,
    pipeline_status: 'notified',
    posted_at: '2026-05-20',
    created_at: '2026-05-22T00:00:00.000Z',
  },
]

function renderTable(overrides: Partial<React.ComponentProps<typeof DiscoveredJobsTable>> = {}) {
  const props = {
    data: mockJobs,
    total: 2,
    page: 0,
    size: 25,
    onPageChange: jest.fn(),
    onFilterChange: jest.fn(),
    onMarkApplied: jest.fn(),
    onDiscard: jest.fn(),
    onReopen: jest.fn(),
    onViewJD: jest.fn(),
    onBulkRemove: jest.fn(),
    onBulkReopen: jest.fn(),
    onRemoveAllInView: jest.fn(),
    ...overrides,
  }
  render(<DiscoveredJobsTable {...props} />)
  return props
}

function renderWithRerender() {
  const props = {
    data: mockJobs, total: 2, page: 0, size: 25,
    onPageChange: jest.fn(), onFilterChange: jest.fn(), onMarkApplied: jest.fn(),
    onDiscard: jest.fn(), onReopen: jest.fn(), onViewJD: jest.fn(),
    onBulkRemove: jest.fn(), onBulkReopen: jest.fn(), onRemoveAllInView: jest.fn(),
  }
  const utils = render(<DiscoveredJobsTable {...props} />)
  return { rerender: (data: any[]) => utils.rerender(<DiscoveredJobsTable {...props} data={data} />) }
}

describe('DiscoveredJobsTable', () => {
  it('renders rows with company, job title and source', () => {
    renderTable()
    expect(screen.getByText('Acme')).toBeInTheDocument()
    expect(screen.getByText('Globex')).toBeInTheDocument()
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument()
    expect(screen.getByText('ML Engineer')).toBeInTheDocument()
  })

  it('shows the Below bar tab', () => {
    renderTable()
    expect(screen.getByRole('button', { name: 'Below bar' })).toBeInTheDocument()
  })

  it('renders posted and fetched dates compactly', () => {
    renderTable()
    expect(screen.getByText('Posted Jun 1')).toBeInTheDocument()
    expect(screen.getByText('Fetched Jun 3')).toBeInTheDocument()
  })

  it('shows the score for each row', () => {
    renderTable()
    expect(screen.getByText('91')).toBeInTheDocument()
    expect(screen.getByText('78')).toBeInTheDocument()
  })

  it('calls onMarkApplied when the Mark Applied action is clicked', () => {
    const onMarkApplied = jest.fn()
    renderTable({ onMarkApplied })
    fireEvent.click(screen.getAllByTitle(/mark applied/i)[0])
    expect(onMarkApplied).toHaveBeenCalledWith(1)
  })

  it('renders empty state when there is no data', () => {
    renderTable({ data: [], total: 0 })
    expect(screen.getByText(/no results/i)).toBeInTheDocument()
  })

  it('shows a Reopen control for discarded rows and calls onReopen', () => {
    const onReopen = jest.fn()
    renderTable({ data: [{ ...mockJobs[0], pipeline_status: 'discarded' }], total: 1, onReopen })
    // The Discard action button is replaced by Reopen for a discarded row.
    // (Match the button exactly so the "discarded manually" reason label doesn't count.)
    expect(screen.queryByRole('button', { name: /^discard$/i })).not.toBeInTheDocument()
    fireEvent.click(screen.getByTitle(/reopen/i))
    expect(onReopen).toHaveBeenCalledWith(1)
  })

  it('calls onViewJD with the row id when View JD is clicked', () => {
    const onViewJD = jest.fn()
    renderTable({ onViewJD })
    fireEvent.click(screen.getAllByTitle(/view jd/i)[0])
    expect(onViewJD).toHaveBeenCalledWith(1)
  })

  it('calls onDiscard with the row id for a non-discarded row', () => {
    const onDiscard = jest.fn()
    renderTable({ onDiscard })
    // mockJobs[0] (id 1) is 'scored' (not discarded) -> shows a per-row Remove action.
    fireEvent.click(screen.getAllByTitle(/remove/i)[0])
    expect(onDiscard).toHaveBeenCalledWith(1)
  })

  it('renders a — fallback for a row whose score is null', () => {
    renderTable({ data: [{ ...mockJobs[0], score: null }], total: 1 })
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('debounces onFilterChange with the current bucket + search', () => {
    jest.useFakeTimers()
    try {
      const onFilterChange = jest.fn()
      renderTable({ onFilterChange })

      const searchInput = screen.getByPlaceholderText(/search/i)
      fireEvent.change(searchInput, { target: { value: 'Acme' } })

      // The initial-mount effect fires once with the default state; assert only the
      // post-search payload.
      onFilterChange.mockClear()
      act(() => {
        jest.advanceTimersByTime(300)
      })

      expect(onFilterChange).toHaveBeenCalledWith({ search: 'Acme', bucket: 'matched', sort: 'score' })
    } finally {
      jest.runOnlyPendingTimers()
      jest.useRealTimers()
    }
  })

  it('switching to the Discarded bucket fires onFilterChange with that bucket', () => {
    jest.useFakeTimers()
    try {
      const onFilterChange = jest.fn()
      renderTable({ onFilterChange })

      onFilterChange.mockClear()
      fireEvent.click(screen.getByRole('button', { name: 'Discarded' }))
      act(() => {
        jest.advanceTimersByTime(300)
      })

      expect(onFilterChange).toHaveBeenCalledWith({ search: '', bucket: 'discarded', sort: 'score' })
    } finally {
      jest.runOnlyPendingTimers()
      jest.useRealTimers()
    }
  })

  it('renders a bucket-aware why-cell for a below-bar row (domain verdict pill + top gap)', () => {
    const rows = [
      {
        ...mockJobs[0],
        id: 20,
        score: 68,
        pipeline_status: 'scored',
        score_detail: JSON.stringify({
          assessment: {
            domain: { verdict: 'adjacent', note: 'ML infra, not research' },
            must_haves: { met: [], missing: ['live-desk production experience'] },
            summary: 'Close, but light on desk experience',
          },
        }),
      },
    ]
    renderTable({ data: rows, total: 1 })
    fireEvent.click(screen.getByRole('button', { name: 'Below bar' }))
    // The signature element: WHY it's under the bar — verdict + the top missing must-have.
    expect(screen.getByText('Adjacent')).toBeInTheDocument()
    expect(screen.getByText(/missing: live-desk production experience/)).toBeInTheDocument()
  })

  it('falls back to the legacy reasoning line for a below-bar row without a scorecard', () => {
    // Pre-round-2 rows have no `assessment`; the why-cell still says WHY via `reasoning`.
    const rows = [
      {
        ...mockJobs[0],
        id: 22,
        score: 70,
        pipeline_status: 'scored',
        score_detail: JSON.stringify({ reasoning: 'Strong Python engineer but only internship-level experience' }),
      },
    ]
    renderTable({ data: rows, total: 1 })
    fireEvent.click(screen.getByRole('button', { name: 'Below bar' }))
    expect(screen.getByText(/only internship-level experience/)).toBeInTheDocument()
  })

  it('shows both seniority and domain verdict pills for a below-bar row', () => {
    const rows = [
      {
        ...mockJobs[0],
        id: 23,
        score: 63,
        pipeline_status: 'scored',
        score_detail: JSON.stringify({
          assessment: {
            seniority: { verdict: 'too_junior', note: 'needs 3+ yrs' },
            domain: { verdict: 'adjacent', note: 'AI tooling, not quant' },
            must_haves: { met: [], missing: ['UNIX/Linux systems depth'] },
          },
        }),
      },
    ]
    renderTable({ data: rows, total: 1 })
    fireEvent.click(screen.getByRole('button', { name: 'Below bar' }))
    expect(screen.getByText('Too junior')).toBeInTheDocument()
    expect(screen.getByText('Adjacent')).toBeInTheDocument()
    expect(screen.getByText(/missing: UNIX\/Linux systems depth/)).toBeInTheDocument()
  })

  it('shows the recommended résumé label next to the score', () => {
    const rows = [
      { ...mockJobs[0], id: 24, score: 87, score_detail: JSON.stringify({ recommended_resume: 'quant_dev' }) },
    ]
    renderTable({ data: rows, total: 1 })   // default Matched bucket
    expect(screen.getByText('Quant Dev')).toBeInTheDocument()
  })

  it('renders the disqualification reason in the Discarded bucket why-cell', () => {
    const rows = [
      {
        ...mockJobs[0],
        id: 21,
        score: 90,
        pipeline_status: 'discarded',
        score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'internship/co-op role' }),
      },
    ]
    renderTable({ data: rows, total: 1 })
    fireEvent.click(screen.getByRole('button', { name: 'Discarded' }))
    expect(screen.getByText(/internship\/co-op role/)).toBeInTheDocument()
  })

  it('sends minScore in the filter payload', () => {
    jest.useFakeTimers()
    try {
      const onFilterChange = jest.fn()
      renderTable({ onFilterChange })
      fireEvent.change(screen.getByLabelText(/minimum score/i), { target: { value: '70' } })
      onFilterChange.mockClear()
      act(() => {
        jest.advanceTimersByTime(300)
      })
      expect(onFilterChange).toHaveBeenCalledWith(expect.objectContaining({ minScore: 70 }))
    } finally {
      jest.runOnlyPendingTimers()
      jest.useRealTimers()
    }
  })

  it('switching to the Low-context bucket fires onFilterChange with that bucket', () => {
    jest.useFakeTimers()
    try {
      const onFilterChange = jest.fn()
      renderTable({ onFilterChange })

      onFilterChange.mockClear()
      fireEvent.click(screen.getByRole('button', { name: 'Low-context' }))
      act(() => {
        jest.advanceTimersByTime(300)
      })

      // No cause sub-filter rides along (that sub-filter is Discarded-only).
      expect(onFilterChange).toHaveBeenCalledWith({ search: '', bucket: 'lowcontext', sort: 'score' })
    } finally {
      jest.runOnlyPendingTimers()
      jest.useRealTimers()
    }
  })

  it('does not show the disqualification-cause filter in the Low-context bucket', () => {
    renderTable()
    fireEvent.click(screen.getByRole('button', { name: 'Low-context' }))
    expect(screen.queryByLabelText(/disqualification cause/i)).not.toBeInTheDocument()
  })

  it('shows the disqualification-cause filter only in the Discarded bucket', () => {
    renderTable()
    expect(screen.queryByLabelText(/disqualification cause/i)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Discarded' }))
    expect(screen.getByLabelText(/disqualification cause/i)).toBeInTheDocument()
  })

  it('calls onPageChange when Next is clicked, and disables Previous on page 0', () => {
    const onPageChange = jest.fn()
    renderTable({ total: 60, page: 0, size: 25, onPageChange })   // 3 pages
    expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /next/i }))
    expect(onPageChange).toHaveBeenCalledWith(1)
  })

  it('renders the job title as a link to the live posting', () => {
    renderTable()
    const link = screen.getByRole('link', { name: 'Backend Engineer' })
    expect(link).toHaveAttribute('href', 'https://acme.example/jobs/1')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('sends the chosen sort in the filter payload', () => {
    jest.useFakeTimers()
    try {
      const onFilterChange = jest.fn()
      renderTable({ onFilterChange })
      fireEvent.click(screen.getByLabelText(/sort by/i))
      fireEvent.click(screen.getByText('Newest posted'))
      onFilterChange.mockClear()
      act(() => { jest.advanceTimersByTime(300) })
      expect(onFilterChange).toHaveBeenCalledWith(expect.objectContaining({ sort: 'posted' }))
    } finally {
      jest.runOnlyPendingTimers()
      jest.useRealTimers()
    }
  })

  it('selecting a matched row reveals Remove selected and calls onBulkRemove with ids', () => {
    const onBulkRemove = jest.fn()
    renderTable({ onBulkRemove })
    fireEvent.click(screen.getByLabelText('Select Backend Engineer'))
    fireEvent.click(screen.getByRole('button', { name: /remove selected/i }))
    expect(onBulkRemove).toHaveBeenCalledWith([1])
  })

  it('on the Discarded bucket, selected rows offer Reopen selected', () => {
    const onBulkReopen = jest.fn()
    renderTable({
      data: [{ ...mockJobs[0], pipeline_status: 'discarded' }],
      total: 1,
      onBulkReopen,
    })
    fireEvent.click(screen.getByRole('button', { name: 'Discarded' }))
    fireEvent.click(screen.getByLabelText('Select Backend Engineer'))
    fireEvent.click(screen.getByRole('button', { name: /reopen selected/i }))
    expect(onBulkReopen).toHaveBeenCalledWith([1])
  })

  it('select-all toggles every row on the page', () => {
    renderTable()
    fireEvent.click(screen.getByLabelText(/select all/i))
    expect(screen.getByText(/2 selected/i)).toBeInTheDocument()
  })

  it('clears selection when the data set changes', () => {
    const { rerender } = renderWithRerender()
    fireEvent.click(screen.getByLabelText('Select Backend Engineer'))
    expect(screen.getByText(/1 selected/i)).toBeInTheDocument()
    rerender([{ ...mockJobs[0], id: 99 }])
    expect(screen.queryByText(/selected/i)).not.toBeInTheDocument()
  })

  it('Remove all in view passes the live (non-debounced) discarded filter', () => {
    const onRemoveAllInView = jest.fn()
    renderTable({ onRemoveAllInView })
    fireEvent.click(screen.getByRole('button', { name: 'Discarded' }))
    fireEvent.click(screen.getByRole('button', { name: /remove all in view/i }))
    expect(onRemoveAllInView).toHaveBeenCalledWith(
      expect.objectContaining({ bucket: 'discarded', search: '' })
    )
  })
})
