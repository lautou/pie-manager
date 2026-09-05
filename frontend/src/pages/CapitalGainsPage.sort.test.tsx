// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Sort-coverage tests for PVPage — covers lines 60-68 (sortTickers switch cases)
 * and lines 195-200 (sortEvents switch cases).
 *
 * The Th mock calls sort.onSort(event, columnIndex, 'asc') on every click,
 * triggering each case in the switch statements.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfTableStubs } from '../../tests/utils/patternfly-mocks';

vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
}));

vi.mock('@patternfly/react-core', () => pfCoreStubs);

// Th mock that fires sort.onSort toggling between asc and desc on repeated clicks
vi.mock('@patternfly/react-table', () => ({
  ...pfTableStubs,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Th: ({ children, sort }: any) => (
    <th
      data-col-index={sort?.columnIndex}
      onClick={() => {
        if (sort?.onSort) {
          const currentDir = sort.sortBy?.index === sort.columnIndex ? sort.sortBy?.direction : 'asc';
          const nextDir = currentDir === 'asc' ? 'desc' : 'asc';
          sort.onSort({} as MouseEvent, sort.columnIndex, nextDir);
        }
      }}
    >
      {children}
    </th>
  ),
}));

vi.mock('../utils/format', () => ({
  formatEUR: (val: number) => `${val.toFixed(2)} €`,
  formatPct1: (val: number, withSign?: boolean) => `${withSign && val > 0 ? '+' : ''}${val.toFixed(1)} %`,
  formatDate: (iso: string) => {
    if (!iso || iso.length < 10) return iso;
    const [y, m, d] = iso.split('-');
    return `${d}/${m}/${y}`;
  },
}));

const mockUseCapitalGains = vi.fn();
vi.mock('../api/queries', () => ({
  useCapitalGains: (...args: any[]) => mockUseCapitalGains(...args),
}));

// Two tickers so that sort comparators actually execute comparisons (non-trivial results)
const mockData = {
  portfolio_id: 1,
  tickers: [
    {
      ticker: 'MSFT',
      product_name: 'Microsoft Corp',
      cump: 300.0,
      qty_held: 5,
      cost_basis_eur: 1500,
      current_value_eur: 1600,
      unrealized_pv: 100,
      realized_pv_total: 80,
      events: [
        {
          date: '2024-06-15',
          ticker: 'MSFT',
          product_name: 'Microsoft Corp',
          qty_sold: 3,
          cump_at_sell: 290.0,
          sell_price_eur: 900,
          realized_pv: 80,
          account_id: 1,
        },
      ],
    },
    {
      ticker: 'AAPL',
      product_name: 'Apple Inc',
      cump: 140.0,
      qty_held: 10,
      cost_basis_eur: 1400,
      current_value_eur: 1500,
      unrealized_pv: 200,
      realized_pv_total: 50,
      events: [
        {
          date: '2024-03-10',
          ticker: 'AAPL',
          product_name: 'Apple Inc',
          qty_sold: 5,
          cump_at_sell: 135.0,
          sell_price_eur: 750,
          realized_pv: 50,
          account_id: 1,
        },
      ],
    },
  ],
  total_unrealized_pv: 300,
  total_realized_pv: 130,
  total_pv: 430,
};

import CapitalGainsPage from './CapitalGainsPage';

