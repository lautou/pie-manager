import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import apiClient from '../api/client';
import { useSyncStatus } from './useSyncStatus';

export const REFRESH_INTERVAL_MS = 15 * 60 * 1000; // 15 minutes

// Query keys that represent live portfolio data (prices, balances, positions)
export const REFRESH_KEYS = ['dashboard', 'positions', 'accounts-summary', 'snapshots', 'sync-status'];

export function useAutoRefresh(portfolioId: string | undefined) {
  const qc = useQueryClient();
  const lastDayRef = useRef(new Date().getDate());
  const { data: syncStatus } = useSyncStatus();
  const lastSyncRef = useRef<string | null>(null);

  useEffect(() => {
    if (!portfolioId) return;

    // 15-min UI refresh (fallback safety net): PgQueuer handles the price
    // sync on its own schedule; this ensures data doesn't go too stale even
    // if the sync-status-driven refresh below ever misses an update.
    const refreshId = setInterval(() => {
      REFRESH_KEYS.forEach((key) => qc.invalidateQueries({ queryKey: [key] }));
    }, REFRESH_INTERVAL_MS);

    // Midnight check: every minute, detect day change → trigger snapshot fill
    const midnightId = setInterval(() => {
      const today = new Date().getDate();
      if (today !== lastDayRef.current) {
        lastDayRef.current = today;
        // New day detected — generate yesterday's snapshot silently
        apiClient.post('/api/admin/fill-missing-snapshots').catch(() => {});
        // Refresh data after a short delay (let snapshot compute)
        setTimeout(() => {
          REFRESH_KEYS.forEach((key) => qc.invalidateQueries({ queryKey: [key] }));
        }, 10000);
      }
    }, 60_000);

    return () => {
      clearInterval(refreshId);
      clearInterval(midnightId);
    };
  }, [qc, portfolioId]);

  // Precise refresh: as soon as a new price sync completes (detected via
  // sync-status polling), invalidate immediately instead of waiting for the
  // blind 15-min timer above — which runs on its own clock, unrelated to
  // when PgQueuer's sync actually finishes.
  useEffect(() => {
    if (!portfolioId) return;
    const finishedAt = syncStatus?.finished_at ?? null;
    if (finishedAt === null) return;
    if (lastSyncRef.current === null) {
      // First observed value — just record the baseline, data is already fresh.
      lastSyncRef.current = finishedAt;
      return;
    }
    if (finishedAt !== lastSyncRef.current) {
      lastSyncRef.current = finishedAt;
      REFRESH_KEYS.forEach((key) => qc.invalidateQueries({ queryKey: [key] }));
    }
  }, [qc, portfolioId, syncStatus?.finished_at]);
}
