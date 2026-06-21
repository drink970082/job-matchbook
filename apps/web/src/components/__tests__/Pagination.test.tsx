import { render, screen, fireEvent } from '@testing-library/react'
import { Pagination, pageItems } from '@/components/Pagination'

describe('pageItems', () => {
  it('windows around the current page with ellipsis for gaps', () => {
    expect(pageItems(1, 1)).toEqual([1])
    expect(pageItems(3, 5)).toEqual([1, 2, 3, 4, 5])           // no gaps
    expect(pageItems(1, 5)).toEqual([1, 2, 'ellipsis', 5])
    expect(pageItems(40, 81)).toEqual([1, 'ellipsis', 39, 40, 41, 'ellipsis', 81])
  })
})

describe('Pagination', () => {
  it('jumps to an exact page via a page-number button', () => {
    const onPageChange = jest.fn()
    render(<Pagination page={0} size={10} total={30} onPageChange={onPageChange} />)  // 3 pages
    fireEvent.click(screen.getByRole('button', { name: 'Page 3' }))
    expect(onPageChange).toHaveBeenCalledWith(2)  // 0-indexed
  })

  it('goes to the last page', () => {
    const onPageChange = jest.fn()
    render(<Pagination page={0} size={10} total={100} onPageChange={onPageChange} />)  // 10 pages
    fireEvent.click(screen.getByRole('button', { name: /last page/i }))
    expect(onPageChange).toHaveBeenCalledWith(9)
  })

  it('clamps an out-of-range go-to-page entry', () => {
    const onPageChange = jest.fn()
    render(<Pagination page={0} size={10} total={100} onPageChange={onPageChange} />)
    const input = screen.getByLabelText(/go to page/i)
    fireEvent.change(input, { target: { value: '999' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onPageChange).toHaveBeenCalledWith(9)  // clamped to last page
  })

  it('disables First/Previous on the first page', () => {
    render(<Pagination page={0} size={10} total={100} onPageChange={jest.fn()} />)
    expect(screen.getByRole('button', { name: /first page/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /previous page/i })).toBeDisabled()
  })
})