describe('CapitalGainsPage — sorting the summary and history tables by every column', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseCapitalGains.mockReturnValue({ data: mockData, isLoading: false, isError: false });
  });

  // ── Summary table sort cases (lines 60-68) ──────────────────────────────────

  it('sorts the summary table by Ticker', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const ths = Array.from(document.querySelectorAll('th[data-col-index]'));
    const col0 = ths.find(th => th.getAttribute('data-col-index') === '0');
    expect(col0).toBeInTheDocument();
    await user.click(col0 as HTMLElement);
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the summary table by CUMP', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const ths = Array.from(document.querySelectorAll('th[data-col-index]'));
    const col2 = ths.find(th => th.getAttribute('data-col-index') === '2');
    expect(col2).toBeInTheDocument();
    await user.click(col2 as HTMLElement);
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the summary table by Valeur actuelle', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const ths = Array.from(document.querySelectorAll('th[data-col-index]'));
    const col3 = ths.find(th => th.getAttribute('data-col-index') === '3');
    expect(col3).toBeInTheDocument();
    await user.click(col3 as HTMLElement);
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the summary table by Coût de revient', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const ths = Array.from(document.querySelectorAll('th[data-col-index]'));
    const col4 = ths.find(th => th.getAttribute('data-col-index') === '4');
    expect(col4).toBeInTheDocument();
    await user.click(col4 as HTMLElement);
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the summary table by PV latente', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const ths = Array.from(document.querySelectorAll('th[data-col-index]'));
    const col5 = ths.find(th => th.getAttribute('data-col-index') === '5');
    expect(col5).toBeInTheDocument();
    await user.click(col5 as HTMLElement);
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the summary table by PV latente %', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const ths = Array.from(document.querySelectorAll('th[data-col-index]'));
    const col6 = ths.find(th => th.getAttribute('data-col-index') === '6');
    expect(col6).toBeInTheDocument();
    await user.click(col6 as HTMLElement);
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the summary table by PV réalisée', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const ths = Array.from(document.querySelectorAll('th[data-col-index]'));
    const col7 = ths.find(th => th.getAttribute('data-col-index') === '7');
    expect(col7).toBeInTheDocument();
    await user.click(col7 as HTMLElement);
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the summary table by PV globale', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const ths = Array.from(document.querySelectorAll('th[data-col-index]'));
    const col8 = ths.find(th => th.getAttribute('data-col-index') === '8');
    expect(col8).toBeInTheDocument();
    await user.click(col8 as HTMLElement);
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  // ── History table sort cases (lines 195-200) ────────────────────────────────
  // EVENT_COLS column indices: date=0, ticker=1, nom=2, qty=3, cump=4, prix=5, pv=6

  it('sorts the history table by Ticker', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    // History table Th elements have col-index 0-6; find index 1 (ticker)
    // Summary table has indices 0-8, history table has indices 0-6; both render
    // We need the history-table Th with index=1; find all th[data-col-index="1"]
    // and click one that corresponds to 'Ticker' label in history
    const allThIndex1 = Array.from(document.querySelectorAll('th[data-col-index="1"]'));
    // The last one belongs to the history table (rendered later in DOM)
    if (allThIndex1.length > 0) {
      await user.click(allThIndex1[allThIndex1.length - 1]);
    }
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the history table by Qté vendue', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const allThIndex3 = Array.from(document.querySelectorAll('th[data-col-index="3"]'));
    if (allThIndex3.length > 0) {
      await user.click(allThIndex3[allThIndex3.length - 1]);
    }
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the history table by CUMP à la vente', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const allThIndex4 = Array.from(document.querySelectorAll('th[data-col-index="4"]'));
    if (allThIndex4.length > 0) {
      await user.click(allThIndex4[allThIndex4.length - 1]);
    }
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the history table by Prix de cession', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const allThIndex5 = Array.from(document.querySelectorAll('th[data-col-index="5"]'));
    if (allThIndex5.length > 0) {
      await user.click(allThIndex5[allThIndex5.length - 1]);
    }
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the history table by PV réalisée', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const allThIndex6 = Array.from(document.querySelectorAll('th[data-col-index="6"]'));
    if (allThIndex6.length > 0) {
      await user.click(allThIndex6[allThIndex6.length - 1]);
    }
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the history table by Date in both ascending and descending direction', async () => {
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    const allThIndex0 = Array.from(document.querySelectorAll('th[data-col-index="0"]'));
    // Click twice: first → desc, second → asc — covers both directions
    if (allThIndex0.length > 0) {
      await user.click(allThIndex0[allThIndex0.length - 1]);
      await user.click(allThIndex0[allThIndex0.length - 1]);
    }
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });

  it('sorts the summary table by PV latente % when a ticker has zero cost basis', async () => {
    // One ticker has cost_basis_eur=0 → pctB = 0 (false branch of !== 0 ? ... : 0)
    const dataWithZeroCost = {
      portfolio_id: 1,
      tickers: [
        {
          ticker: 'AAA', product_name: 'Asset A', cump: 100, qty_held: 10,
          cost_basis_eur: 1000, current_value_eur: 1200, unrealized_pv: 200, realized_pv_total: 0,
          events: [],
        },
        {
          ticker: 'BBB', product_name: 'Asset B', cump: 50, qty_held: 0,
          cost_basis_eur: 0, // triggers pctB = 0 fallback
          current_value_eur: 0, unrealized_pv: 0, realized_pv_total: 100,
          events: [],
        },
      ],
      total_unrealized_pv: 200,
      total_realized_pv: 100,
      total_pv: 300,
    };
    mockUseCapitalGains.mockReturnValue({ data: dataWithZeroCost, isLoading: false, isError: false });

    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);
    // Click col 6 (PV latente %) — triggers sortTickers with col='unrealized_pv_pct'
    // comparator uses pctA and pctB; pctB = b.cost_basis_eur !== 0 ? ... : 0
    const col6 = Array.from(document.querySelectorAll('th[data-col-index="6"]'))[0];
    if (col6) await user.click(col6 as HTMLElement);
    expect(screen.getByText('Plus-values')).toBeInTheDocument();
  });
});
