// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import type { SortByDirection } from '@patternfly/react-table';
import { useColumnSort, useSortState, applyColumnSort } from './useColumnSort';

interface Row { name: string; value: number }

const DATA: Row[] = [
  { name: 'Zebra', value: 10 },
  { name: 'Apple', value: 30 },
  { name: 'Mango', value: 20 },
];

const compare = (a: Row, b: Row, index: number): number => {
  switch (index) {
    case 0: return a.name.localeCompare(b.name);
    case 1: return a.value - b.value;
    default: return 0;
  }
};

describe('useColumnSort', () => {
  it('sorts by defaultIndex ascending initially', () => {
    const { result } = renderHook(() => useColumnSort(DATA, compare, 0));
    expect(result.current.sorted.map((r) => r.name)).toEqual(['Apple', 'Mango', 'Zebra']);
    expect(result.current.sortBy).toEqual({ index: 0, direction: 'asc' });
  });

  it('honors an explicit defaultDir', () => {
    const { result } = renderHook(() => useColumnSort(DATA, compare, 0, 'desc'));
    expect(result.current.sorted.map((r) => r.name)).toEqual(['Zebra', 'Mango', 'Apple']);
    expect(result.current.sortBy).toEqual({ index: 0, direction: 'desc' });
  });

  it('onSort switches column and direction', () => {
    const { result } = renderHook(() => useColumnSort(DATA, compare, 0));

    act(() => {
      result.current.onSort({} as React.MouseEvent, 1, 'desc' as SortByDirection);
    });

    expect(result.current.sortBy).toEqual({ index: 1, direction: 'desc' });
    expect(result.current.sorted.map((r) => r.value)).toEqual([30, 20, 10]);
  });
});

describe('useSortState + applyColumnSort', () => {
  it('one shared sort state can drive several independently-sorted arrays', () => {
    const other: Row[] = [{ name: 'Banana', value: 5 }, { name: 'Cherry', value: 1 }];
    const { result } = renderHook(() => useSortState(1));

    expect(applyColumnSort(DATA, compare, result.current.sortIndex, result.current.sortDir)
      .map((r) => r.value)).toEqual([10, 20, 30]);
    expect(applyColumnSort(other, compare, result.current.sortIndex, result.current.sortDir)
      .map((r) => r.value)).toEqual([1, 5]);

    act(() => {
      result.current.onSort({} as React.MouseEvent, 1, 'desc' as SortByDirection);
    });

    expect(applyColumnSort(other, compare, result.current.sortIndex, result.current.sortDir)
      .map((r) => r.value)).toEqual([5, 1]);
  });
});
