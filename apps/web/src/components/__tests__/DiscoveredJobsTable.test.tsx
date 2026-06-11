import { render, screen, fireEvent, act } from '@testing-library/react'
import { DiscoveredJobsTable } from '@/components/DiscoveredJobsTable'
import userEvent from '@testing-library/user-event'

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

describe('DiscoveredJobsTable', () => {
  it('renders rows with company, job title and source', () => {
    render(
      <DiscoveredJobsTable
        data={mockJobs}
        total={2}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )

    expect(screen.getByText('Acme')).toBeInTheDocument()
    expect(screen.getByText('Globex')).toBeInTheDocument()
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument()
    expect(screen.getByText('ML Engineer')).toBeInTheDocument()
  })

  it('shows the score for each row', () => {
    render(
      <DiscoveredJobsTable
        data={mockJobs}
        total={2}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )

    expect(screen.getByText('91')).toBeInTheDocument()
    expect(screen.getByText('78')).toBeInTheDocument()
  })

  it('shows a multi-page warning flag when resume_pages > 1', () => {
    render(
      <DiscoveredJobsTable
        data={mockJobs}
        total={2}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )

    // The 2-page row (Globex) should show a warning; the 1-page row should not.
    const warnings = screen.getAllByTitle(/page/i)
    expect(warnings.length).toBe(1)
    expect(warnings[0]).toHaveTextContent(/2/)
  })

  it('calls onMarkApplied when the Mark Applied action is clicked', () => {
    const onMarkApplied = jest.fn()
    render(
      <DiscoveredJobsTable
        data={mockJobs}
        total={2}
        onFilterChange={jest.fn()}
        onMarkApplied={onMarkApplied}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )

    const buttons = screen.getAllByTitle(/mark applied/i)
    fireEvent.click(buttons[0])
    expect(onMarkApplied).toHaveBeenCalledWith(1)
  })

  it('renders empty state when there is no data', () => {
    render(
      <DiscoveredJobsTable
        data={[]}
        total={0}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )
    expect(screen.getByText(/no results/i)).toBeInTheDocument()
  })

  it('shows a Reopen control for discarded rows and calls onReopen', () => {
    const onReopen = jest.fn()
    const discarded = [{ ...mockJobs[0], pipeline_status: 'discarded' }]
    render(
      <DiscoveredJobsTable
        data={discarded}
        total={1}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={onReopen}
        onViewJD={jest.fn()}
      />
    )

    // Discard is replaced by Reopen for a discarded row.
    expect(screen.queryByTitle(/discard/i)).not.toBeInTheDocument()
    const reopen = screen.getByTitle(/reopen/i)
    fireEvent.click(reopen)
    expect(onReopen).toHaveBeenCalledWith(1)
  })

  it('calls onViewJD with the row id when View JD is clicked', () => {
    const onViewJD = jest.fn()
    render(
      <DiscoveredJobsTable
        data={mockJobs}
        total={2}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={onViewJD}
      />
    )

    const viewButtons = screen.getAllByTitle(/view jd/i)
    fireEvent.click(viewButtons[0])
    expect(onViewJD).toHaveBeenCalledWith(1)
  })

  it('calls onDiscard with the row id for a non-discarded row', () => {
    const onDiscard = jest.fn()
    render(
      <DiscoveredJobsTable
        data={mockJobs}
        total={2}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={onDiscard}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )

    // mockJobs[0] (id 1) is 'scored' (not discarded) -> shows a Discard action.
    const discardButtons = screen.getAllByTitle(/discard/i)
    fireEvent.click(discardButtons[0])
    expect(onDiscard).toHaveBeenCalledWith(1)
  })

  it('renders a — fallback for a row whose score is null', () => {
    const withNullScore = [{ ...mockJobs[0], score: null }]
    render(
      <DiscoveredJobsTable
        data={withNullScore}
        total={1}
        onFilterChange={jest.fn()}
        onMarkApplied={jest.fn()}
        onDiscard={jest.fn()}
        onReopen={jest.fn()}
        onViewJD={jest.fn()}
      />
    )

    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('debounces onFilterChange and maps the default queue/score state to undefined', () => {
    jest.useFakeTimers()
    try {
      const onFilterChange = jest.fn()
      render(
        <DiscoveredJobsTable
          data={mockJobs}
          total={2}
          onFilterChange={onFilterChange}
          onMarkApplied={jest.fn()}
          onDiscard={jest.fn()}
          onReopen={jest.fn()}
          onViewJD={jest.fn()}
        />
      )

      const searchInput = screen.getByPlaceholderText(/search/i)
      // fireEvent (not userEvent) is used here because userEvent and fake timers
      // need extra wiring; a controlled input updates fine with fireEvent.change.
      fireEvent.change(searchInput, { target: { value: 'Acme' } })

      // Debounce window not elapsed yet (the initial-mount effect fires once with
      // the default state; we only assert the post-search payload below).
      onFilterChange.mockClear()
      act(() => {
        jest.advanceTimersByTime(300)
      })

      expect(onFilterChange).toHaveBeenCalledWith({
        search: 'Acme',
        // status default 'queue' maps to undefined; minScore default 'all' maps to undefined.
        status: undefined,
        minScore: undefined,
      })
    } finally {
      jest.runOnlyPendingTimers()
      jest.useRealTimers()
    }
  })

  it('maps a selected Min Score option to a Number in the filter payload (Radix Select)', async () => {
    // Radix Select opens via pointer interactions that jsdom does not implement
    // (hasPointerCapture / scrollIntoView). Stub those locally so the portal can
    // open, then drive the trigger + option with keyboard + click. The stubs are
    // scoped to this test and removed in finally (no jest-config changes).
    const origHasPC = (Element.prototype as any).hasPointerCapture
    const origSetPC = (Element.prototype as any).setPointerCapture
    const origReleasePC = (Element.prototype as any).releasePointerCapture
    const origScroll = (Element.prototype as any).scrollIntoView
    ;(Element.prototype as any).hasPointerCapture = () => false
    ;(Element.prototype as any).setPointerCapture = () => {}
    ;(Element.prototype as any).releasePointerCapture = () => {}
    ;(Element.prototype as any).scrollIntoView = () => {}

    try {
      const onFilterChange = jest.fn()
      const user = userEvent.setup()
      render(
        <DiscoveredJobsTable
          data={mockJobs}
          total={2}
          onFilterChange={onFilterChange}
          onMarkApplied={jest.fn()}
          onDiscard={jest.fn()}
          onReopen={jest.fn()}
          onViewJD={jest.fn()}
        />
      )

      // The Min Score trigger shows its current value ("Any Score") as its text.
      // (Radix SelectValue placeholder does not surface as an accessible name in jsdom.)
      const minScoreTrigger = screen.getByText('Any Score').closest('[role="combobox"]') as HTMLElement
      expect(minScoreTrigger).not.toBeNull()

      // Open via keyboard (Radix opens the listbox on Enter/Space/ArrowDown).
      minScoreTrigger.focus()
      await user.keyboard('{Enter}')

      const option = await screen.findByRole('option', { name: '80+' })
      await user.click(option)

      // Wait out the 300ms debounce and assert the numeric mapping ('80' -> 80).
      await new Promise((r) => setTimeout(r, 350))
      expect(onFilterChange).toHaveBeenLastCalledWith(
        expect.objectContaining({ minScore: 80, status: undefined }),
      )
    } finally {
      ;(Element.prototype as any).hasPointerCapture = origHasPC
      ;(Element.prototype as any).setPointerCapture = origSetPC
      ;(Element.prototype as any).releasePointerCapture = origReleasePC
      ;(Element.prototype as any).scrollIntoView = origScroll
    }
  })
})
