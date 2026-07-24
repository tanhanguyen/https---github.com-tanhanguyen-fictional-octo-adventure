import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Kept separate from vite.config.ts (and out of the tsconfig project references) so the
// vitest<->vite type-augmentation skew never blocks `npm run typecheck`; vitest loads this
// via esbuild at runtime, no tsc involved.
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
