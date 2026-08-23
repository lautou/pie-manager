// SPDX-License-Identifier: AGPL-3.0-or-later
import { useQuery } from '@tanstack/react-query';
import apiClient from '../api/client';
import type { SyncStatus } from '../types';

/** Poll faster while a refresh is running, so the "Actualiser maintenant" button and
 * status badge flip back to idle promptly instead of waiting up to 60s. Shared by every
 * once-a-day background sync-status hook built via makeSyncStatusHook below. */
export function macroRefetchInterval(query: { state: { data?: SyncStatus } }): number {
  return query.state.data?.status === 'running' ? 3_000 : 60_000;
}

/** Same shape as useSyncStatus (SyncStatus), different endpoint/queryKey — a once-a-day
 * background task, polled less aggressively than live prices. */
function makeSyncStatusHook(endpoint: string, queryKey: string) {
  return function useSyncStatusHook() {
    return useQuery<SyncStatus>({
      queryKey: [queryKey],
      queryFn: async () => (await apiClient.get<SyncStatus>(endpoint)).data,
      refetchInterval: macroRefetchInterval,
      staleTime: 30_000,
    });
  };
}

export const useMacroSyncStatus = makeSyncStatusHook('/api/indicators/sync-status', 'macro-sync-status');

export const useCountryPerfSyncStatus = makeSyncStatusHook(
  '/api/indicators/country-performance/sync-status', 'country-perf-sync-status',
);
