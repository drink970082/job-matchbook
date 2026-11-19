import { render, screen } from '@testing-library/react'
import { QuotaBar } from '@/components/QuotaBar'

afterEach(() => jest.restoreAllMocks())

test('shows the plain login command for the default codex home', async () => {
    global.fetch = jest.fn().mockResolvedValue({ json: async () => ({
        backend: 'codex', auth_required: true, login_command: 'codex login --device-auth',
        limits: [], as_of: null,
    }) })
    render(<QuotaBar />)
    expect(await screen.findByRole('status')).toHaveTextContent('Codex login needs attention')
    expect(screen.getByText('codex login --device-auth')).toBeVisible()
})

test('shows the worker\'s login command verbatim, for any backend', async () => {
    global.fetch = jest.fn().mockResolvedValue({ json: async () => ({
        backend: 'codex', auth_required: true,
        login_command: 'CODEX_HOME="$HOME/.codex-work" codex login --device-auth',
        limits: [], as_of: null,
    }) })
    render(<QuotaBar />)
    expect(await screen.findByText('CODEX_HOME="$HOME/.codex-work" codex login --device-auth')).toBeVisible()
})

test('a successful Codex reading does not show a login notice', async () => {
    global.fetch = jest.fn().mockResolvedValue({ json: async () => ({
        backend: 'codex', limits: [], as_of: null,
    }) })
    render(<QuotaBar />)
    await screen.findByText('No subscription usage recorded yet.')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
})
