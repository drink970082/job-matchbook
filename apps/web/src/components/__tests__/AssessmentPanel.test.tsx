import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { AssessmentPanel } from '../preselection/AssessmentPanel'

const workerRoot = resolve(__dirname, '../../../../worker')

describe('isolated synthetic assessment panel', () => {
    it('renders the real Python CLI projection through TypeScript validation', () => {
        const result = spawnSync('python3', [
            '-m',
            'ats_worker.preselection_view_cli',
            '--fixture',
            'tests/fixtures/preselection_assessment_contract.json',
            '--case',
            'current_success',
        ], { cwd: workerRoot, encoding: 'utf8' })

        expect(result.status).toBe(0)
        expect(result.stderr).toBe('')
        const projectedView: unknown = JSON.parse(result.stdout)
        render(<AssessmentPanel value={projectedView} />)

        expect(screen.getByRole('region', { name: 'Synthetic assessment preview' })).toBeInTheDocument()
        expect(screen.getByText('Assessment state:')).toBeInTheDocument()
        expect(screen.getByText('Current')).toBeInTheDocument()
        expect(screen.getByText('Latest attempt: Succeeded')).toBeInTheDocument()
        expect(screen.getByText('Seniority alignment')).toBeInTheDocument()
        expect(screen.getByText('84 / 100')).toBeInTheDocument()
        expect(screen.getByText(/Fabricated JD text: experience designing reliable data services\./)).toBeInTheDocument()
        expect(screen.getByText(/does not determine qualification/)).toBeInTheDocument()
        expect(screen.queryByText(/SYNTHETIC_PRIVATE_/)).not.toBeInTheDocument()
    })
})
