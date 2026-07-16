import '@testing-library/jest-dom'

// Radix UI uses scrollIntoView internally; jsdom doesn't implement it. Guarded so
// this shared setup stays no-op under a `@jest-environment node` file (no window).
if (typeof window !== 'undefined') {
    window.HTMLElement.prototype.scrollIntoView = jest.fn()
}
