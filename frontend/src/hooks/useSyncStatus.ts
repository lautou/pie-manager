import { useQuery } from '@tanstack/react-query';
import apiClient from '../api/client';
import type { SyncStatus } from '../types';

export type { SyncStatus };

async function fetchSyncStatus(): Promise<SyncStatus> {
  const { data } = await apiClient.get('/api/admin/sync-status');
  return data;
}

export function useSyncStatus() {
  return useQuery<SyncStatus>({
    queryKey: ['sync-status'],
    queryFn: fetchSyncStatus,
    refetchInterval: 60_000,   // poll every 60 s
    staleTime: 30_000,
  });
}

/** Format finished_at as "HH:MM" local time. Returns null if not available. */
export function formatSyncTime(status: SyncStatus | undefined): string | null {
  const ts = status?.finished_at ?? status?.started_at;
  if (!ts) return null;
  return new Date(ts).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

/** Format finished_at as "JJ/MM HH:MM" when it's a different day */
export function formatSyncDateTime(status: SyncStatus | undefined): string | null {
  const ts = status?.finished_at ?? status?.started_at;
  if (!ts) return null;
  const d = new Date(ts);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) {
    return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })
    + ' ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}
