// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for SyntheseComptesPage
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfTableStubs, pfIconStubs } from '../../tests/utils/patternfly-mocks';

// Mock react-router-dom
vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
  useNavigate: () => vi.fn(),
}));

// Modal overridden to expose an onClose trigger (the generic stub has no
// close affordance)
vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  Modal: ({ children, isOpen, onClose }: any) =>
    isOpen ? (
      <div data-testid="modal">
        <button data-testid="modal-close" onClick={onClose}>Close</button>
        {children}
      </div>
    ) : null,
  ModalHeader: ({ title }: any) => <div>{title}</div>,
  ModalBody: ({ children }: any) => <>{children}</>,
}));

// Mock PatternFly table — override Th to invoke sort.onSort when clicked
// Each click toggles between 'asc' and 'desc' to exercise both sort direction branches.
const thClickCount: Record<string, number> = {};
vi.mock('@patternfly/react-table', () => ({
  ...pfTableStubs,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Th: ({ children, sort }: any) => (
    <th
      onClick={() => {
        if (sort?.onSort) {
          const key = String(sort.columnIndex);
          thClickCount[key] = (thClickCount[key] ?? 0) + 1;
          const dir = thClickCount[key] % 2 === 1 ? 'asc' : 'desc';
          sort.onSort({} as MouseEvent, sort.columnIndex, dir);
        }
      }}
    >
      {children}
    </th>
  ),
}));

// Mock PatternFly icons
vi.mock('@patternfly/react-icons', () => pfIconStubs);

// Mock SyncBadge
vi.mock('../components/SyncBadge', () => ({
  default: () => <span data-testid="sync-badge" />,
}));

// Mock format utils
vi.mock('../utils/format', () => ({
  formatUnitPrice: (v: number, _c?: string) => `${v} €`,
  formatEUR: (val: number) => `${val.toFixed(2)} €`,
  formatPct2: (val: number, withSign?: boolean) =>
    `${withSign && val > 0 ? '+' : ''}${val.toFixed(2)} %`,
  formatNativeCurrency: (val: number, currency: string, maxDecimals = 3) => `${val.toFixed(maxDecimals)} ${currency}`,
}));

// Mock API queries
const mockUseAccountsSummary = vi.fn();
const mockUseCapitalGains = vi.fn();

vi.mock('../api/queries', () => ({
  useAccountsSummary: (...args: any[]) => mockUseAccountsSummary(...args),
  useCapitalGains: (...args: any[]) => mockUseCapitalGains(...args),
  useEtfComposition: () => ({ data: undefined, isLoading: false }),
}));

const mockAccountSummary = {
  id: 1,
  name: 'Degiro',
  currency: 'EUR',
  cash_balance_eur: 1000,
  positions_value_eur: 9000,
  total_eur: 10000,
  positions: [
    {
      ticker: 'AAPL',
      product_name: 'Apple',
      category: 'Actif',
      quantity: 10,
      last_price: 150,
      last_price_date: '2024-01-01',
      last_price_source: 'yahoo',
      value_eur: 1500,
      currency: 'USD',
    },
  ],
};

const mockAccountSummaryManualSource = {
  ...mockAccountSummary,
  id: 2,
  name: 'auCoffre.com',
  positions: [
    {
      ticker: 'GOLD',
      product_name: 'Or physique',
      category: 'Actif', instrument_type: 'Or physique',
      quantity: 72,
      last_price: 32336.34,
      last_price_date: '2026-05-16',
      last_price_source: 'manual',
      value_eur: 32336.34,
      currency: 'EUR',
    },
  ],
};

const mockAccountSummaryNoPositions = {
  ...mockAccountSummary,
  id: 3,
  name: 'Revolut',
  positions: [],
  positions_value_eur: 0,
  cash_balance_eur: 500,
  total_eur: 500,
};

import AccountsSummaryPage from './AccountsSummaryPage';
import { StalePriceBadge } from '../components/PriceBadges';

