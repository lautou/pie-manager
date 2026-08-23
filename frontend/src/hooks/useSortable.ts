// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useMemo } from 'react';

type SortDir = 'asc' | 'desc';

interface SortableOptions<T> {
  data: T[];
  defaultCol: keyof T;
  defaultDir?: SortDir;
  getValue?: (item: T, col: keyof T) => string | number;
}

interface SortableResult<T, K extends keyof T> {
  sorted: T[];
  sortCol: K;
  sortDir: SortDir;
  toggle: (col: K) => void;
  indicator: (col: K) => string;
  thStyle: (col: K) => React.CSSProperties;
}

export function useSortable<T, K extends keyof T = keyof T>({
  data,
  defaultCol,
  defaultDir = 'asc',
  getValue,
}: SortableOptions<T>): SortableResult<T, K> {
  const [sortCol, setSortCol] = useState<K>(defaultCol as K);
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir);

  const toggle = (col: K) => {
    if ((col as unknown) === sortCol) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
  };

  const sorted = useMemo(() => {
    return [...data].sort((a, b) => {
      const va = getValue ? getValue(a, sortCol as keyof T) : (a[sortCol as keyof T] as unknown as string | number);
      const vb = getValue ? getValue(b, sortCol as keyof T) : (b[sortCol as keyof T] as unknown as string | number);
      const cmp = typeof va === 'string' && typeof vb === 'string'
        ? va.localeCompare(vb, 'fr')
        : (va as number) - (vb as number);
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [data, sortCol, sortDir, getValue]);

  const indicator = (col: K) =>
    (col as unknown) === sortCol ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ' ⇅';

  const thStyle = (col: K): React.CSSProperties => ({
    padding: '6px 8px',
    textAlign: 'left',
    borderBottom: '1px solid #ddd',
    fontSize: '0.85rem',
    color: (col as unknown) === sortCol ? '#0066CC' : '#6A6E73',
    cursor: 'pointer',
    userSelect: 'none',
    whiteSpace: 'nowrap',
  });

  return { sorted, sortCol, sortDir, toggle, indicator, thStyle };
}
