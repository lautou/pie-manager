// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { makeWrapper } from '../../tests/utils/react-query-wrapper';
import { useSyncStatusInvalidation } from './useSyncStatusInvalidation';

function setup() {
  const qc = new QueryClient({
    defaultOptions: { queries: { gcTime: 0, staleTime: Infinity, retry: false } },
  });
  const invalidateSpy = vi.spyOn(qc, 'invalidateQueries');
  const wrapper = makeWrapper(qc);
  return { invalidateSpy, wrapper };
}

describe('useSyncStatusInvalidation', () => {
  it('does not invalidate on the first observed non-null finished_at (baseline)', () => {
    const { invalidateSpy, wrapper } = setup();
    const { rerender } = renderHook(
      ({ finishedAt }) => useSyncStatusInvalidation(finishedAt, [['country-performance']]),
      { wrapper, initialProps: { finishedAt: null as string | null } },
    );
    rerender({ finishedAt: 't0' });
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it('invalidates all given keys when finished_at changes after the baseline', () => {
    const { invalidateSpy, wrapper } = setup();
    const { rerender } = renderHook(
      ({ finishedAt }) => useSyncStatusInvalidation(finishedAt, [['country-performance'], ['country-perf-configs']]),
      { wrapper, initialProps: { finishedAt: null as string | null } },
    );
    rerender({ finishedAt: 't0' }); // baseline
    rerender({ finishedAt: 't1' }); // real change

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['country-performance'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['country-perf-configs'] });
  });

  it('does not re-invalidate when finished_at is unchanged across renders', () => {
    const { invalidateSpy, wrapper } = setup();
    const { rerender } = renderHook(
      ({ finishedAt }) => useSyncStatusInvalidation(finishedAt, [['country-performance']]),
      { wrapper, initialProps: { finishedAt: null as string | null } },
    );
    rerender({ finishedAt: 't0' });
    rerender({ finishedAt: 't1' });
    invalidateSpy.mockClear();
    rerender({ finishedAt: 't1' });
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it('does not re-invalidate when the effect re-runs (queryKeys changed) but finished_at is genuinely the same as last seen', () => {
    // Same finishedAt across renders 2→3 means the effect wouldn't normally re-run at all
    // (unchanged deps) — changing queryKeys forces a real re-execution so this actually
    // exercises the `finished !== lastSyncRef.current` FALSE branch, not just "effect skipped".
    const { invalidateSpy, wrapper } = setup();
    const { rerender } = renderHook(
      ({ finishedAt, keys }) => useSyncStatusInvalidation(finishedAt, keys),
      { wrapper, initialProps: { finishedAt: null as string | null, keys: [['a']] } },
    );
    rerender({ finishedAt: 't0', keys: [['a']] }); // baseline
    invalidateSpy.mockClear();
    rerender({ finishedAt: 't0', keys: [['b']] }); // deps changed, finishedAt unchanged
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it('is a no-op when finishedAt is null or undefined', () => {
    const { invalidateSpy, wrapper } = setup();
    const { rerender } = renderHook(
      ({ finishedAt }) => useSyncStatusInvalidation(finishedAt, [['country-performance']]),
      { wrapper, initialProps: { finishedAt: undefined as string | null | undefined } },
    );
    rerender({ finishedAt: null });
    rerender({ finishedAt: undefined });
    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});
