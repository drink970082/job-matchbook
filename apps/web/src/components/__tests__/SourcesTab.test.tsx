import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SourcesTab, type WatchedSource } from '@/components/SourcesTab'
import { addWatchedCompany, removeWatchedCompany } from '@/lib/watchlist-actions'

const refresh = jest.fn()
jest.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }))
jest.mock('@/lib/watchlist-actions')
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }))

const row = (id: number, over: Partial<WatchedSource> = {}): WatchedSource =>
    ({ id, source: 'greenhouse', slug: `co${id}`, name: `Company ${String(id).padStart(2, '0')}`, postings_30d: id, ...over })

beforeEach(() => jest.clearAllMocks())

test('pages 25 at a time, searches, filters by source and flags dead and pending boards', () => {
    const rows = [...Array.from({ length: 30 }, (_, i) => row(i + 1)),
        row(31, { name: 'Dead Co', postings_30d: 0 }), row(32, { name: 'New Co', postings_30d: 0, pending: true, source: 'lever' })]
    render(<SourcesTab sources={rows} />)
    expect(screen.getAllByRole('row')).toHaveLength(26)            // header + 25
    expect(screen.queryByText('co1')).toBeNull()                    // slug only on hover
    expect(screen.getByText('Company 01')).toHaveAttribute('title', 'greenhouse/co1')
    fireEvent.change(screen.getByLabelText('Search boards'), { target: { value: 'DEAD' } })
    expect(screen.getAllByRole('row')).toHaveLength(2)
    expect(screen.getByText('Dead Co')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search boards'), { target: { value: '' } })
    fireEvent.click(screen.getByLabelText('Only boards with no postings'))
    expect(screen.getByText('No postings in 30 days')).toBeInTheDocument()
    expect(screen.queryByText('New Co')).toBeNull()                 // pending is not dead
    fireEvent.click(screen.getByLabelText('Only boards with no postings'))
    fireEvent.change(screen.getByLabelText('Source'), { target: { value: 'lever' } })
    expect(screen.getByText('Pending first fetch')).toBeInTheDocument()
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
    fireEvent.change(screen.getByLabelText('Company name'), { target: { value: 'Acme' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add board' }))
    await waitFor(() => expect(addWatchedCompany).toHaveBeenCalledWith({ url: 'https://jobs.lever.co/acme-robotics', name: 'Acme' }))
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
