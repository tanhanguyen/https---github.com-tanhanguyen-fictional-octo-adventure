import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// RTL leaves mounted trees behind between tests unless we unmount them; do it globally
// so every test starts from a clean DOM.
afterEach(() => {
  cleanup()
})
