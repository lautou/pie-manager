import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_BACKEND_URL || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/utils/vitest-setup.ts'],
    server: {
      deps: {
        inline: ['react-i18next', 'i18next'],
      },
    },
    // ForceExitReporter calls process.exit(0) from the main Vitest process
    // after all tests complete. This terminates all fork workers regardless of
    // lingering handles (React Query gcTime timers, jsdom internals from
    // DashboardPage.test.tsx that prevent clean worker exit).
    // Without this, the test run hangs for 16+ minutes after ~50s of tests.
    reporters: process.env.VITEST_WATCH
      ? ['default']
      : ['dot', './tests/utils/coverage-ignore-reporter.ts'],
    globalSetup: './tests/utils/global-setup.ts',
    pool: 'forks',
    poolOptions: {
      forks: {
        singleFork: true,
      },
    },
    // `coverage` config lives in vitest.config.ts, not here: when both a vite.config.ts
    // and a standalone vitest.config.ts exist, Vitest resolves `test.coverage` from the
    // standalone file only — any `coverage` block declared here would be silently ignored.
  },
});
