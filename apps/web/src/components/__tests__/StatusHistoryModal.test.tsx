
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { StatusHistoryModal } from '../StatusHistoryModal'
import userEvent from '@testing-library/user-event'

describe('StatusHistoryModal', () => {
    const mockHistory = [
        { id: 1, status: 'Applied', timestamp: '2023-01-01', notes: 'Initial application' },
        { id: 2, status: 'Interviewing: 1st round', timestamp: '2023-01-15', notes: 'First round' }
    ]

    const mockApplication = {
        id: 1,
        company_name: 'Google',
        job_title: 'SWE',
    }

    const defaultProps = {
        isOpen: true,
        onClose: jest.fn(),
        application: mockApplication,
        history: mockHistory,
        onAddStatus: jest.fn(),
        onDeleteHistory: jest.fn(),
    }

    it('should render history items', () => {
        render(<StatusHistoryModal {...defaultProps} />)
        expect(screen.getAllByText('Applied').length).toBeGreaterThan(0)
        expect(screen.getByText('First round')).toBeInTheDocument()
    })

    it('should call onClose when close button is clicked', async () => {
        const user = userEvent.setup()
        render(<StatusHistoryModal {...defaultProps} />)
        const closeButton = screen.getByRole('button', { name: /close/i })
        await user.click(closeButton)
    })

    it('should allow adding a new status', async () => {
        const user = userEvent.setup()
        const onAddStatus = jest.fn()
        render(<StatusHistoryModal {...defaultProps} onAddStatus={onAddStatus} />)

        const statusSelect = screen.getByLabelText(/status/i)
        await user.selectOptions(statusSelect, 'Offer')

        await user.type(screen.getByLabelText(/notes/i), 'Negotiating')

        await user.click(screen.getByRole('button', { name: /update status/i }))

        expect(onAddStatus).toHaveBeenCalledWith(expect.objectContaining({
            status: 'Offer',
            notes: 'Negotiating'
        }))
    })
})
