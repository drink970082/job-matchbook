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
    resume_path: '/resumes/1.pdf',
    resume_pages: 1,
    pipeline_status: 'scored',
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
    resume_path: '/resumes/2.pdf',
    resume_pages: 2,
    pipeline_status: 'tailored',
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

  it('shows the score for each row', () => {
    renderTable()
    expect(screen.getByText('91')).toBeInTheDocument()
    expect(screen.getByText('78')).toBeInTheDocument()
  })

  it('shows a multi-page warning flag when resume_pages > 1', () => {
    renderTable()
    // The 2-page row (Globex) should show a warning; the 1-page row should not.
    const warnings = screen.getAllByTitle(/page/i)
    expect(warnings.length).toBe(1)
    expect(warnings[0]).toHaveTextContent(/2/)
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
    // mockJobs[0] (id 1) is 'scored' (not discarded) -> shows a Discard action.
    fireEvent.click(screen.getAllByTitle(/discard/i)[0])
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

      expect(onFilterChange).toHaveBeenCalledWith({ search: '', bucket: 'discarded', discardType: 'nearmiss', sort: 'score' })
    } finally {
      jest.runOnlyPendingTimers()
      jest.useRealTimers()
    }
  })

  it('distinguishes disqualified (with reason) from low-score rows', () => {
    const rows = [
      // High score but hard-disqualified -> shows the reason, not "low score".
      {
        ...mockJobs[0],
        id: 10,
        score: 90,
        pipeline_status: 'discarded',
        score_detail: JSON.stringify({ disqualified: true, disqualification_reason: 'internship/co-op role' }),
      },
      // Below threshold, not disqualified -> "low score".
      { ...mockJobs[0], id: 11, score: 60, pipeline_status: 'scored', score_detail: null },
    ]
    renderTable({ data: rows, total: 2 })
    expect(screen.getByText(/internship\/co-op role/)).toBeInTheDocument()
    expect(screen.getByText(/low score/i)).toBeInTheDocument()
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

  it('shows the discard-type filter only in the Discarded bucket', () => {
    renderTable()
    expect(screen.queryByLabelText(/discard type/i)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Discarded' }))
    expect(screen.getByLabelText(/discard type/i)).toBeInTheDocument()
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
})
