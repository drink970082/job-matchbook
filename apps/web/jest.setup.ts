import '@testing-library/jest-dom'

// Radix UI uses scrollIntoView internally; jsdom doesn't implement it.
window.HTMLElement.prototype.scrollIntoView = jest.fn()
