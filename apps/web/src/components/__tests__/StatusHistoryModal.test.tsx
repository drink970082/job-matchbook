
import { render, screen, waitFor } from '@testing-library/react'
import { StatusHistoryModal } from '../StatusHistoryModal'
import userEvent from '@testing-library/user-event'

describe('StatusHistoryModal', () => {
    const mockHistory = [
        { id: 11, status: 'Applied', timestamp: '2023-01-01', notes: 'Initial application' },
        { id: 22, status: 'Interviewing: 1st round', timestamp: '2023-01-15', notes: 'First round' }
    ]

    const mockApplication = {
        id: 1,
        company_name: 'Google',
        job_title: 'SWE',
        category: 'SWE',
    }

    const makeProps = () => ({
        isOpen: true,
        onClose: jest.fn(),
        application: mockApplication,
        history: mockHistory,
        onAddStatus: jest.fn(),
        onDeleteHistory: jest.fn(),
        onEditApplication: jest.fn().mockResolvedValue(undefined),
    })

    // The history list renders an icon-only Trash button per row (no accessible
    // text), so identify those rows by their empty accessible name.
    const getDeleteButtons = () =>
        screen.getAllByRole('button').filter((b) => b.textContent?.trim() === '')

    it('should render history items', () => {
        render(<StatusHistoryModal {...makeProps()} />)
        expect(screen.getAllByText('Applied').length).toBeGreaterThan(0)
        expect(screen.getByText('First round')).toBeInTheDocument()
    })

    it('should call onClose when close button is clicked', async () => {
        const user = userEvent.setup()
        const props = makeProps()
        render(<StatusHistoryModal {...props} />)
        const closeButton = screen.getByRole('button', { name: /close/i })
        await user.click(closeButton)
        expect(props.onClose).toHaveBeenCalled()
    })

    it('should allow adding a new status', async () => {
        const user = userEvent.setup()
        const props = makeProps()
        render(<StatusHistoryModal {...props} />)

        const statusSelect = screen.getByLabelText(/status/i)
        await user.selectOptions(statusSelect, 'Offer')

        await user.type(screen.getByLabelText(/notes/i), 'Negotiating')

        await user.click(screen.getByRole('button', { name: /update status/i }))

        expect(props.onAddStatus).toHaveBeenCalledWith(expect.objectContaining({
            status: 'Offer',
            notes: 'Negotiating'
        }))
    })

    it('calls onDeleteHistory with the clicked row id', async () => {
        const user = userEvent.setup()
        const props = makeProps()
        render(<StatusHistoryModal {...props} />)

        const deleteButtons = getDeleteButtons()
        // Two history rows -> two delete buttons (and only those are icon-only).
        expect(deleteButtons).toHaveLength(2)

        // Second row is the 'First round' / id 22 entry.
        await user.click(deleteButtons[1])
        expect(props.onDeleteHistory).toHaveBeenCalledWith(22)
    })

    it('enters edit mode, saves changes, and returns to view mode', async () => {
        const user = userEvent.setup()
        const props = makeProps()
        render(<StatusHistoryModal {...props} />)

        // Enter edit mode.
        await user.click(screen.getByRole('button', { name: /^edit$/i }))

        // Edit fields are pre-populated from the application defaults.
        const companyInput = screen.getByPlaceholderText('Company Name')
        const titleInput = screen.getByPlaceholderText('Job Title')
        const categoryInput = screen.getByPlaceholderText('Category')
        expect(companyInput).toHaveValue('Google')
        expect(titleInput).toHaveValue('SWE')
        expect(categoryInput).toHaveValue('SWE')

        await user.clear(companyInput)
        await user.type(companyInput, 'Anthropic')
        await user.clear(titleInput)
        await user.type(titleInput, 'Research Engineer')
        await user.clear(categoryInput)
        await user.type(categoryInput, 'MLE')

        await user.click(screen.getByRole('button', { name: /^save$/i }))

        expect(props.onEditApplication).toHaveBeenCalledWith(
            mockApplication.id,
            expect.objectContaining({
                company_name: 'Anthropic',
                job_title: 'Research Engineer',
                category: 'MLE',
            }),
        )

        // After save the form collapses back to view mode (Edit button reappears).
        await waitFor(() => {
            expect(screen.getByRole('button', { name: /^edit$/i })).toBeInTheDocument()
        })
        expect(screen.queryByPlaceholderText('Company Name')).not.toBeInTheDocument()
    })

    it('cancels edit without calling onEditApplication and resets the form', async () => {
        const user = userEvent.setup()
        const props = makeProps()
        render(<StatusHistoryModal {...props} />)

        await user.click(screen.getByRole('button', { name: /^edit$/i }))

        const companyInput = screen.getByPlaceholderText('Company Name')
        await user.clear(companyInput)
        await user.type(companyInput, 'Throwaway')

        await user.click(screen.getByRole('button', { name: /^cancel$/i }))

        expect(props.onEditApplication).not.toHaveBeenCalled()

        // Back in view mode; re-opening edit shows the original (reset) value.
        await user.click(screen.getByRole('button', { name: /^edit$/i }))
        expect(screen.getByPlaceholderText('Company Name')).toHaveValue('Google')
    })
})
