// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for useMacroSyncStatus.ts — mirrors useSyncStatus.test.ts's hook-test pattern.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { makeWrapper } from '../../tests/utils/react-query-wrapper';
import { macroRefetchInterval, useCountryPerfSyncStatus, useMacroSyncStatus } from './useMacroSyncStatus';
import type { SyncStatus } from '../types';

vi.mock('../api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

function makeStatus(overrides: Partial<SyncStatus> = {}): SyncStatus {
  return {
    status: 'success',
    started_at: null,
    finished_at: null,
    total_tickers: 0,
    succeeded: 0,
    failed_tickers: [],
    ...overrides,
  };
}

describe('macroRefetchInterval', () => {
  it('polls every 3s while a sync is running', () => {
    expect(macroRefetchInterval({ state: { data: makeStatus({ status: 'running' }) } })).toBe(3_000);
  });

  it('polls every 60s otherwise', () => {
    expect(macroRefetchInterval({ state: { data: makeStatus({ status: 'success' }) } })).toBe(60_000);
  });

  it('polls every 60s when there is no data yet', () => {
    expect(macroRefetchInterval({ state: { data: undefined } })).toBe(60_000);
  });
});

describe('useMacroSyncStatus hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches from /api/indicators/sync-status and returns data', async () => {
    const { default: apiClient } = await import('../api/client');
    const mockGet = vi.mocked(apiClient.get);
    const syncData = makeStatus({ status: 'success', started_at: 't0', finished_at: 't1', total_tickers: 4, succeeded: 4 });
    mockGet.mockResolvedValueOnce({ data: syncData } as any);

    const wrapper = makeWrapper();
    const { result } = renderHook(() => useMacroSyncStatus(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(syncData);
    expect(mockGet).toHaveBeenCalledWith('/api/indicators/sync-status');
  });

  it('returns undefined data initially (loading state)', () => {
    const wrapper = makeWrapper();
    const { result } = renderHook(() => useMacroSyncStatus(), { wrapper });
    expect(result.current.data).toBeUndefined();
  });
});

describe('useCountryPerfSyncStatus hook', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches from /api/indicators/country-performance/sync-status and returns data', async () => {
    const { default: apiClient } = await import('../api/client');
    const mockGet = vi.mocked(apiClient.get);
    const syncData = makeStatus({ status: 'success', started_at: 't0', finished_at: 't1', total_tickers: 23, succeeded: 23 });
    mockGet.mockResolvedValueOnce({ data: syncData } as any);

    const wrapper = makeWrapper();
    const { result } = renderHook(() => useCountryPerfSyncStatus(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(syncData);
    expect(mockGet).toHaveBeenCalledWith('/api/indicators/country-performance/sync-status');
  });

  it('returns undefined data initially (loading state)', () => {
    const wrapper = makeWrapper();
    const { result } = renderHook(() => useCountryPerfSyncStatus(), { wrapper });
    expect(result.current.data).toBeUndefined();
  });
});
