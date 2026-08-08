import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';

/**
 * Invalidates the given query keys as soon as a background sync's `finished_at`
 * timestamp genuinely changes — skipping the first observed value on mount, so a page
 * load doesn't trigger an unnecessary refetch right after data was already fetched fresh.
 *
 * Extracted from IndicatorsPage.tsx's original inline effect (used there for the
 * growth/inflation sync, now also used for the country-performance sync).
 */
export function useSyncStatusInvalidation(
  finishedAt: string | null | undefined, queryKeys: string[][],
): void {
  const qc = useQueryClient();
  const lastSyncRef = useRef<string | null>(null);

  useEffect(() => {
    const finished = finishedAt ?? null;
    if (finished === null) return;
    if (lastSyncRef.current === null) {
      lastSyncRef.current = finished;
      return;
    }
    if (finished !== lastSyncRef.current) {
      lastSyncRef.current = finished;
      queryKeys.forEach((key) => qc.invalidateQueries({ queryKey: key }));
    }
  }, [qc, finishedAt, JSON.stringify(queryKeys)]);
}
