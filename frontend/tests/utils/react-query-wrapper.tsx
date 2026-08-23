// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Shared React Query wrapper for renderHook tests.
 *
 * Usage (in queries.test.ts, useSyncStatus.test.ts, etc.):
 *   import { makeWrapper } from '../../tests/utils/react-query-wrapper';
 *   const wrapper = makeWrapper();
 *   const { result } = renderHook(() => useMyHook(), { wrapper });
 */
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

/**
 * Creates a React Query wrapper component suitable for use with `renderHook`.
 *
 * @param qc - Optional pre-configured QueryClient; a fresh one with
 *             test-optimised settings is created when omitted.
 *
 * Test-optimised defaults:
 *   - gcTime: 0          → subscriptions are released immediately after unmount
 *   - staleTime: Infinity → no background refetches during tests
 *   - retry: false        → failed queries fail fast instead of retrying
 *   - refetchOn*: false   → no automatic refetches triggered by focus/mount/reconnect
 */
export function makeWrapper(qc?: QueryClient) {
  const client = qc ?? new QueryClient({
    defaultOptions: {
      queries: {
        gcTime: 0,
        staleTime: Infinity,
        retry: false,
        refetchOnWindowFocus: false,
        refetchOnMount: false,
        refetchOnReconnect: false,
      },
      mutations: { retry: false },
    },
  });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client }, children);
  }
  return Wrapper;
}
