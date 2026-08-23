// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, it, expect } from 'vitest';
import { clampZoomRange, timeAxisStyle } from './chartZoom';

describe('clampZoomRange', () => {
  it('widens a range narrower than the minimum, centered on the original midpoint', () => {
    const start = new Date('2020-01-01T00:00:00Z');
    const end = new Date('2020-01-02T00:00:00Z'); // 1 day
    const minMs = 10 * 86_400_000; // 10 days
    const [s, e] = clampZoomRange([start, end], minMs);
    expect(e.getTime() - s.getTime()).toBe(minMs);
    const center = (s.getTime() + e.getTime()) / 2;
    expect(center).toBe((start.getTime() + end.getTime()) / 2);
  });

  it('leaves a range at or above the minimum untouched', () => {
    const start = new Date('2020-01-01T00:00:00Z');
    const end = new Date('2020-06-01T00:00:00Z');
    const [s, e] = clampZoomRange([start, end], 10 * 86_400_000);
    expect(s).toBe(start);
    expect(e).toBe(end);
  });
});

describe('timeAxisStyle', () => {
  it('uses year-month format and tickCount/fixLabelOverlap when unzoomed (Infinity zoomDays)', () => {
    const style = timeAxisStyle(undefined);
    expect(style.tickCount).toBe(16);
    expect(style.fixLabelOverlap).toBe(true);
    expect(style.tickFormat(new Date('2020-03-15'))).toBe('2020-03');
  });

  it('uses year-month format for a zoom span of 1-3 years (no year-only duplicates)', () => {
    const zoomDomain: [Date, Date] = [new Date('2020-01-01'), new Date('2022-01-01')];
    const style = timeAxisStyle(zoomDomain);
    expect(style.tickFormat(new Date('2020-06-01'))).toBe('2020-06');
    expect(style.tickFormat(new Date('2021-06-01'))).toBe('2021-06');
  });

  it('switches to full day-level format when zoomed to less than 90 days', () => {
    const zoomDomain: [Date, Date] = [new Date('2020-01-01'), new Date('2020-01-20')];
    const style = timeAxisStyle(zoomDomain);
    expect(style.tickFormat(new Date('2020-01-05'))).toBe('2020-01-05');
  });

  it('accepts a raw timestamp (not a Date instance) in tickFormat', () => {
    const style = timeAxisStyle(undefined);
    expect(style.tickFormat(new Date('2020-03-15').getTime() as unknown as Date)).toBe('2020-03');
  });

  it('applies angled, right-anchored tick label style and a light grid', () => {
    const style = timeAxisStyle(undefined);
    expect(style.style.tickLabels).toEqual({ fontSize: 10, angle: -45, textAnchor: 'end' });
    expect(style.style.grid).toEqual({ stroke: '#d4d4d4', strokeWidth: 0.5 });
  });
});
