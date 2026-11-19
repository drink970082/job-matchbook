import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { WatchlistTab } from '../WatchlistTab'

const removed = {
    id: 2, at: '2026-11-18T10:00:00.000Z', actor: 'mcp', action: 'remove',
    payload: { source: 'greenhouse', slug: 'acme', name: 'Acme', recipe: null },
}
const added = { ...removed, id: 1, action: 'add', actor: 'web' }

function renderTab(watchlist: any[], onAdd = jest.fn()) {
    render(<WatchlistTab promotions={[]} watchlist={watchlist} activity={[removed, added]}
        onApprove={jest.fn()} onDismiss={jest.fn()} onAdd={onAdd} onRemove={jest.fn()} />)
    return onAdd
}

test('a removal shows who did it and re-adds the stored row', async () => {
    const onAdd = renderTab([])
    expect(screen.getByText('Removed Acme (greenhouse/acme)')).toBeInTheDocument()
    expect(screen.getByText('via MCP')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Re-add' }))
    expect(onAdd).toHaveBeenCalledWith({ source: 'greenhouse', slug: 'acme', name: 'Acme' })
})

test('no Re-add once the company is watched again', () => {
    renderTab([{ id: 3, source: 'greenhouse', slug: 'acme', name: 'Acme' }])
    expect(screen.queryByRole('button', { name: 'Re-add' })).toBeNull()
})
