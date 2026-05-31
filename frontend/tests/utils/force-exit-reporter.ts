/**
 * Vitest custom reporter — forces the main process to exit after all tests.
 *
 * Root cause of the hang: DashboardPage.test.tsx leaves active Node.js handles
 * (React Query gcTime timers, jsdom internals) that prevent the fork worker
 * process from exiting cleanly. Vitest waits indefinitely for the worker to
 * exit, causing a 16+ minute hang despite tests completing in ~50 seconds.
 *
 * NOTE: This file is intentionally NOT included in the TypeScript project
 * (excluded from tsconfig). It is loaded by Vitest at runtime via its own
 * module resolution which handles the Node.js types correctly.
 */

export default class ForceExitReporter {
  onFinished() {
    if (!process.env['VITEST_WATCH']) {
      setTimeout(() => process.exit(0), 1000);
    }
  }
}
