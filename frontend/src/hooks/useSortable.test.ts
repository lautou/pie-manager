// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for useSortable hook (lines 31-35 — toggle function branches).
 */
import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSortable } from './useSortable';

const DATA = [
  { name: 'Zebra', value: 10 },
  { name: 'Apple', value: 30 },
  { name: 'Mango', value: 20 },
];

describe('useSortable', () => {
  it('sorts by defaultCol ascending initially', () => {
    const { result } = renderHook(() =>
      useSortable({ data: DATA, defaultCol: 'name' })
    );
    expect(result.current.sorted[0].name).toBe('Apple');
    expect(result.current.sorted[2].name).toBe('Zebra');
  });

  it('toggle: clicking same column switches direction (lines 31-32 — same col branch)', () => {
    const { result } = renderHook(() =>
      useSortable({ data: DATA, defaultCol: 'name' })
    );

    // Initially asc
    expect(result.current.sortDir).toBe('asc');
    expect(result.current.sorted[0].name).toBe('Apple');

    // Toggle same column → desc (lines 31-32)
    act(() => {
      result.current.toggle('name' as any);
    });

    expect(result.current.sortDir).toBe('desc');
    expect(result.current.sorted[0].name).toBe('Zebra');
  });

  it('toggle: clicking different column sets new column asc (lines 33-35 — new col branch)', () => {
    const { result } = renderHook(() =>
      useSortable({ data: DATA, defaultCol: 'name' })
    );

    // Initially sorted by name asc
    expect(result.current.sortCol).toBe('name');

    // Toggle to value column (different col — lines 33-35)
    act(() => {
      result.current.toggle('value' as any);
    });

    expect(result.current.sortCol).toBe('value');
    expect(result.current.sortDir).toBe('asc');
    // Sorted by value ascending: 10, 20, 30
    expect(result.current.sorted[0].name).toBe('Zebra');
    expect(result.current.sorted[2].name).toBe('Apple');
  });

  it('toggle same column twice returns to asc', () => {
    const { result } = renderHook(() =>
      useSortable({ data: DATA, defaultCol: 'name' })
    );

    act(() => { result.current.toggle('name' as any); }); // → desc
    act(() => { result.current.toggle('name' as any); }); // → asc again

    expect(result.current.sortDir).toBe('asc');
    expect(result.current.sorted[0].name).toBe('Apple');
  });

  it('indicator returns ▲ for current col asc, ▼ for desc, ⇅ for other', () => {
    const { result } = renderHook(() =>
      useSortable({ data: DATA, defaultCol: 'name' })
    );

    expect(result.current.indicator('name' as any)).toBe(' ▲');

    act(() => { result.current.toggle('name' as any); }); // → desc
    expect(result.current.indicator('name' as any)).toBe(' ▼');
    expect(result.current.indicator('value' as any)).toBe(' ⇅');
  });

  it('thStyle returns blue for current col, grey for other', () => {
    const { result } = renderHook(() =>
      useSortable({ data: DATA, defaultCol: 'name' })
    );

    const currentStyle = result.current.thStyle('name' as any);
    const otherStyle = result.current.thStyle('value' as any);

    expect(currentStyle.color).toBe('#0066CC');
    expect(otherStyle.color).toBe('#6A6E73');
  });

  it('uses getValue function when provided', () => {
    const { result } = renderHook(() =>
      useSortable({
        data: DATA,
        defaultCol: 'value',
        getValue: (item, col) => item[col as keyof typeof item] as number,
      })
    );

    // Should sort numerically by value ascending: 10, 20, 30
    expect(result.current.sorted[0].value).toBe(10);
    expect(result.current.sorted[2].value).toBe(30);
  });

  it('defaultDir desc sorts descending initially', () => {
    const { result } = renderHook(() =>
      useSortable({ data: DATA, defaultCol: 'name', defaultDir: 'desc' })
    );

    expect(result.current.sorted[0].name).toBe('Zebra');
    expect(result.current.sorted[2].name).toBe('Apple');
  });
});
