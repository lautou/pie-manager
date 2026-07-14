import { useQuery } from '@tanstack/react-query';
import apiClient from '../api/client';
import type { SyncStatus } from '../types';

async function fetchMacroSyncStatus(): Promise<SyncStatus> {
  const { data } = await apiClient.get('/api/indicators/sync-status');
  return data;
}

/** Poll faster while a refresh is running, so the "Actualiser maintenant" button and
 * status badge flip back to idle promptly instead of waiting up to 60s. */
export function macroRefetchInterval(query: { state: { data?: SyncStatus } }): number {
  return query.state.data?.status === 'running' ? 3_000 : 60_000;
}

/** Same shape as useSyncStatus (SyncStatus), different endpoint — the macro indicators
 * refresh is a once-a-day background task, polled less aggressively than live prices. */
export function useMacroSyncStatus() {
  return useQuery<SyncStatus>({
    queryKey: ['macro-sync-status'],
    queryFn: fetchMacroSyncStatus,
    refetchInterval: macroRefetchInterval,
    staleTime: 30_000,
  });
}
