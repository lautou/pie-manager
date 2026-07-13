import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/**/*.d.ts', 'src/main.tsx'],
      all: true,
      reporter: ['text', 'lcov'],
      thresholds: {
        // Unreachable branches are suppressed with targeted v8 ignore directives
        // (/* v8 ignore next -- @preserve */) so all four metrics reach exactly 100%.
        statements: 100,
        branches: 100,
        functions: 100,
        lines: 100,
      },
    },
  },
})
