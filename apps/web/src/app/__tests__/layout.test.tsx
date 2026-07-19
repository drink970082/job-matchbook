import { render } from '@testing-library/react'

Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: jest.fn().mockImplementation(query => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: jest.fn(),
        removeListener: jest.fn(),
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
        dispatchEvent: jest.fn(),
    })),
})

const captured: Record<string, unknown> = {}
jest.mock('sonner', () => ({
    Toaster: (props: Record<string, unknown>) => {
        Object.assign(captured, props)
        return null
    },
}))

import RootLayout from '../layout'

describe('RootLayout', () => {
    it('gives the Toaster a system-following theme (not hardcoded dark)', () => {
        render(<RootLayout>{null}</RootLayout>)
        expect(captured.theme).toBe('system')
    })
})
