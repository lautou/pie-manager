// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Global Vitest setup.
 *
 * Configures a global render wrapper so all render() calls automatically get
 * the I18nextProvider with French translations — no per-test wrapper needed.
 *
 * NOTE: The DashboardPage worker hang (lingering jsdom timers) has NOT been
 * fixed here. The brute-force timer cleanup approach (clearing all IDs 0→max)
 * causes OOM because jsdom accumulates millions of timer IDs across the test
 * suite, and clearing them all allocates 8GB+ of memory.
 *
 * Current workaround: `timeout 120` in package.json test script.
 * See CLAUDE.md "Performance des tests frontend" for full context.
 *
 * Only the standard @testing-library/react cleanup is applied here, which
 * unmounts components and clears the DOM after each test.
 */
import { afterEach } from 'vitest';
import { cleanup, configure } from '@testing-library/react';
import { I18nTestWrapper } from './i18n-wrapper';

// Wrap every render() call with I18nextProvider so useTranslation() works
// without a per-test provider setup.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
configure({ wrapper: I18nTestWrapper } as any);

afterEach(() => {
  cleanup();
});
