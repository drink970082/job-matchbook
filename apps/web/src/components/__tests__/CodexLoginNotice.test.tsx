import { render, screen } from '@testing-library/react'
import { ScorerUsageBar } from '@/components/ScorerUsageBar'

afterEach(() => jest.restoreAllMocks())

test('shows the ATS login command even without a quota reading', async () => {
    global.fetch = jest.fn().mockResolvedValue({ json: async () => ({
        backend: 'codex', auth_required: true, limits: [], as_of: null,
    }) })
    render(<ScorerUsageBar />)
    expect(await screen.findByRole('status')).toHaveTextContent('Codex login needs attention')
    expect(screen.getByText('CODEX_HOME="$HOME/.codex-ats" codex login --device-auth')).toBeVisible()
})

test('a successful Codex reading does not show a login notice', async () => {
    global.fetch = jest.fn().mockResolvedValue({ json: async () => ({
        backend: 'codex', limits: [], as_of: null,
    }) })
    render(<ScorerUsageBar />)
    await screen.findByText('No scorer usage recorded yet.')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
})
