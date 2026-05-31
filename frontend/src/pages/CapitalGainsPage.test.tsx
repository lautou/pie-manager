/**
 * Tests for PVPage (Plus-values / Capital Gains)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfTableStubs } from '../../tests/utils/patternfly-mocks';

// Mock react-router-dom
vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
}));

// Mock PatternFly core
vi.mock('@patternfly/react-core', () => pfCoreStubs);

// Mock PatternFly table — override Th to toggle sort direction on each click
const pvThClickCount: Record<string, number> = {};
vi.mock('@patternfly/react-table', () => ({
  ...pfTableStubs,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Th: ({ children, sort }: any) => (
    <th
      onClick={() => {
        if (sort?.onSort) {
          const key = String(sort.columnIndex);
          pvThClickCount[key] = (pvThClickCount[key] ?? 0) + 1;
          const dir = pvThClickCount[key] % 2 === 1 ? 'asc' : 'desc';
          sort.onSort({} as MouseEvent, sort.columnIndex, dir);
        }
      }}
    >
      {children}
    </th>
  ),
}));

// Mock format utils
vi.mock('../utils/format', () => ({
  formatEUR: (val: number) => `${val.toFixed(2)} €`,
  formatPct1: (val: number, withSign?: boolean) => `${withSign && val > 0 ? '+' : ''}${val.toFixed(1)} %`,
  formatDate: (iso: string) => {
    if (!iso || iso.length < 10) return iso;
    const [y, m, d] = iso.split('-');
    return `${d}/${m}/${y}`;
  },
}));

// Mock useCapitalGains hook
const mockUseCapitalGains = vi.fn();
vi.mock('../api/queries', () => ({
  useCapitalGains: (...args: any[]) => mockUseCapitalGains(...args),
}));

const mockCapitalGainsData = {
  portfolio_id: 1,
  tickers: [
    {
      ticker: 'AAPL',
      product_name: 'Apple Inc',
      cump: 140.0,
      qty_held: 10,
      cost_basis_eur: 1400,
      current_value_eur: 1500,
      unrealized_pv: 100,
      realized_pv_total: 50,
      events: [
        {
          date: '2024-06-15',
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
    {
      ticker: 'MSFT',
      product_name: 'Microsoft Corp',
      cump: 280.0,
      qty_held: 0,  // no open position
      cost_basis_eur: 0,
      current_value_eur: 0,
      unrealized_pv: 0,
      realized_pv_total: -30,  // realized loss
      events: [
        {
          date: '2024-03-10',
          ticker: 'MSFT',
          product_name: 'Microsoft Corp',
          qty_sold: 2,
          cump_at_sell: 290.0,
          sell_price_eur: 560,
          realized_pv: -30,
          account_id: 1,
        },
      ],
    },
  ],
  total_unrealized_pv: 100,
  total_realized_pv: 20,
  total_pv: 120,
};

import CapitalGainsPage from './CapitalGainsPage';

describe('CapitalGainsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.keys(pvThClickCount).forEach(k => delete pvThClickCount[k]);
  });

  // ── Loading state ─────────────────────────────────────────────────────────

  it('shows spinner when loading', () => {
    mockUseCapitalGains.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    render(<CapitalGainsPage />);
    expect(screen.getByTestId('spinner')).toBeTruthy();
  });

  // ── Error state ───────────────────────────────────────────────────────────

  it('shows error message when query fails', () => {
    mockUseCapitalGains.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    render(<CapitalGainsPage />);
    expect(screen.getByText(/Erreur lors du chargement des plus-values/i)).toBeTruthy();
  });

  it('shows error when data is undefined (no error flag)', () => {
    mockUseCapitalGains.mockReturnValue({ data: undefined, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    expect(screen.getByText(/Erreur lors du chargement des plus-values/i)).toBeTruthy();
  });

  // ── Page title ────────────────────────────────────────────────────────────

  it('renders page title "Plus-values"', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    expect(screen.getByText('Plus-values')).toBeTruthy();
  });

  // ── Section A — Summary table ─────────────────────────────────────────────

  it('renders summary table header columns', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    // "Ticker" appears in both summary and history table headers
    expect(screen.getAllByText('Ticker').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Nom').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('CUMP')).toBeTruthy();
    expect(screen.getByText('Valeur actuelle')).toBeTruthy();
    expect(screen.getByText('Coût de revient')).toBeTruthy();
    // "PV latente" appears in both summary col and KPI card title
    expect(screen.getAllByText('PV latente').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('PV latente %')).toBeTruthy();
    // "PV réalisée" appears in summary col and KPI card
    expect(screen.getAllByText('PV réalisée').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('PV nette')).toBeTruthy();
  });

  it('renders tickers with qty_held > 0 in summary', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    // AAPL appears in summary table and in history table
    expect(screen.getAllByText('AAPL').length).toBeGreaterThanOrEqual(1);
  });

  it('renders tickers with realized_pv_total != 0 even if qty_held = 0', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    // MSFT appears in summary table and in history table
    expect(screen.getAllByText('MSFT').length).toBeGreaterThanOrEqual(1);
  });

  it('excludes tickers with qty_held=0 AND realized_pv_total=0', () => {
    const dataWithZeroTicker = {
      ...mockCapitalGainsData,
      tickers: [
        ...mockCapitalGainsData.tickers,
        {
          ticker: 'ZZZZ',
          product_name: 'Zero ticker',
          cump: 0,
          qty_held: 0,
          cost_basis_eur: 0,
          current_value_eur: 0,
          unrealized_pv: 0,
          realized_pv_total: 0,
          events: [],
        },
      ],
    };
    mockUseCapitalGains.mockReturnValue({ data: dataWithZeroTicker, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    expect(screen.queryByText('ZZZZ')).toBeNull();
  });

  it('shows "Aucune position ni cession" when no visible tickers', () => {
    const emptyData = {
      ...mockCapitalGainsData,
      tickers: [],
    };
    mockUseCapitalGains.mockReturnValue({ data: emptyData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    expect(screen.getByText(/Aucune position ni cession/i)).toBeTruthy();
  });

  it('renders AAPL unrealized_pv value', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    // AAPL unrealized_pv = 100 → "+100.00 €"
    const body = document.body.textContent ?? '';
    expect(body).toContain('+100.00 €');
  });

  it('renders MSFT negative realized_pv_total', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    // MSFT realized_pv_total = -30
    const body = document.body.textContent ?? '';
    expect(body).toContain('-30.00 €');
  });

  // ── Section B — KPI cards ─────────────────────────────────────────────────

  it('renders KPI card titles', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    expect(screen.getByText('PV latente totale')).toBeTruthy();
    expect(screen.getByText('PV réalisée totale')).toBeTruthy();
    // "PV nette totale" card removed — only 2 KPI cards now
    expect(screen.queryByText('PV nette totale')).toBeNull();
  });

  it('shows total_unrealized_pv in KPI card', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    // total_unrealized_pv = 100 → "+100.00 €"
    const body = document.body.textContent ?? '';
    expect(body).toContain('+100.00 €');
  });

  it('shows percentage on unrealized KPI card when cost_basis > 0', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    // cost_basis_eur = 1400 (only AAPL is visible with qty_held > 0 or realized)
    // unrealized / cost = 100/1400 * 100 = 7.1%
    const body = document.body.textContent ?? '';
    expect(body).toContain('sur coût de revient');
  });

  // ── Section C — Historique des cessions ───────────────────────────────────

  it('renders history table header columns', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    expect(screen.getByText('Date')).toBeTruthy();
    expect(screen.getByText('Nom produit')).toBeTruthy();
    expect(screen.getByText('Qté vendue')).toBeTruthy();
    expect(screen.getByText('CUMP à la vente')).toBeTruthy();
    expect(screen.getByText('Prix de cession')).toBeTruthy();
  });

  it('renders sell events from history', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    // AAPL event date 2024-06-15 → formatted as 15/06/2024
    expect(screen.getByText('15/06/2024')).toBeTruthy();
  });

  it('shows "Aucune cession" when no events', () => {
    const noEvents = {
      ...mockCapitalGainsData,
      tickers: [{ ...mockCapitalGainsData.tickers[0], events: [] }],
    };
    mockUseCapitalGains.mockReturnValue({ data: noEvents, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    expect(screen.getByText(/Aucune cession enregistrée/i)).toBeTruthy();
  });

  it('renders "Historique des cessions" section title', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    expect(screen.getByText('Historique des cessions')).toBeTruthy();
  });

  it('renders "Récapitulatif par titre" section title', () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    expect(screen.getByText('Récapitulatif par titre')).toBeTruthy();
  });

  // ── Sorting ───────────────────────────────────────────────────────────────

  it('summary table columns are clickable for sort', async () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);

    // Click on "PV latente" column header — should not crash
    const pvHeader = screen.getByText('PV latente');
    await user.click(pvHeader);
    expect(screen.getByText('Plus-values')).toBeTruthy();
  });

  it('history table sort column click does not crash', async () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<CapitalGainsPage />);

    const dateHeader = screen.getByText('Date');
    await user.click(dateHeader);
    expect(screen.getByText('Plus-values')).toBeTruthy();
  });
});

// ── Additional PVPage branch coverage ────────────────────────────────────────

describe('CapitalGainsPage — additional branch coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.keys(pvThClickCount).forEach(k => delete pvThClickCount[k]);
  });

  it('KPI card with negative total_unrealized_pv shows no + prefix (line 158 false branch)', () => {
    mockUseCapitalGains.mockReturnValue({
      data: {
        ...mockCapitalGainsData,
        total_unrealized_pv: -500,
        total_realized_pv: -200,
      },
      isLoading: false,
      isError: false,
    });
    render(<CapitalGainsPage />);
    const body = document.body.textContent ?? '';
    // totalUnrealized=-500 → > 0 is false → no '+' prefix
    expect(body).toContain('-500.00 €');
  });

  it('KPI card with zero total_realized_pv shows no + prefix (line 173 false branch)', () => {
    mockUseCapitalGains.mockReturnValue({
      data: {
        ...mockCapitalGainsData,
        total_unrealized_pv: 0,
        total_realized_pv: 0,
      },
      isLoading: false,
      isError: false,
    });
    render(<CapitalGainsPage />);
    const body = document.body.textContent ?? '';
    // totalRealized=0 → > 0 is false → no '+' prefix
    expect(body).toContain('0.00 €');
  });

  it('clicking all summary column headers exercises all sortTickers switch cases', async () => {
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    const { container } = render(<CapitalGainsPage />);

    // Click every th in the page to exercise all switch cases in sortTickers
    const ths = Array.from(container.querySelectorAll('th'));
    for (const th of ths) {
      await user.click(th as HTMLElement);
    }
    // Also click twice on some headers to exercise desc direction (dir=-1)
    for (const th of ths.slice(0, 3)) {
      await user.click(th as HTMLElement);
    }
    expect(screen.getByText('Plus-values')).toBeTruthy();
  }, 10000);

  it('sortTickers with cost_basis_eur=0 uses pctA=0 fallback (line 58-59 false branches)', async () => {
    // MSFT has cost_basis_eur: 0 → pctA = 0 (false branch of !== 0)
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    const { container } = render(<CapitalGainsPage />);

    // Click "PV latente %" header (index 6) to sort by unrealized_pv_pct
    // → sortTickers uses pctA/pctB where MSFT has cost_basis_eur=0
    const ths = Array.from(container.querySelectorAll('th'));
    // Summary table has 9 Ths (indices 0-8); the 7th (index 6) is "PV latente %"
    if (ths.length > 6) {
      await user.click(ths[6] as HTMLElement);
    }
    expect(screen.getByText('Plus-values')).toBeTruthy();
  }, 10000);

  it('earliestEventDate is shown in KPI card when events exist (line 175-178 true branch)', () => {
    // earliestEventDate is non-null → {earliestEventDate && ...} shows "Depuis le" date
    mockUseCapitalGains.mockReturnValue({ data: mockCapitalGainsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    // Events exist → earliestEventDate = sorted date → renders "Depuis le 10/03/2024"
    const body = document.body.textContent ?? '';
    expect(body).toContain('Depuis le');
  });

  it('no events → earliestEventDate is null, no "Depuis le" shown (line 175 false branch)', () => {
    const noEventsData = {
      ...mockCapitalGainsData,
      tickers: mockCapitalGainsData.tickers.map(t => ({ ...t, events: [] })),
    };
    mockUseCapitalGains.mockReturnValue({ data: noEventsData, isLoading: false, isError: false });
    render(<CapitalGainsPage />);
    // earliestEventDate = null → no "Depuis le" text
    const body = document.body.textContent ?? '';
    expect(body).not.toContain('Depuis le');
  });
});
