import { render, screen } from '@testing-library/react'
import { ScorerUsageBar } from '@/components/ScorerUsageBar'

afterEach(() => jest.restoreAllMocks())

test('shows the plain login command for the default codex home', async () => {
    global.fetch = jest.fn().mockResolvedValue({ json: async () => ({
        backend: 'codex', auth_required: true, limits: [], as_of: null,
    }) })
    render(<ScorerUsageBar />)
    expect(await screen.findByRole('status')).toHaveTextContent('Codex login needs attention')
    expect(screen.getByText('codex login --device-auth')).toBeVisible()
})

test('prefixes the worker\'s non-default CODEX_HOME', async () => {
    global.fetch = jest.fn().mockResolvedValue({ json: async () => ({
        backend: 'codex', auth_required: true, codex_home: '$HOME/.codex-work',
        limits: [], as_of: null,
    }) })
    render(<ScorerUsageBar />)
    expect(await screen.findByText('CODEX_HOME="$HOME/.codex-work" codex login --device-auth')).toBeVisible()
})

test('a successful Codex reading does not show a login notice', async () => {
    global.fetch = jest.fn().mockResolvedValue({ json: async () => ({
        backend: 'codex', limits: [], as_of: null,
    }) })
    render(<ScorerUsageBar />)
    await screen.findByText('No scorer usage recorded yet.')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
})
