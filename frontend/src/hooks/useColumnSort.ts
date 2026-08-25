// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import type { SortByDirection } from '@patternfly/react-table';

export type SortDir = 'asc' | 'desc';

export type ColumnCompare<T> = (a: T, b: T, index: number) => number;

interface SortState {
  sortIndex: number;
  sortDir: SortDir;
  sortBy: { index: number; direction: SortByDirection };
  onSort: (event: React.MouseEvent, index: number, direction: SortByDirection) => void;
}

interface ColumnSortResult<T> extends SortState {
  sorted: T[];
}

/**
 * PatternFly `Th sort={{ sortBy, onSort, columnIndex }}` index/direction state, plus the
 * toggle-on-click handler — split out from useColumnSort below for the rare case where one
 * sort state drives several independently-rendered tables (e.g. AccountsSummaryPage's shared
 * per-account detail sort), which each then call applyColumnSort themselves.
 */
export function useSortState(defaultIndex: number, defaultDir: SortDir = 'asc'): SortState {
  const [sortIndex, setSortIndex] = useState(defaultIndex);
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir);

  const onSort = (_: React.MouseEvent, index: number, direction: SortByDirection) => {
    setSortIndex(index);
    setSortDir(direction as SortDir);
  };

  return { sortIndex, sortDir, sortBy: { index: sortIndex, direction: sortDir as SortByDirection }, onSort };
}

/** Applies a column-indexed, ascending-oriented `compare` plus a sort direction to `data`. */
export function applyColumnSort<T>(
  data: T[], compare: ColumnCompare<T>, sortIndex: number, sortDir: SortDir,
): T[] {
  const sign = sortDir === 'asc' ? 1 : -1;
  return [...data].sort((a, b) => compare(a, b, sortIndex) * sign);
}

/**
 * The common case: one table, one sort state. `compare` returns an ascending-oriented
 * comparison for the given column index; this hook owns everything else (as opposed to
 * useSortable's key-based sort for simple single-key tables).
 */
export function useColumnSort<T>(
  data: T[], compare: ColumnCompare<T>, defaultIndex: number, defaultDir: SortDir = 'asc',
): ColumnSortResult<T> {
  const state = useSortState(defaultIndex, defaultDir);
  return { ...state, sorted: applyColumnSort(data, compare, state.sortIndex, state.sortDir) };
}
