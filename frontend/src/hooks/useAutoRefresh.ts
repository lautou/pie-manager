import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import apiClient from '../api/client';

export const REFRESH_INTERVAL_MS = 15 * 60 * 1000; // 15 minutes

// Query keys that represent live portfolio data (prices, balances, positions)
export const REFRESH_KEYS = ['dashboard', 'positions', 'accounts-summary', 'snapshots', 'sync-status'];

export function useAutoRefresh(portfolioId: string | undefined) {
  const qc = useQueryClient();
  const lastDayRef = useRef(new Date().getDate());

  useEffect(() => {
    if (!portfolioId) return;

    // 15-min UI refresh: Celery Beat handles the price sync, we just re-fetch data
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
}
