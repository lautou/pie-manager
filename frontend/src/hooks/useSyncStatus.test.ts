/**
 * Tests for useSyncStatus.ts — helper functions AND the hook itself.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { makeWrapper } from '../../tests/utils/react-query-wrapper'
import { formatSyncTime, formatSyncDateTime, useSyncStatus } from './useSyncStatus'
import type { SyncStatus } from './useSyncStatus'

// Mock apiClient for hook tests
vi.mock('../api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))


function makeStatus(overrides: Partial<SyncStatus> = {}): SyncStatus {
  return {
    status: 'success',
    started_at: null,
    finished_at: null,
    total_tickers: 0,
    succeeded: 0,
    failed_tickers: [],
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// formatSyncTime
// ---------------------------------------------------------------------------

describe('formatSyncTime', () => {
  it('returns null for undefined status', () => {
    expect(formatSyncTime(undefined)).toBeNull()
  })

  it('returns null when both timestamps are null', () => {
    expect(formatSyncTime(makeStatus({ started_at: null, finished_at: null }))).toBeNull()
  })

  it('returns a non-null string when finished_at is set', () => {
    const status = makeStatus({ finished_at: '2026-01-15T10:30:00Z' })
    const result = formatSyncTime(status)
    expect(result).not.toBeNull()
    expect(typeof result).toBe('string')
    expect(result!.length).toBeGreaterThan(0)
  })

  it('returns a non-null string when only started_at is set', () => {
    const status = makeStatus({ started_at: '2026-01-15T09:00:00Z', finished_at: null })
    const result = formatSyncTime(status)
    expect(result).not.toBeNull()
    expect(typeof result).toBe('string')
  })

  it('prefers finished_at over started_at (different timestamps produce different results)', () => {
    const onlyStarted = makeStatus({ started_at: '2020-01-01T08:00:00Z', finished_at: null })
    const withFinished = makeStatus({ started_at: '2020-01-01T08:00:00Z', finished_at: '2020-01-01T09:00:00Z' })
    // Both return non-null; they may differ since finished_at is used when set
    expect(formatSyncTime(onlyStarted)).not.toBeNull()
    expect(formatSyncTime(withFinished)).not.toBeNull()
    // finished_at (09:00) ≠ started_at (08:00)
    expect(formatSyncTime(withFinished)).not.toBe(formatSyncTime(onlyStarted))
  })
})

// ---------------------------------------------------------------------------
// formatSyncDateTime
// ---------------------------------------------------------------------------

describe('formatSyncDateTime', () => {
  it('returns null for undefined status', () => {
    expect(formatSyncDateTime(undefined)).toBeNull()
  })

  it('returns null when both timestamps are null', () => {
    expect(formatSyncDateTime(makeStatus())).toBeNull()
  })

  it('returns a string without "/" for a timestamp from today', () => {
    // Noon today local time → same day as new Date() → no date prefix
    const today = new Date()
    today.setHours(12, 0, 0, 0)
    const status = makeStatus({ finished_at: today.toISOString() })
    const result = formatSyncDateTime(status)
    expect(result).not.toBeNull()
    // Today's result must NOT contain "/" (the date prefix separator)
    expect(result).not.toContain('/')
  })

  it('returns a string with "/" for a timestamp from a past date', () => {
    // 2020-03-15 is clearly not today in any timezone
    const status = makeStatus({ finished_at: '2020-03-15T12:00:00Z' })
    const result = formatSyncDateTime(status)
    expect(result).not.toBeNull()
    // Past date includes "DD/MM" prefix → must contain "/"
    expect(result).toContain('/')
  })

  it('prefers finished_at over started_at (a clear past date)', () => {
    const status = makeStatus({
      started_at: '2020-01-01T08:00:00Z',
      finished_at: '2020-01-01T10:00:00Z',
    })
    const result = formatSyncDateTime(status)
    expect(result).not.toBeNull()
    // Both are past dates → result includes "/"
    expect(result).toContain('/')
  })

  it('uses started_at when finished_at is null', () => {
    const status = makeStatus({ started_at: '2020-06-10T14:00:00Z', finished_at: null })
    const result = formatSyncDateTime(status)
    expect(result).not.toBeNull()
    expect(result).toContain('/')
  })
})

// ---------------------------------------------------------------------------
// issue #72 regression: a UTC-marked timestamp must convert to local wall-clock
// time, not be displayed as if the UTC value were already local. Pinned against a
// fixed timezone so the assertion is deterministic regardless of the CI runner's
// own local timezone.
// ---------------------------------------------------------------------------

describe('formatSyncTime — UTC-to-local conversion (issue #72)', () => {
  const originalTZ = process.env.TZ

  beforeEach(() => {
    process.env.TZ = 'Europe/Paris'
  })

  afterEach(() => {
    process.env.TZ = originalTZ
  })

  it('converts a UTC timestamp to Paris summer time (CEST, UTC+2)', () => {
    // 15:36 UTC in August (CEST) is 17:36 in Paris — the exact bug reported live.
    const status = makeStatus({ finished_at: '2026-08-14T15:36:32Z' })
    expect(formatSyncTime(status)).toBe('17:36')
  })

  it('converts a UTC timestamp to Paris winter time (CET, UTC+1)', () => {
    // 15:36 UTC in January (CET) is 16:36 in Paris.
    const status = makeStatus({ finished_at: '2026-01-14T15:36:32Z' })
    expect(formatSyncTime(status)).toBe('16:36')
  })
})

// ---------------------------------------------------------------------------
// useSyncStatus hook
// ---------------------------------------------------------------------------

describe('useSyncStatus hook', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns data on successful fetch', async () => {
    const { default: apiClient } = await import('../api/client')
    const mockGet = vi.mocked(apiClient.get)
    const syncData: SyncStatus = {
      status: 'success',
      started_at: '2026-01-15T10:00:00Z',
      finished_at: '2026-01-15T10:05:00Z',
      total_tickers: 10,
      succeeded: 10,
      failed_tickers: [],
    }
    mockGet.mockResolvedValueOnce({ data: syncData } as any)

    const wrapper = makeWrapper()
    const { result } = renderHook(() => useSyncStatus(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(syncData)
    expect(mockGet).toHaveBeenCalledWith('/api/admin/sync-status')
  })

  it('returns undefined data initially (loading state)', () => {
    const wrapper = makeWrapper()
    const { result } = renderHook(() => useSyncStatus(), { wrapper })

    // During initial fetch, data should be undefined
    expect(result.current.data).toBeUndefined()
  })
})
