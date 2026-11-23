import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SourcesTab, type WatchedSource } from '@/components/SourcesTab'
import { addWatchedCompany, removeWatchedCompany } from '@/lib/watchlist-actions'

const refresh = jest.fn()
jest.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))
jest.mock('@/lib/watchlist-actions')
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }))

const OK = { health: 'ok', last_fetched_at: '2026-11-21T08:00:00.000Z', last_fetch_status: 'ok',
    last_fetched: 30, last_kept: 6, last_new: 2, last_bodyless: 0, last_desc_median: 2100 } as const
const row = (id: number, over: Partial<WatchedSource> = {}): WatchedSource =>
    ({ id, source: 'greenhouse', slug: `co${id}`, name: `Company ${String(id).padStart(2, '0')}`, postings_30d: id, ...OK, ...over })

beforeEach(() => jest.clearAllMocks())

test('pages 25 at a time, searches and filters by source', () => {
    const rows = [...Array.from({ length: 30 }, (_, i) => row(i + 1)),
        row(31, { name: 'Dead Co', postings_30d: 0 }), row(32, { name: 'Lever Co', source: 'lever' })]
    render(<SourcesTab sources={rows} />)
    expect(screen.getAllByRole('row')).toHaveLength(26)            // header + 25
    expect(screen.queryByText('co1')).toBeNull()                    // slug only on hover
    expect(screen.getByText('Company 01')).toHaveAttribute('title', 'greenhouse/co1')
    fireEvent.change(screen.getByLabelText('Search boards'), { target: { value: 'DEAD' } })
    expect(screen.getAllByRole('row')).toHaveLength(2)
    expect(screen.getByText('Dead Co')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search boards'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'lever' } })
    expect(screen.getAllByRole('row')).toHaveLength(2)
    expect(screen.getByText('Lever Co')).toBeInTheDocument()
})

test('tells apart a failed fetch, filters keeping none, teasers and a board never fetched (#231)', () => {
    const never = { health: 'never_fetched', last_fetched_at: null, last_fetch_status: null, last_fetched: null,
        last_kept: null, last_new: null, last_bodyless: null, last_desc_median: null } as const
    render(<SourcesTab sources={[
        row(1, { name: 'Healthy Co' }),
        row(2, { name: 'Moved Co', health: 'fetch_failed', last_fetch_status: 'http_404', last_fetched: null, last_kept: null }),
        row(3, { name: 'Empty Co', health: 'empty', last_fetched: 0, last_kept: 0, last_new: 0 }),
        row(4, { name: 'Filtered Co', health: 'kept_zero', last_fetched: 40, last_kept: 0, last_new: 0 }),
        row(5, { name: 'Teaser Co', health: 'teaser', last_desc_median: 600 }),
        row(6, { name: 'Fresh Co', ...never }),
        row(7, { name: 'Headless Co', source: 'browser', ...never, health: 'disabled', last_fetch_status: 'disabled' }),
        row(8, { name: 'Broken Co', health: 'bodyless', last_fetched: 25, last_kept: 0, last_new: 0, last_bodyless: 9 }),
    ]} />)
    const cell = (name: string) => screen.getByText(name).closest('tr')!
    expect(cell('Healthy Co')).toHaveTextContent('30 listed, 6 kept, 2 new')
    expect(cell('Moved Co')).toHaveTextContent('Fetch failed: http_404')
    expect(cell('Empty Co')).toHaveTextContent('Board listed nothing')
    expect(cell('Filtered Co')).toHaveTextContent('40 listed, filters kept 0')
    expect(cell('Teaser Co')).toHaveTextContent('Teaser descriptions (median 600 chars)')
    expect(cell('Fresh Co')).toHaveTextContent('Never fetched')
    expect(cell('Headless Co')).toHaveTextContent('Not fetched: browser sources are off')
    expect(cell('Broken Co')).toHaveTextContent('Descriptions missing: 9 postings came back with none')
    fireEvent.change(screen.getByLabelText('Health'), { target: { value: 'fetch_failed' } })
    expect(screen.getAllByRole('row')).toHaveLength(2)
    expect(screen.getByText('Moved Co')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Health'), { target: { value: 'attention' } })
    expect(screen.getAllByRole('row').map((r) => r.textContent)).toEqual([
        expect.stringContaining('Company'), expect.stringContaining('Broken Co'), expect.stringContaining('Empty Co'),
        expect.stringContaining('Filtered Co'),
        expect.stringContaining('Moved Co'), expect.stringContaining('Teaser Co')])
})

test('sorts by postings', () => {
    render(<SourcesTab sources={[row(1), row(2), row(3)]} />)
    fireEvent.click(screen.getByRole('button', { name: /Postings \(30d\)/ }))
    fireEvent.click(screen.getByRole('button', { name: /Postings \(30d\)/ }))
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('Company 03')
})

test('adds a board from a pasted URL, with the name prefilled and editable', async () => {
    ;(addWatchedCompany as jest.Mock).mockResolvedValue({ success: true })
    render(<SourcesTab sources={[]} />)
    fireEvent.change(screen.getByLabelText('Careers or job URL'), { target: { value: 'https://jobs.lever.co/acme-robotics' } })
    expect(screen.getByText('lever board "acme-robotics"')).toBeInTheDocument()
    expect(screen.getByLabelText('Company name')).toHaveValue('Acme Robotics')
    fireEvent.change(screen.getByLabelText('Company name'), { target: { value: 'Typo' } })
    fireEvent.change(screen.getByLabelText('Careers or job URL'), { target: { value: 'https://jobs.lever.co/globex' } })
    expect(screen.getByLabelText('Company name')).toHaveValue('Globex')        // a new board resets the name
    fireEvent.change(screen.getByLabelText('Careers or job URL'), { target: { value: 'https://jobs.lever.co/acme-robotics' } })
    fireEvent.change(screen.getByLabelText('Company name'), { target: { value: 'Acme' } })
    fireEvent.change(screen.getByLabelText('Careers or job URL'), { target: { value: 'https://jobs.lever.co/acme-robotics/123' } })
    expect(screen.getByLabelText('Company name')).toHaveValue('Acme')          // same board keeps the edit
    fireEvent.click(screen.getByRole('button', { name: 'Add board' }))
    await waitFor(() => expect(addWatchedCompany).toHaveBeenCalledWith({ url: 'https://jobs.lever.co/acme-robotics/123', name: 'Acme' }))
    await waitFor(() => expect(refresh).toHaveBeenCalled())
})

test('an unresolvable URL points at the onboard-board skill and cannot be added', () => {
    render(<SourcesTab sources={[]} />)
    fireEvent.change(screen.getByLabelText('Careers or job URL'), { target: { value: 'https://www.acme.com/careers' } })
    expect(screen.getByText(/needs a custom recipe .* onboard-board skill/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add board' })).toBeDisabled()
})

test('remove asks first', async () => {
    ;(removeWatchedCompany as jest.Mock).mockResolvedValue({ success: true })
    const confirm = jest.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    render(<SourcesTab sources={[row(1, { source: 'custom' })]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Remove Company 01' }))
    expect(removeWatchedCompany).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Remove Company 01' }))
    await waitFor(() => expect(removeWatchedCompany).toHaveBeenCalledWith(1))
    confirm.mockRestore()
})