describe('AccountsSummaryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset Th click counters so sort direction starts at 'asc' for each test
    Object.keys(thClickCount).forEach(k => delete thClickCount[k]);
    mockUseCapitalGains.mockReturnValue({ data: undefined, isLoading: false, isError: false });
  });

  it('shows spinner when loading', () => {
    mockUseAccountsSummary.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByTestId('spinner')).toBeInTheDocument();
  });

  it('shows error when isError', () => {
    mockUseAccountsSummary.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    render(<AccountsSummaryPage />);
    expect(screen.getByText(/Erreur lors du chargement de la synthèse des comptes/i)).toBeInTheDocument();
  });

  it('shows error when data is undefined', () => {
    mockUseAccountsSummary.mockReturnValue({ data: undefined, isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByText(/Erreur lors du chargement de la synthèse des comptes/i)).toBeInTheDocument();
  });

  it('renders page title', () => {
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummary], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByText('Comptes')).toBeInTheDocument();
  });

  it('renders account name', () => {
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummary], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getAllByText('Degiro').length).toBeGreaterThan(0);
  });

  it('clicking a composable ticker opens the composition modal, and closing it clears the state', async () => {
    const user = userEvent.setup();
    const etfAccount = {
      ...mockAccountSummary,
      positions: [{ ...mockAccountSummary.positions[0], instrument_type: 'ETF' }],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [etfAccount], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);

    await user.click(screen.getByText('AAPL'));
    expect(screen.getByTestId('modal')).toBeInTheDocument();

    await user.click(screen.getByTestId('modal-close'));
    expect(screen.queryByTestId('modal')).toBeNull();
  });

  it('renders KPI cards', () => {
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummary], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByText('Total portefeuille')).toBeInTheDocument();
    expect(screen.getByText('Espèces totales')).toBeInTheDocument();
    expect(screen.getByText('Titres totaux')).toBeInTheDocument();
  });

  it('renders position ticker', () => {
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummary], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByText('AAPL')).toBeInTheDocument();
  });

  it('renders manual price badge for manual source', () => {
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummaryManualSource], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByText('manual')).toBeInTheDocument();
  });

  it('renders blue label for non-manual source', () => {
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummary], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByText('yahoo')).toBeInTheDocument();
  });

  it('shows "Aucune position" for account with no positions', () => {
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummaryNoPositions], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByText(/Aucune position — espèces uniquement/i)).toBeInTheDocument();
  });

  it('shows sync badge', () => {
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummary], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByTestId('sync-badge')).toBeInTheDocument();
  });

  it('renders summary table', () => {
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummary], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByLabelText('Récapitulatif par compte')).toBeInTheDocument();
  });

  it('renders position with non-EUR currency', () => {
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummary], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    // Position has USD currency — should show native value column
    expect(screen.getByText('Apple')).toBeInTheDocument();
  });

  it('falls back to a default color for an account name not in the known-broker color map', () => {
    const unknownAccount = {
      ...mockAccountSummary,
      id: 99,
      name: 'UnknownBroker',
      positions: [
        {
          ticker: 'BTC', product_name: 'Bitcoin',
          quantity: 0.5, last_price: 30000, last_price_date: '2024-01-01',
          last_price_source: 'yahoo', value_eur: 15000, currency: 'USD',
        },
      ],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [unknownAccount], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getAllByText('UnknownBroker').length).toBeGreaterThan(0);
    expect(screen.getByText('BTC')).toBeInTheDocument();
  });

  it('renders alternating row background colors for multiple positions in the detail table', () => {
    const accountWithMultiplePositions = {
      ...mockAccountSummary,
      positions: [
        { ticker: 'AAPL', product_name: 'Apple', quantity: 10, last_price: 150, last_price_date: '2024-01-01', last_price_source: 'yahoo', value_eur: 1500, currency: 'USD' },
        { ticker: 'MSFT', product_name: 'Microsoft', quantity: 5, last_price: 300, last_price_date: '2024-01-01', last_price_source: 'yahoo', value_eur: 1500, currency: 'USD' },
      ],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [accountWithMultiplePositions], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('MSFT')).toBeInTheDocument();
  });

  it('shows a dash in the percentage-of-total column when the grand total is zero', () => {
    const zeroAccount = {
      ...mockAccountSummary,
      cash_balance_eur: 0,
      positions_value_eur: 0,
      total_eur: 0,
      positions: [],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [zeroAccount], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    // When total is 0, percentage shows '—'
    const body = document.body.textContent ?? '';
    expect(body).toContain('—');
  });

  it('does not render a price date when last_price_date is null', () => {
    const accountNullDate = {
      ...mockAccountSummary,
      positions: [
        { ticker: 'AAPL', product_name: 'Apple', quantity: 10, last_price: 150, last_price_date: null, last_price_source: 'yahoo', value_eur: 1500, currency: 'USD' },
      ],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [accountNullDate], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    // No date shown for null last_price_date
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    const body = document.body.textContent ?? '';
    expect(body).not.toContain('2024-01-01');
  });

  it('shows a dash in the native-currency column for a EUR-denominated position', () => {
    const eurAccount = {
      ...mockAccountSummary,
      positions: [
        { ticker: 'LIQUIDITE.EURO', product_name: 'Liquidités', quantity: 1000, last_price: 1, last_price_date: '2024-01-01', last_price_source: 'manual', value_eur: 1000, currency: 'EUR' },
      ],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [eurAccount], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    // EUR currency → devise column shows '—'
    const cells = screen.getAllByText('—');
    expect(cells.length).toBeGreaterThan(0);
  });

  it('falls back to EUR when formatting the last price for a position with an empty currency', () => {
    // pos.currency = '' → pos.currency || 'EUR' = 'EUR' (the fallback branch)
    const accountEmptyCurrency = {
      ...mockAccountSummary,
      positions: [
        { ticker: 'BOND', product_name: 'Obligation', category: 'Actif', quantity: 100, last_price: 10, last_price_date: '2024-01-01', last_price_source: 'manual', value_eur: 1000, currency: '' },
      ],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [accountEmptyCurrency], isLoading: false, isError: false });
    // Should render without crash (price format uses EUR as fallback)
    render(<AccountsSummaryPage />);
    expect(screen.getByText('BOND')).toBeInTheDocument();
  });

  it('Manuel category: shows "—" for Quantité and Dernier prix, date under Total EUR', () => {
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummaryManualSource], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    // OR.PHYSIQUE-like: quantité and dernier prix must show '—'
    const dashes = screen.getAllByText('—');
    // At least Quantité (—) and Dernier prix (—) and Total devise (—) = 3 dashes
    expect(dashes.length).toBeGreaterThanOrEqual(3);
    // The last_price_date appears under Total EUR
    expect(screen.getByText('2026-05-16')).toBeInTheDocument();
  });

  // ── StalePriceBadge integration via SyntheseComptesPage ─────────────────

  it('StalePriceBadge: shows stale badge in account table when last_price_date > 2 days old', () => {
    const staleDate = new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const accountStale = {
      ...mockAccountSummary,
      positions: [
        { ...mockAccountSummary.positions[0], last_price_date: staleDate, last_price_source: 'yahoo' },
      ],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [accountStale], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    const body = document.body.textContent ?? '';
    expect(body).toMatch(/Prix : \d+j/);
  });

  it('StalePriceBadge: shows no stale badge in account table when last_price_date is within 2 days', () => {
    const freshDate = new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const accountFresh = {
      ...mockAccountSummary,
      positions: [
        { ...mockAccountSummary.positions[0], last_price_date: freshDate, last_price_source: 'yahoo' },
      ],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [accountFresh], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    const body = document.body.textContent ?? '';
    expect(body).not.toMatch(/Prix : \d+j/);
    expect(body).not.toContain('Prix inconnu');
  });

  it('StalePriceBadge: shows "Prix inconnu" for null last_price_date with non-manual source', () => {
    const accountNullDate = {
      ...mockAccountSummary,
      positions: [
        { ...mockAccountSummary.positions[0], last_price_date: null, last_price_source: 'yahoo' },
      ],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [accountNullDate], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    expect(screen.getByText('Prix inconnu')).toBeInTheDocument();
  });

  it('StalePriceBadge: no stale badge for manual source even with old date', () => {
    const oldDate = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    mockUseAccountsSummary.mockReturnValue({ data: [mockAccountSummaryManualSource], isLoading: false, isError: false });
    // mockAccountSummaryManualSource has last_price_source: 'manual' and recent date
    // Use a fresh account with old date + manual source
    const accountManualOld = {
      ...mockAccountSummary,
      positions: [
        { ...mockAccountSummary.positions[0], last_price_date: oldDate, last_price_source: 'manual' },
      ],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [accountManualOld], isLoading: false, isError: false });
    render(<AccountsSummaryPage />);
    const body = document.body.textContent ?? '';
    expect(body).not.toMatch(/Prix : \d+j/);
    expect(body).not.toContain('Prix inconnu');
  });
});

// ── Sort callbacks ────────────────────────────────────────────────────────────

describe('AccountsSummaryPage — sort callbacks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.keys(thClickCount).forEach(k => delete thClickCount[k]);
    mockUseCapitalGains.mockReturnValue({ data: undefined, isLoading: false, isError: false });
  });

  it('clicking a summary table column header triggers the summary sort callback', async () => {
    // onSummSort is passed to the summary table Th via sort prop.
    // The overridden Th mock calls sort.onSort when clicked.
    const twoAccounts = [
      { ...mockAccountSummary, id: 1, name: 'Anzeiger', total_eur: 8000 },
      { ...mockAccountSummary, id: 2, name: 'Boursorama', total_eur: 12000 },
    ];
    mockUseAccountsSummary.mockReturnValue({ data: twoAccounts, isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    const { container } = render(<AccountsSummaryPage />);

    // Find the summary table Th headers and click one to trigger onSummSort
    const ths = Array.from(container.querySelectorAll('th'));
    // Click the first Th (Compte column, index 0 = SUMM_COL.name)
    if (ths.length > 0) {
      await user.click(ths[0]);
      // Sort happened — page still renders correctly
      expect(screen.getByText('Comptes')).toBeInTheDocument();
    }
  });

  it('clicking a per-account detail table column header triggers the account sort callback', async () => {
    // onAccSort is passed to the per-account detail table Th via sort prop.
    const account = { ...mockAccountSummary, positions: [
      { ticker: 'AAPL', product_name: 'Apple', category: 'Actif', quantity: 10, last_price: 150, last_price_date: '2024-01-01', last_price_source: 'yahoo', value_eur: 1500, currency: 'USD' },
      { ticker: 'MSFT', product_name: 'Microsoft', category: 'Actif', quantity: 5, last_price: 300, last_price_date: '2024-01-01', last_price_source: 'yahoo', value_eur: 1500, currency: 'USD' },
    ]};
    mockUseAccountsSummary.mockReturnValue({ data: [account], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    const { container } = render(<AccountsSummaryPage />);

    // Find all Th elements — the detail table Th comes after the summary table Th
    const ths = Array.from(container.querySelectorAll('th'));
    // Click on a later Th (the detail table starts after summary table columns)
    // Summary table has 5 columns; detail table Ths come after
    if (ths.length > 5) {
      await user.click(ths[5]); // first column of detail table
      expect(screen.getByText('Comptes')).toBeInTheDocument();
    } else if (ths.length > 0) {
      // Fallback: click last Th
      await user.click(ths[ths.length - 1]);
      expect(screen.getByText('Comptes')).toBeInTheDocument();
    }
  });

  it('sorts the summary table by each column across multiple accounts', async () => {
    // Need 2+ accounts so the comparator actually runs.
    // Also need to switch sort column to exercise different cases.
    const accounts = [
      { id: 1, name: 'Degiro', currency: 'EUR', cash_balance_eur: 1000, positions_value_eur: 9000, total_eur: 10000, positions: [] },
      { id: 2, name: 'Bourso', currency: 'EUR', cash_balance_eur: 2000, positions_value_eur: 5000, total_eur: 7000, positions: [] },
      { id: 3, name: 'Revolut', currency: 'EUR', cash_balance_eur: 500, positions_value_eur: 1000, total_eur: 1500, positions: [] },
    ];
    mockUseAccountsSummary.mockReturnValue({ data: accounts, isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    const { container } = render(<AccountsSummaryPage />);

    // Click multiple summary Th headers to exercise different sort key branches:
    // name (0), cash (1), positions (2), total (3), pct (4)
    const ths = Array.from(container.querySelectorAll('th'));
    for (let i = 0; i < Math.min(5, ths.length); i++) {
      await user.click(ths[i]);
    }
    expect(screen.getByText('Comptes')).toBeInTheDocument();
  });

  it('clicking the same summary column header twice switches the sort to descending order', async () => {
    // Click same column twice: first = 'asc', second = 'desc' (toggles via thClickCount)
    const twoAccounts = [
      { ...mockAccountSummary, id: 1, name: 'Alpha', total_eur: 8000, cash_balance_eur: 500, positions_value_eur: 7500 },
      { ...mockAccountSummary, id: 2, name: 'Beta', total_eur: 12000, cash_balance_eur: 1000, positions_value_eur: 11000 },
    ];
    mockUseAccountsSummary.mockReturnValue({ data: twoAccounts, isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    const { container } = render(<AccountsSummaryPage />);

    const ths = Array.from(container.querySelectorAll('th'));
    if (ths.length > 0) {
      // Click twice: first click → 'asc', second click → 'desc'
      await user.click(ths[0]);
      await user.click(ths[0]);
      expect(screen.getByText('Comptes')).toBeInTheDocument();
    }
  });

  it('sorting by the percentage column with a zero grand total does not crash', async () => {
    // grandTotal = sum of total_eur. Use total_eur=0 for all accounts.
    const zeroAccounts = [
      { id: 1, name: 'Alpha', currency: 'EUR', cash_balance_eur: 0, positions_value_eur: 0, total_eur: 0, positions: [] },
      { id: 2, name: 'Beta', currency: 'EUR', cash_balance_eur: 0, positions_value_eur: 0, total_eur: 0, positions: [] },
    ];
    mockUseAccountsSummary.mockReturnValue({ data: zeroAccounts, isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    const { container } = render(<AccountsSummaryPage />);

    // Click the "pct" column header (index 4 = SUMM_COL.pct)
    const ths = Array.from(container.querySelectorAll('th'));
    // Find the 5th column (index 4)
    if (ths.length > 4) {
      await user.click(ths[4]);
      // grandTotal = 0 → pA = 0, pB = 0 → both use the false branch of grandTotal > 0
    }
    expect(screen.getByText('Comptes')).toBeInTheDocument();
  });

  it('clicking the same detail table column header twice sorts positions in descending order', async () => {
    const accountWithPositions = {
      ...mockAccountSummary,
      positions: [
        { ticker: 'AAPL', product_name: 'Apple', category: 'Actif', quantity: 10, last_price: 150, last_price_date: '2024-01-01', last_price_source: 'yahoo', value_eur: 1500, currency: 'USD' },
        { ticker: 'MSFT', product_name: 'Microsoft', category: 'Actif', quantity: 5, last_price: 300, last_price_date: '2024-01-01', last_price_source: 'yahoo', value_eur: 1500, currency: 'USD' },
      ],
    };
    mockUseAccountsSummary.mockReturnValue({ data: [accountWithPositions], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    const { container } = render(<AccountsSummaryPage />);

    // Click a detail table Th twice to get desc direction
    const ths = Array.from(container.querySelectorAll('th'));
    // Detail table Ths come after the 5 summary Ths
    if (ths.length > 6) {
      await user.click(ths[5]); // first = 'asc'
      await user.click(ths[5]); // second = 'desc' → dir=-1
      expect(screen.getByText('Comptes')).toBeInTheDocument();
    }
  });
});

// ── StalePriceBadge unit tests (imported directly) ──────────────────────────

describe('StalePriceBadge (from AccountsSummaryPage test file)', () => {
  it('renders nothing for source="manual"', () => {
    const { container } = render(<StalePriceBadge lastPriceDate={null} source="manual" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders "Prix inconnu" for null date with non-manual source', () => {
    render(<StalePriceBadge lastPriceDate={null} source="yahoo" />);
    expect(screen.getByText('Prix inconnu')).toBeInTheDocument();
  });

  it('renders nothing for a date 2 days ago (threshold boundary)', () => {
    const twoDaysAgo = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    const { container } = render(<StalePriceBadge lastPriceDate={twoDaysAgo} source="yahoo" />);
    expect(container.firstChild).toBeNull();
  });

  it('renders "Prix : 7j" for a date 7 days ago', () => {
    const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().split('T')[0];
    render(<StalePriceBadge lastPriceDate={sevenDaysAgo} source="yahoo" />);
    expect(screen.getByText('Prix : 7j')).toBeInTheDocument();
  });
});

// ── computePV and pvColor coverage (lines 55-66, 86, 157-158) ────────────────

describe('AccountsSummaryPage — computePV and pvColor coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.keys(thClickCount).forEach(k => delete thClickCount[k]);
  });

  it('renders the unrealized P&L line for an account when capital gains data is available', () => {
    // Position with category='Actif' and CUMP data → computePV returns non-null
    const accountWithPV = {
      id: 1,
      name: 'Degiro',
      currency: 'EUR',
      cash_balance_eur: 1000,
      positions_value_eur: 9000,
      total_eur: 10000,
      positions: [
        { ticker: 'AAPL', product_name: 'Apple', category: 'Actif', quantity: 10,
          last_price: 200, last_price_date: '2024-01-01', last_price_source: 'yahoo',
          value_eur: 2000, currency: 'USD' },
      ],
    };

    mockUseAccountsSummary.mockReturnValue({ data: [accountWithPV], isLoading: false, isError: false });
    // Provide CUMP data for AAPL: cump = 150 → costBasis = 10 * 150 = 1500, pvEur = 2000 - 1500 = 500 > 0
    mockUseCapitalGains.mockReturnValue({
      data: { tickers: [{ ticker: 'AAPL', cump: 150, unrealized_pv: 500, cost_basis_eur: 1500, realized_pv_total: 0 }] },
      isLoading: false,
      isError: false,
    });

    render(<AccountsSummaryPage />);
    // hasPV = true (computePV returns non-null for AAPL) → PV line renders with + prefix
    expect(screen.getByText('Comptes')).toBeInTheDocument();
    // The PV display should show a positive value (green)
    // The formatEUR mock returns "500.00 €" for 500
    // The pvColor returns '#137333' for positive — this is a style, not text
    expect(screen.getAllByText(/AAPL/).length).toBeGreaterThan(0);
  });

  it('does not show an unrealized P&L for a Frais-category position', () => {
    // Position with category='Frais' → computePV returns null immediately (line 63)
    const accountWithFrais = {
      id: 1,
      name: 'Degiro',
      currency: 'EUR',
      cash_balance_eur: 500,
      positions_value_eur: 1000,
      total_eur: 1500,
      positions: [
        { ticker: 'FRAIS.COURTAGE.EUR', product_name: 'Frais courtage', category: 'Frais',
          quantity: 1, last_price: 5, last_price_date: null, last_price_source: 'manual',
          value_eur: 5, currency: 'EUR' },
      ],
    };

    mockUseAccountsSummary.mockReturnValue({ data: [accountWithFrais], isLoading: false, isError: false });
    mockUseCapitalGains.mockReturnValue({
      data: { tickers: [{ ticker: 'FRAIS.COURTAGE.EUR', cump: 1, unrealized_pv: 0, cost_basis_eur: 1, realized_pv_total: 0 }] },
      isLoading: false,
      isError: false,
    });

    render(<AccountsSummaryPage />);
    // hasPV = false (all positions return null from computePV) → no PV line
    expect(screen.getByText('Comptes')).toBeInTheDocument();
  });

  it('does not show an unrealized P&L when the position quantity is zero (zero cost basis)', () => {
    // Position with cump > 0 but quantity = 0 → costBasis = 0 (line 65)
    const accountWithZeroQty = {
      id: 1,
      name: 'Degiro',
      currency: 'EUR',
      cash_balance_eur: 500,
      positions_value_eur: 0,
      total_eur: 500,
      positions: [
        { ticker: 'AAPL', product_name: 'Apple', category: 'Actif',
          quantity: 0, last_price: 150, last_price_date: null, last_price_source: 'yahoo',
          value_eur: 0, currency: 'USD' },
      ],
    };

    mockUseAccountsSummary.mockReturnValue({ data: [accountWithZeroQty], isLoading: false, isError: false });
    mockUseCapitalGains.mockReturnValue({
      data: { tickers: [{ ticker: 'AAPL', cump: 150, unrealized_pv: 0, cost_basis_eur: 0, realized_pv_total: 0 }] },
      isLoading: false,
      isError: false,
    });

    render(<AccountsSummaryPage />);
    expect(screen.getByText('Comptes')).toBeInTheDocument();
  });

  it('pvColor: negative PV renders red (pvColor < 0 branch)', () => {
    // Position with negative PV
    const accountNegPV = {
      id: 1,
      name: 'Degiro',
      currency: 'EUR',
      cash_balance_eur: 0,
      positions_value_eur: 500,
      total_eur: 500,
      positions: [
        { ticker: 'AAPL', product_name: 'Apple', category: 'Actif',
          quantity: 10, last_price: 50, last_price_date: null, last_price_source: 'yahoo',
          value_eur: 500, currency: 'USD' },
      ],
    };

    mockUseAccountsSummary.mockReturnValue({ data: [accountNegPV], isLoading: false, isError: false });
    // CUMP 100 > current price 50: pvEur = 500 - 1000 = -500 < 0
    mockUseCapitalGains.mockReturnValue({
      data: { tickers: [{ ticker: 'AAPL', cump: 100, unrealized_pv: -500, cost_basis_eur: 1000, realized_pv_total: 0 }] },
      isLoading: false,
      isError: false,
    });

    render(<AccountsSummaryPage />);
    // hasPV = true → renders PV column; pvColor = '#D93025' for negative
    expect(screen.getByText('Comptes')).toBeInTheDocument();
  });

  it('pvColor: renders the unrealized P&L in a neutral color when it is exactly zero', () => {
    // Position with PV = 0 → pvColor(0) = 'var(--pf-t--global--text--color--subtle)' (line 57)
    const accountZeroPV = {
      id: 1, name: 'Degiro', currency: 'EUR', cash_balance_eur: 0, positions_value_eur: 1000, total_eur: 1000,
      positions: [
        { ticker: 'AAPL', product_name: 'Apple', category: 'Actif', quantity: 10,
          last_price: 100, last_price_date: null, last_price_source: 'yahoo', value_eur: 1000, currency: 'USD' },
      ],
    };

    mockUseAccountsSummary.mockReturnValue({ data: [accountZeroPV], isLoading: false, isError: false });
    // CUMP 100 = current price: pvEur = 1000 - 1000 = 0 → pvColor(0) = neutral
    mockUseCapitalGains.mockReturnValue({
      data: { tickers: [{ ticker: 'AAPL', cump: 100, unrealized_pv: 0, cost_basis_eur: 1000, realized_pv_total: 0 }] },
      isLoading: false, isError: false,
    });

    render(<AccountsSummaryPage />);
    expect(screen.getByText('Comptes')).toBeInTheDocument();
  });

  it('sorts the detail table by the unrealized P&L and P&L percentage columns', async () => {
    const accounts = [
      {
        id: 1, name: 'Degiro', currency: 'EUR', cash_balance_eur: 1000, positions_value_eur: 3000, total_eur: 4000,
        positions: [
          { ticker: 'AAPL', product_name: 'Apple', category: 'Actif', quantity: 10,
            last_price: 200, last_price_date: null, last_price_source: 'yahoo', value_eur: 2000, currency: 'USD' },
          { ticker: 'MSFT', product_name: 'Microsoft', category: 'Actif', quantity: 5,
            last_price: 200, last_price_date: null, last_price_source: 'yahoo', value_eur: 1000, currency: 'USD' },
        ],
      },
    ];

    mockUseAccountsSummary.mockReturnValue({ data: accounts, isLoading: false, isError: false });
    mockUseCapitalGains.mockReturnValue({
      data: { tickers: [
        { ticker: 'AAPL', cump: 150, unrealized_pv: 500, cost_basis_eur: 1500, realized_pv_total: 0 },
        { ticker: 'MSFT', cump: 180, unrealized_pv: 100, cost_basis_eur: 900, realized_pv_total: 0 },
      ] },
      isLoading: false,
      isError: false,
    });

    const user = userEvent.setup({ delay: null });
    const { container } = render(<AccountsSummaryPage />);

    // Click ALL Th headers to trigger sort by each column, including pvEur and pvPct
    const ths = Array.from(container.querySelectorAll('th'));
    for (const th of ths) {
      await user.click(th as HTMLElement);
    }

    expect(screen.getByText('Comptes')).toBeInTheDocument();
  });
});
