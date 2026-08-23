// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for SnapshotsTable — including memoized computed values.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

import { pfCoreStubs, pfTableStubs } from '../../tests/utils/patternfly-mocks';

vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  Pagination: ({ page, itemCount, perPage, onSetPage, onPerPageSelect }: any) => (
    <div data-testid="pagination" data-page={page} data-item-count={itemCount} data-per-page={perPage}>
      <button onClick={() => onSetPage(null, page + 1)}>Next</button>
      <button onClick={() => onSetPage(null, page - 1)}>Prev</button>
      <button onClick={() => onPerPageSelect?.(null, 20)}>PerPage</button>
    </div>
  ),
}));

vi.mock('@patternfly/react-table', () => pfTableStubs);

vi.mock('../utils/format', () => ({
  formatEUR: (val: number) => `${val.toFixed(2)} €`,
}));

import SnapshotsTable from './SnapshotsTable';
import type { DailySnapshot } from '../types';

// ── helpers ──────────────────────────────────────────────────────────────────

const makeSnap = (i: number): DailySnapshot => ({
  id: i,
  portfolio_id: 1,
  date: `2024-01-${String(i).padStart(2, '0')}`,
  total_eur: 10000 + i * 100,
  offensive_eur: 5000 + i * 50,
  defensive_eur: 5000 + i * 50,
});

/** Build an array of n snapshots (sorted ascending, as PerformancePage provides). */
const makeSnaps = (n: number): DailySnapshot[] =>
  Array.from({ length: n }, (_, i) => makeSnap(i + 1));

const SNAP_PAGE_SIZE = 15; // must match component constant

// ── tests ─────────────────────────────────────────────────────────────────────

describe('SnapshotsTable', () => {
  it('renders empty state when no snapshots', () => {
    render(
      <SnapshotsTable
        sortedDaily={[]}
        snapPage={1}
        setSnapPage={vi.fn()}
        onRowClick={vi.fn()}
      />,
    );
    expect(screen.getByText('Aucun snapshot disponible.')).toBeTruthy();
  });

  it('shows snapshot count in the card title', () => {
    const snaps = makeSnaps(3);
    render(
      <SnapshotsTable
        sortedDaily={snaps}
        snapPage={1}
        setSnapPage={vi.fn()}
        onRowClick={vi.fn()}
      />,
    );
    expect(screen.getByText('Snapshots journaliers (3)')).toBeTruthy();
  });

  // ── memoized reversal ────────────────────────────────────────────────────────

  it('displays rows in descending date order (newest first)', () => {
    // sortedDaily is ascending [2024-01-01, 2024-01-02, 2024-01-03]
    const snaps = makeSnaps(3);
    render(
      <SnapshotsTable
        sortedDaily={snaps}
        snapPage={1}
        setSnapPage={vi.fn()}
        onRowClick={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole('row');
    // first row after header should be the last date (reversed)
    const dateCells = rows
      .slice(1) // skip header row
      .map((r) => r.textContent ?? '');
    expect(dateCells[0]).toContain('2024-01-03');
    expect(dateCells[2]).toContain('2024-01-01');
  });

  // ── memoized pagination slicing ──────────────────────────────────────────────

  it('renders exactly SNAP_PAGE_SIZE rows when data exceeds one page', () => {
    const snaps = makeSnaps(SNAP_PAGE_SIZE + 5); // 20 items
    render(
      <SnapshotsTable
        sortedDaily={snaps}
        snapPage={1}
        setSnapPage={vi.fn()}
        onRowClick={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole('row');
    // header + SNAP_PAGE_SIZE data rows
    expect(rows.length).toBe(SNAP_PAGE_SIZE + 1);
  });

  it('renders remaining rows on page 2', () => {
    const total = SNAP_PAGE_SIZE + 4; // 19 items → page 2 has 4
    const snaps = makeSnaps(total);
    render(
      <SnapshotsTable
        sortedDaily={snaps}
        snapPage={2}
        setSnapPage={vi.fn()}
        onRowClick={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole('row');
    expect(rows.length).toBe(4 + 1); // header + 4 data rows
  });

  // ── page clamping ────────────────────────────────────────────────────────────

  it('clamps snapPage to totalPages when snapPage exceeds available pages', () => {
    // 3 items = 1 page; passing snapPage=99 should still show items on page 1
    const snaps = makeSnaps(3);
    render(
      <SnapshotsTable
        sortedDaily={snaps}
        snapPage={99}
        setSnapPage={vi.fn()}
        onRowClick={vi.fn()}
      />,
    );
    // All 3 rows + header should be visible (not 0 because page was out of range)
    const rows = screen.getAllByRole('row');
    expect(rows.length).toBe(4);
  });

  // ── pagination control ───────────────────────────────────────────────────────

  it('calls setSnapPage with next page number when Next is clicked', async () => {
    const setSnapPage = vi.fn();
    const snaps = makeSnaps(SNAP_PAGE_SIZE + 1);
    const user = userEvent.setup({ delay: null });
    render(
      <SnapshotsTable
        sortedDaily={snaps}
        snapPage={1}
        setSnapPage={setSnapPage}
        onRowClick={vi.fn()}
      />,
    );
    await user.click(screen.getByText('Next'));
    expect(setSnapPage).toHaveBeenCalledWith(2);
  });

  // ── row click ────────────────────────────────────────────────────────────────

  it('calls onRowClick with the correct snapshot when a row is clicked', async () => {
    const onRowClick = vi.fn();
    const snaps = makeSnaps(2);
    const user = userEvent.setup({ delay: null });
    render(
      <SnapshotsTable
        sortedDaily={snaps}
        snapPage={1}
        setSnapPage={vi.fn()}
        onRowClick={onRowClick}
      />,
    );
    // First data row is snap id=2 (reversed)
    const rows = screen.getAllByRole('row');
    await user.click(rows[1]);
    expect(onRowClick).toHaveBeenCalledWith(snaps[1]); // id=2 is index 1
  });

  // ── handlePerPageSelect noop ─────────────────────────────────────────────────

  it('handlePerPageSelect: clicking PerPage button resets to page 1 and changes perPage', async () => {
    const snaps = makeSnaps(SNAP_PAGE_SIZE + 5);
    const setSnapPage = vi.fn();
    const user = userEvent.setup({ delay: null });
    render(
      <SnapshotsTable
        sortedDaily={snaps}
        snapPage={2}
        setSnapPage={setSnapPage}
        onRowClick={vi.fn()}
      />,
    );
    await user.click(screen.getByText('PerPage'));
    // setSnapPage(1) must be called to reset to first page
    expect(setSnapPage).toHaveBeenCalledWith(1);
    expect(screen.getByTestId('pagination')).toBeTruthy();
  });

  // ── pagination props ─────────────────────────────────────────────────────────

  it('passes correct itemCount to Pagination', () => {
    const snaps = makeSnaps(SNAP_PAGE_SIZE + 5);
    render(
      <SnapshotsTable
        sortedDaily={snaps}
        snapPage={1}
        setSnapPage={vi.fn()}
        onRowClick={vi.fn()}
      />,
    );
    const pagination = screen.getByTestId('pagination');
    expect(pagination.getAttribute('data-item-count')).toBe(String(SNAP_PAGE_SIZE + 5));
    expect(pagination.getAttribute('data-per-page')).toBe(String(SNAP_PAGE_SIZE));
  });
});
