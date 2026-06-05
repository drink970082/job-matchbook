import { render, screen } from '@testing-library/react'
import { KPIGrid } from '@/components/KPIGrid'

describe('KPIGrid', () => {
    it('should render all KPI values', () => {
        const stats = {
            applied: 10,
            active: 5,
            assessment: 2,
            interviewing: 3,
            rejected: 4,
            offer: 1
        }

        render(<KPIGrid stats={stats} />)

        expect(screen.getByText('Applied')).toBeInTheDocument()
        expect(screen.getByText('10')).toBeInTheDocument()

        expect(screen.getByText('Active')).toBeInTheDocument()
        expect(screen.getByText('5')).toBeInTheDocument()

        expect(screen.getByText('Offer')).toBeInTheDocument()
        expect(screen.getByText('1')).toBeInTheDocument()
    })
})
