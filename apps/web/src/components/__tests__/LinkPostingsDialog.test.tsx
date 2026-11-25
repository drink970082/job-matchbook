import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { LinkPostingsDialog } from '@/components/LinkPostingsDialog'
import { getLinkSuggestions, linkApplication } from '@/lib/link-actions'
import { toast } from 'sonner'

jest.mock('@/lib/link-actions')
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }))

const suggestion = (job_id: number, tier: 1 | 2 | 3, over = {}) => ({ job_id, tier, company_name: 'Acme', job_title: `Role ${job_id}`,
    job_url: `https://x.test/${job_id}`, location: 'NYC', posted_at: '2026-11-01', source_state: 'available', ...over })
const item = (id: number, suggestions: any[], more = 0) => ({ more, suggestions,
    application: { id, company_name: 'Acme', job_title: `App ${id}`, application_url: null, date_applied: '2026-11-02', status: 'Applied' } })
const onClose = jest.fn()
const onLinked = jest.fn()
const show = (applicationId: number | null = null) =>
    render(<LinkPostingsDialog open applicationId={applicationId} onClose={onClose} onLinked={onLinked} />)

beforeEach(() => jest.clearAllMocks())

test('lists each application with its labelled candidates and links only what is clicked', async () => {
    ;(getLinkSuggestions as jest.Mock).mockResolvedValue({ success: true, data: [
        item(1, [suggestion(10, 1), suggestion(11, 3, { source_state: 'closed' })]), item(2, [suggestion(10, 2), suggestion(12, 3)], 4)] })
    ;(linkApplication as jest.Mock).mockResolvedValue({ success: true })
    show()
    const first = await screen.findByRole('region', { name: 'Acme - App 1' })
    expect(getLinkSuggestions).toHaveBeenCalledWith({})
    expect(linkApplication).not.toHaveBeenCalled()
    expect(first).toHaveTextContent('Same posting')
    expect(first).toHaveTextContent('closed')
    expect(screen.getByText('4 more postings at this company.')).toBeInTheDocument()
    fireEvent.click(within(first).getByRole('button', { name: /to Role 10 \(job 10\)/ }))
    await waitFor(() => expect(linkApplication).toHaveBeenCalledWith(1, 10))
    await waitFor(() => expect(onLinked).toHaveBeenCalledTimes(1))
    // The linked application leaves, and its posting leaves the other lists.
    expect(screen.queryByRole('region', { name: 'Acme - App 1' })).toBeNull()
    const second = screen.getByRole('region', { name: 'Acme - App 2' })
    expect(within(second).queryByText('Role 10')).toBeNull()
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.click(within(second).getByRole('button', { name: /job 12/ }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
})

test('a refused link keeps the list and shows the reason', async () => {
    ;(getLinkSuggestions as jest.Mock).mockResolvedValue({ success: true, data: [item(1, [suggestion(10, 2)])] })
    ;(linkApplication as jest.Mock).mockResolvedValue({ success: false, error: 'Job 10 is already linked to application 5' })
    show(1)
    expect(getLinkSuggestions).toHaveBeenCalledWith({ applicationId: 1 })
    fireEvent.click(await screen.findByRole('button', { name: /job 10/ }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Job 10 is already linked to application 5'))
    expect(screen.getByRole('region', { name: 'Acme - App 1' })).toBeInTheDocument()
    expect(onLinked).not.toHaveBeenCalled()
})

test('no candidate, and a failed load, say so', async () => {
    ;(getLinkSuggestions as jest.Mock).mockResolvedValueOnce({ success: true, data: [item(1, [])] })
    const { unmount } = show(1)
    expect(await screen.findByText('No posting found for this application.')).toBeInTheDocument()
    unmount()
    ;(getLinkSuggestions as jest.Mock).mockResolvedValueOnce({ success: false, error: 'Application not found' })
    show(1)
    expect(await screen.findByText('Application not found')).toBeInTheDocument()
})
