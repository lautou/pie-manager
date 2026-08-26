// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for useAutoRefresh hook.
 *
 * Strategy:
 * - Use vi.useFakeTimers() to control setInterval / setTimeout without waiting.
 * - Mock @tanstack/react-query so QueryClient.invalidateQueries is spy-able.
 * - Mock apiClient so no real HTTP request is fired.
 * - Use renderHook from @testing-library/react wrapped in a minimal QueryClientProvider.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { useAutoRefresh, REFRESH_INTERVAL_MS, REFRESH_KEYS } from './useAutoRefresh';

// ---------------------------------------------------------------------------
// Mock apiClient — prevents real HTTP calls
// ---------------------------------------------------------------------------
vi.mock('../api/client', () => ({
  default: {
    post: vi.fn().mockResolvedValue({}),
    get: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeWrapper(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useAutoRefresh', () => {
  let qc: QueryClient;

  beforeEach(() => {
    // Fix system time to noon UTC — advancing 15 min won't cross midnight
    // and the midnight-detection interval never fires a day change.
    vi.useFakeTimers({ now: new Date('2024-06-15T12:00:00.000Z') });
    qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.spyOn(qc, 'invalidateQueries');
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('does not call invalidateQueries when portfolioId is undefined', () => {
    renderHook(() => useAutoRefresh(undefined), { wrapper: makeWrapper(qc) });

    vi.advanceTimersByTime(REFRESH_INTERVAL_MS + 1);

    expect(qc.invalidateQueries).not.toHaveBeenCalled();
  });

  it('calls invalidateQueries for every REFRESH_KEY after one interval', () => {
    renderHook(() => useAutoRefresh('1'), { wrapper: makeWrapper(qc) });

    vi.advanceTimersByTime(REFRESH_INTERVAL_MS + 1);

    // One invalidation call per key in REFRESH_KEYS
    expect(qc.invalidateQueries).toHaveBeenCalledTimes(REFRESH_KEYS.length);
    for (const key of REFRESH_KEYS) {
      expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: [key] });
    }
  });

  it('calls invalidateQueries twice after two intervals', () => {
    renderHook(() => useAutoRefresh('1'), { wrapper: makeWrapper(qc) });

    vi.advanceTimersByTime(REFRESH_INTERVAL_MS * 2 + 1);

    expect(qc.invalidateQueries).toHaveBeenCalledTimes(REFRESH_KEYS.length * 2);
  });

  it('clears interval on unmount and stops calling invalidateQueries', () => {
    const { unmount } = renderHook(() => useAutoRefresh('1'), { wrapper: makeWrapper(qc) });

    unmount();

    // After unmount advancing time should produce no new calls
    vi.advanceTimersByTime(REFRESH_INTERVAL_MS * 3);
    expect(qc.invalidateQueries).not.toHaveBeenCalled();
  });

  it('triggers snapshot fill and refresh when day changes', async () => {
    const apiClient = (await import('../api/client')).default;

    // Fix the current day to e.g. the 10th
    const fakeDate = new Date(2026, 4, 10, 23, 59, 0); // May 10, 23:59
    vi.setSystemTime(fakeDate);

    renderHook(() => useAutoRefresh('1'), { wrapper: makeWrapper(qc) });

    // Advance 30 seconds → still May 10, no change
    vi.advanceTimersByTime(30_000);
    expect(apiClient.post).not.toHaveBeenCalled();

    // Cross midnight: advance to May 11 00:01
    vi.setSystemTime(new Date(2026, 4, 11, 0, 1, 0));
    // The midnight-check interval fires every 60 s; tick it
    vi.advanceTimersByTime(60_000);

    expect(apiClient.post).toHaveBeenCalledWith('/api/admin/fill-missing-snapshots');

    // After the 10-second delay, data is also refreshed
    vi.advanceTimersByTime(10_001);
    expect(qc.invalidateQueries).toHaveBeenCalled();
  });

  it('silently swallows a rejected fill-missing-snapshots request during the midnight check', async () => {
    const apiClient = (await import('../api/client')).default;
    // Make apiClient.post REJECT so the .catch(() => {}) callback fires
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error('Network error'));

    const fakeDate = new Date(2026, 4, 10, 23, 59, 0);
    vi.setSystemTime(fakeDate);

    renderHook(() => useAutoRefresh('1'), { wrapper: makeWrapper(qc) });

    // Cross midnight
    vi.setSystemTime(new Date(2026, 4, 11, 0, 1, 0));
    vi.advanceTimersByTime(60_000);

    // The .catch(() => {}) silences the rejection — no unhandled error
    // Wait a tick so the rejected promise resolves and .catch fires
    await Promise.resolve();
    await Promise.resolve();

    // Just verify no unhandled rejection occurred and post was called
    expect(apiClient.post).toHaveBeenCalledWith('/api/admin/fill-missing-snapshots');
  });

  it('exports REFRESH_KEYS as non-empty array of strings', () => {
    expect(Array.isArray(REFRESH_KEYS)).toBe(true);
    expect(REFRESH_KEYS.length).toBeGreaterThan(0);
    for (const key of REFRESH_KEYS) {
      expect(typeof key).toBe('string');
    }
  });

  it('exports REFRESH_INTERVAL_MS as a positive number', () => {
    expect(typeof REFRESH_INTERVAL_MS).toBe('number');
    expect(REFRESH_INTERVAL_MS).toBeGreaterThan(0);
  });

  // -------------------------------------------------------------------------
  // Sync-status driven refresh — precise trigger, complements the blind timer
  // -------------------------------------------------------------------------
  describe('sync-status driven refresh', () => {
    function syncStatusResponse(finishedAt: string) {
      return {
        data: {
          status: 'success', started_at: null, finished_at: finishedAt,
          total_tickers: 5, succeeded: 5, failed_tickers: [],
        },
      } as any;
    }

    it('does not invalidate on the first observed sync-status value (establishes baseline)', async () => {
      const apiClient = (await import('../api/client')).default;
      vi.mocked(apiClient.get).mockResolvedValueOnce(syncStatusResponse('2026-01-01T10:00:00Z'));

      renderHook(() => useAutoRefresh('1'), { wrapper: makeWrapper(qc) });
      await vi.advanceTimersByTimeAsync(0);

      expect(qc.invalidateQueries).not.toHaveBeenCalled();
    });

    it('invalidates REFRESH_KEYS when sync-status finished_at changes between polls', async () => {
      const apiClient = (await import('../api/client')).default;
      vi.mocked(apiClient.get)
        .mockResolvedValueOnce(syncStatusResponse('2026-01-01T10:00:00Z'))
        .mockResolvedValueOnce(syncStatusResponse('2026-01-01T10:15:00Z'));

      renderHook(() => useAutoRefresh('1'), { wrapper: makeWrapper(qc) });
      await vi.advanceTimersByTimeAsync(0); // initial fetch — baseline, no invalidation
      expect(qc.invalidateQueries).not.toHaveBeenCalled();

      // Simulate the next sync-status poll resolving with a new finished_at,
      // bypassing useSyncStatus's own refetchInterval/staleTime timing —
      // this test targets useAutoRefresh's reaction, not React Query's polling.
      await qc.refetchQueries({ queryKey: ['sync-status'] });
      await vi.advanceTimersByTimeAsync(0); // let the effect react to the new render

      expect(qc.invalidateQueries).toHaveBeenCalledTimes(REFRESH_KEYS.length);
      for (const key of REFRESH_KEYS) {
        expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: [key] });
      }
    });

    it('does not invalidate again when sync-status finished_at stays the same across polls', async () => {
      const apiClient = (await import('../api/client')).default;
      vi.mocked(apiClient.get).mockResolvedValue(syncStatusResponse('2026-01-01T10:00:00Z'));

      renderHook(() => useAutoRefresh('1'), { wrapper: makeWrapper(qc) });
      await vi.advanceTimersByTimeAsync(0);
      await qc.refetchQueries({ queryKey: ['sync-status'] });

      expect(qc.invalidateQueries).not.toHaveBeenCalled();
    });

    it('does not invalidate when the effect re-runs for a portfolioId change but finished_at is unchanged', async () => {
      const apiClient = (await import('../api/client')).default;
      vi.mocked(apiClient.get).mockResolvedValue(syncStatusResponse('2026-01-01T10:00:00Z'));

      const { rerender } = renderHook(
        ({ portfolioId }: { portfolioId: string }) => useAutoRefresh(portfolioId),
        { wrapper: makeWrapper(qc), initialProps: { portfolioId: '1' } },
      );
      await vi.advanceTimersByTimeAsync(0); // baseline recorded for finished_at

      // Switch portfolio — the effect re-runs (portfolioId dependency changed)
      // but finished_at is unchanged, so no invalidation should occur.
      rerender({ portfolioId: '2' });
      await vi.advanceTimersByTimeAsync(0);

      expect(qc.invalidateQueries).not.toHaveBeenCalled();
    });

    it('does not invalidate via sync-status when portfolioId is undefined', async () => {
      const apiClient = (await import('../api/client')).default;
      vi.mocked(apiClient.get)
        .mockResolvedValueOnce(syncStatusResponse('A'))
        .mockResolvedValueOnce(syncStatusResponse('B'));

      renderHook(() => useAutoRefresh(undefined), { wrapper: makeWrapper(qc) });
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(60_000);

      expect(qc.invalidateQueries).not.toHaveBeenCalled();
    });
  });
});
