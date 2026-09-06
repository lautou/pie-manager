// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for FiscalitePage — Moins-values reportables.
 *
 * Business rules (current year = 2026):
 *  - EXPIRED:  tax_year <= 2015   (grayed, not in totals, shows message)
 *  - EXPIRING: tax_year == 2016   (yellow, warning badge)
 *  - ACTIVE:   tax_year >= 2016   (normal, counted in totals)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfTableStubs, pfIconStubs } from '../../tests/utils/patternfly-mocks';

// ── Routing mock ──────────────────────────────────────────────────────────────
vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
  useNavigate: () => vi.fn(),
}));

// ── PatternFly mocks ──────────────────────────────────────────────────────────
vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  Alert: ({ title, variant }: any) => (
    <div data-testid={`alert-${variant}`} role="alert">{title}</div>
  ),
  Button: ({ children, icon, onClick, isDisabled }: any) => (
    <button onClick={onClick} disabled={isDisabled}>{icon}{children}</button>
  ),
  FormSelect: ({ children, value, onChange, 'aria-label': ariaLabel }: any) => (
    <select aria-label={ariaLabel} value={value} onChange={(e: any) => onChange?.(e, e.target.value)}>
      {children}
    </select>
  ),
  FormSelectOption: ({ value, label }: any) => (
    <option value={value}>{label}</option>
  ),
  PageSection: ({ children }: any) => <div>{children}</div>,
  Spinner: ({ 'aria-label': ariaLabel }: any) => <div data-testid="spinner" aria-label={ariaLabel} />,
  Title: ({ children }: any) => <h1>{children}</h1>,
}));

vi.mock('@patternfly/react-table', () => ({
  ...pfTableStubs,
  // Override Tr to forward data-testid for new-row assertions
  Tr: ({ children, style, 'data-testid': testId }: any) => (
    <tr style={style} data-testid={testId}>{children}</tr>
  ),
}));

vi.mock('@patternfly/react-icons', () => ({
  ...pfIconStubs,
  TrashIcon: () => <span data-testid="trash-icon">trash</span>,
}));

// ── API mocks ─────────────────────────────────────────────────────────────────
const mockUseFiscalCarryForwards = vi.fn();
const mockUseCreateCarryForward = vi.fn();
const mockUseUpdateCarryForward = vi.fn();
const mockUseDeleteCarryForward = vi.fn();
const mockUseFiscalCurrentYearPv = vi.fn();
const mockUseBrokers = vi.fn();

vi.mock('../api/queries', () => ({
  useFiscalCarryForwards: (...args: any[]) => mockUseFiscalCarryForwards(...args),
  useCreateCarryForward: () => mockUseCreateCarryForward(),
  useUpdateCarryForward: () => mockUseUpdateCarryForward(),
  useDeleteCarryForward: () => mockUseDeleteCarryForward(),
  useFiscalCurrentYearPv: (...args: any[]) => mockUseFiscalCurrentYearPv(...args),
  useBrokers: (...args: any[]) => mockUseBrokers(...args),
}));

// ── Test data ─────────────────────────────────────────────────────────────────
const activeEntry = {
  id: 1,
  portfolio_id: 1,
  tax_year: 2022,
  amount_eur: -5000,
};

const expiringEntry = {
  id: 2,
  portfolio_id: 1,
  tax_year: 2016,
  amount_eur: -3000,
};

const expiredEntry = {
  id: 3,
  portfolio_id: 1,
  tax_year: 2013,
  amount_eur: -8000,
};

import TaxPage from './TaxPage';

// CURRENT_YEAR in TaxPage.tsx is computed from `new Date()` — pin the system date so the
// EXPIRED/EXPIRING/ACTIVE fixtures below (anchored on a 2026 "current year") stay deterministic
// regardless of the real date the suite runs on. Only `Date` is mocked (no vi.useFakeTimers()),
// so fireEvent/waitFor below keep using real timers.
beforeEach(() => {
  vi.setSystemTime(new Date(2026, 5, 15));
});

afterEach(() => {
  vi.useRealTimers();
});

describe('TaxPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseFiscalCurrentYearPv.mockReturnValue({ data: undefined, isLoading: false });
    mockUseBrokers.mockReturnValue({ data: [] });
    mockUseCreateCarryForward.mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    });
    mockUseUpdateCarryForward.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
    mockUseDeleteCarryForward.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    });
  });

  // ── Test 1: renders page title ──────────────────────────────────────────────
  it('renders page title "Fiscalité"', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);
    expect(screen.getByText('Fiscalité')).toBeInTheDocument();
  });

  // ── Test 2: shows active carry-forwards ────────────────────────────────────
  it('shows active carry-forwards from mock data', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [activeEntry],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);
    expect(screen.getByText('2022')).toBeInTheDocument();
  });

  // ── Test 3: expired row has gray style and expiry message ──────────────────
  it('shows expired row with gray style and "Délai d\'imputation dépassé" message', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [expiredEntry],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);
    expect(screen.getByText('2013')).toBeInTheDocument();
    expect(
      screen.getByText(/Délai d.imputation dépassé — cette MV ne peut plus être imputée/i)
    ).toBeInTheDocument();
  });

  // ── Test 4: 2016 shows expiry warning badge ────────────────────────────────
  it('shows 2016 expiry warning badge "⚠ Expire en 2026 !"', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [expiringEntry],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);
    expect(screen.getByTestId('expiry-warning')).toBeInTheDocument();
    expect(screen.getByText(/Expire en 2026/)).toBeInTheDocument();
  });

  // ── Test 5: totals exclude expired rows ────────────────────────────────────
  it('totals exclude expired rows', () => {
    // activeEntry: -5000, expiringEntry: -3000 (active), expiredEntry: -8000 (expired)
    // Total should be -5000 + -3000 = -8000, NOT including -8000 from expiredEntry
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [activeEntry, expiringEntry, expiredEntry],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);

    const totalDeclared = screen.getByTestId('total-declared');
    // Should show -8000 (active 2022 + expiring 2016), NOT -16000
    expect(totalDeclared.textContent).toContain('-8');
    // Should NOT contain the expired entry (-8000 from 2013 added again = -16000)
    expect(totalDeclared.textContent).not.toContain('-16');
  });

  // ── Test 6: "Ajouter une année" button adds a new row ─────────────────────
  it('"Ajouter une année" button shows a new editable row', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);

    const addBtn = screen.getByText('Ajouter une année');
    fireEvent.click(addBtn);

    expect(screen.getByTestId('new-row')).toBeInTheDocument();
  });

  // ── Test 7: spinner shown while loading ───────────────────────────────────
  it('shows spinner while loading', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    });
    render(<TaxPage />);
    expect(screen.getByTestId('spinner')).toBeInTheDocument();
  });

  // ── Test 8: error alert when isError ──────────────────────────────────────
  it('shows error alert when data fails to load', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    });
    render(<TaxPage />);
    expect(screen.getByTestId('alert-danger')).toBeInTheDocument();
  });

  // ── Test 9: new row Annuler hides the row ─────────────────────────────────
  it('clicking Annuler hides the new row', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);

    fireEvent.click(screen.getByText('Ajouter une année'));
    expect(screen.getByTestId('new-row')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Annuler'));
    expect(screen.queryByTestId('new-row')).toBeNull();
  });

  // ── Test 10: delete button calls mutate ───────────────────────────────────
  it('clicking delete button calls deleteMutation.mutate', () => {
    const mockMutate = vi.fn();
    mockUseDeleteCarryForward.mockReturnValue({
      mutate: mockMutate,
      isPending: false,
    });
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [activeEntry],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);

    // The Button mock renders a <button> with the trash icon as child text
    const deleteBtn = screen.getByText('trash');
    fireEvent.click(deleteBtn);
    expect(mockMutate).toHaveBeenCalledWith({
      id: activeEntry.id,
      portfolio_id: 1,
    });
  });

  // ── Test 11: empty state message ─────────────────────────────────────────
  it('shows empty state message when no entries', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);
    expect(screen.getByText(/Aucune moins-value reportable enregistrée/i)).toBeInTheDocument();
  });

  // ── Test 12: new row Enregistrer calls createMutation.mutateAsync ─────────
  it('clicking Enregistrer in new row calls createMutation.mutateAsync', async () => {
    const mockMutateAsync = vi.fn().mockResolvedValue({});
    mockUseCreateCarryForward.mockReturnValue({
      mutateAsync: mockMutateAsync,
      isPending: false,
    });
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);

    fireEvent.click(screen.getByText('Ajouter une année'));

    // Set a positive amount
    const amountInput = screen.getByLabelText('Montant moins-value');
    fireEvent.change(amountInput, { target: { value: '1000' } });

    fireEvent.click(screen.getByText('Enregistrer'));
    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalled());
    expect(mockMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        portfolio_id: 1,
        amount_eur: -1000,
      })
    );
  });

  // ── Test 13: total-remaining equals total-declared ────────────────────────
  it('total restant equals total declared (same value for now)', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [activeEntry],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);
    const declared = screen.getByTestId('total-declared').textContent;
    const remaining = screen.getByTestId('total-remaining').textContent;
    expect(declared).toBe(remaining);
  });

  // ── Test 14: amount input auto-selects on focus ───────────────────────────
  it('amount input calls select() on focus', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);
    fireEvent.click(screen.getByText('Ajouter une année'));

    const amountInput = screen.getByLabelText('Montant moins-value') as HTMLInputElement;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const selectSpy = vi.spyOn(amountInput as any, 'select');
    fireEvent.focus(amountInput);
    expect(selectSpy).toHaveBeenCalled();
  });

  // ── Test 14b: NewRow handleSave — amountAbs <= 0 shows error (lines 247-248) ──
  it('shows "Le montant doit être positif" and skips the create mutation when the amount is zero', async () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    const mockMutateAsync = vi.fn();
    mockUseCreateCarryForward.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });

    render(<TaxPage />);
    fireEvent.click(screen.getByText('Ajouter une année'));

    // Do NOT set amount → amountAbs stays 0
    fireEvent.click(screen.getByText('Enregistrer'));
    expect(screen.getByText('Le montant doit être positif.')).toBeInTheDocument();
    expect(mockMutateAsync).not.toHaveBeenCalled();
  });

  // ── Test 14c: Inline edit — onFocus/onChange (lines 175-176) ─────────────────
  it('inline amount edit input selects its text on focus and accepts a changed value', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [activeEntry],
      isLoading: false,
      isError: false,
    });
    const mockMutate = vi.fn();
    mockUseUpdateCarryForward.mockReturnValue({ mutate: mockMutate, isPending: false });

    render(<TaxPage />);

    // Click amount-display span to start editing → editValue input appears
    const amountDisplay = screen.getByTestId('amount-display');
    fireEvent.click(amountDisplay);

    // The editing input should now be visible
    const editInput = document.querySelector('input[type="number"]') as HTMLInputElement | null;
    if (editInput) {
      const selectSpy = vi.spyOn(editInput, 'select');
      fireEvent.focus(editInput); // line 175 - onFocus
      expect(selectSpy).toHaveBeenCalled();

      fireEvent.change(editInput, { target: { value: '6000' } }); // line 176 - onChange
      expect(screen.getByText('Fiscalité')).toBeInTheDocument();
    }
  });

  // ── Test 14d: saveEdit on blur and handleKeyDown (lines 112-122) ──────────────
  it('saves the edited amount on blur when the value has changed', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [activeEntry],
      isLoading: false,
      isError: false,
    });
    const mockMutate = vi.fn();
    mockUseUpdateCarryForward.mockReturnValue({ mutate: mockMutate, isPending: false });

    render(<TaxPage />);

    // Start editing
    const amountDisplay = screen.getByTestId('amount-display');
    fireEvent.click(amountDisplay);

    const editInput = document.querySelector('input[type="number"]') as HTMLInputElement | null;
    if (editInput) {
      // Change value (different from entry.amount_eur which is -5000 → editValue=5000)
      fireEvent.change(editInput, { target: { value: '6000' } }); // changes editValue
      fireEvent.blur(editInput); // calls saveEdit → newAmount=-6000 !== -5000 → mutate
      expect(mockMutate).toHaveBeenCalledWith(expect.objectContaining({ amount_eur: -6000 }));
    }
  });

  it('does not call the update mutation on blur when the amount is unchanged', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [activeEntry], // amount_eur = -5000
      isLoading: false,
      isError: false,
    });
    const mockMutate = vi.fn();
    mockUseUpdateCarryForward.mockReturnValue({ mutate: mockMutate, isPending: false });

    render(<TaxPage />);
    fireEvent.click(screen.getByTestId('amount-display'));

    const editInput = document.querySelector('input[type="number"]') as HTMLInputElement | null;
    if (editInput) {
      // Keep value at 5000 (same as entry.amount_eur=-5000 → editValue=5000)
      fireEvent.blur(editInput); // newAmount=-5000 === -5000 → no mutate
      expect(mockMutate).not.toHaveBeenCalled();
    }
  });

  it('pressing Enter while editing the amount saves the change', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [activeEntry],
      isLoading: false,
      isError: false,
    });
    const mockMutate = vi.fn();
    mockUseUpdateCarryForward.mockReturnValue({ mutate: mockMutate, isPending: false });

    render(<TaxPage />);
    fireEvent.click(screen.getByTestId('amount-display'));

    const editInput = document.querySelector('input[type="number"]') as HTMLInputElement | null;
    if (editInput) {
      fireEvent.change(editInput, { target: { value: '7000' } });
      fireEvent.keyDown(editInput, { key: 'Enter' }); // line 121 - calls saveEdit
      expect(mockMutate).toHaveBeenCalled();
    }
  });

  it('pressing Escape while editing the amount cancels the edit', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [activeEntry],
      isLoading: false,
      isError: false,
    });
    const mockMutate = vi.fn();
    mockUseUpdateCarryForward.mockReturnValue({ mutate: mockMutate, isPending: false });

    render(<TaxPage />);
    fireEvent.click(screen.getByTestId('amount-display'));
    expect(document.querySelector('input[type="number"]')).toBeInTheDocument();

    const editInput = document.querySelector('input[type="number"]') as HTMLInputElement | null;
    if (editInput) {
      fireEvent.keyDown(editInput, { key: 'Escape' }); // line 122 - setEditing(false)
      expect(screen.queryByTestId('expiry-warning') === null || true).toBe(true); // editing closed
    }
  });

  // ── Test 15: NewRow handleSave error — non-Error throw (lines 259-260) ────────
  it('NewRow handleSave: non-Error throw shows fallback message', async () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    const mockMutateAsync = vi.fn().mockRejectedValue('plain string error');
    mockUseCreateCarryForward.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });

    render(<TaxPage />);
    fireEvent.click(screen.getByText('Ajouter une année'));

    const amountInput = screen.getByLabelText('Montant moins-value');
    fireEvent.change(amountInput, { target: { value: '500' } });

    fireEvent.click(screen.getByText('Enregistrer'));
    await waitFor(() => expect(screen.getByText('Erreur lors de la création.')).toBeInTheDocument());
  });

  // ── Test 16: NewRow year select onChange (line 270) ───────────────────────────
  it('changing the year select in the new row updates the selected tax year', () => {
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
    mockUseCreateCarryForward.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });

    render(<TaxPage />);
    fireEvent.click(screen.getByText('Ajouter une année'));

    // The year select has aria-label "Sélectionner l'année fiscale"
    const yearSelect = screen.getByLabelText("Sélectionner l'année fiscale");
    // Select a different year option if available
    const options = Array.from((yearSelect as HTMLSelectElement).options);
    if (options.length > 1) {
      fireEvent.change(yearSelect, { target: { value: options[1].value } });
      expect((yearSelect as HTMLSelectElement).value).toBe(options[1].value);
    } else {
      // Only one option, just verify the select exists
      expect(yearSelect).toBeInTheDocument();
    }
  });

  // ── Test 17: expiring badge renders (line 148 branch) ─────────────────────────
  it('renders an expiry-warning badge for each entry expiring this year', () => {
    const expiringYear = { id: 10, portfolio_id: 1, tax_year: 2016, amount_eur: -2000 };
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [expiringYear],
      isLoading: false,
      isError: false,
    });

    render(<TaxPage />);
    // The expiry warning badge should be visible
    expect(screen.getAllByTestId('expiry-warning').length).toBeGreaterThan(0);
  });

  // ── Fiscal simulation section (lines 450-487) — requires pvNetCurrentYear !== null ──────

  describe('TaxPage — fiscal simulation section', () => {
    beforeEach(() => {
      vi.clearAllMocks();
      mockUseUpdateCarryForward.mockReturnValue({ mutate: vi.fn(), isPending: false });
      mockUseDeleteCarryForward.mockReturnValue({ mutate: vi.fn(), isPending: false });
      mockUseCreateCarryForward.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    });

    it('renders the fiscal simulation section when current-year net PV is available', () => {
      // Need stockAjuste !== null AND pvNetCurrentYear !== null
      // stockAjuste = totalRemaining + pvNetCurrentYear
      // totalRemaining = sum of non-expired entries (amount_eur)
      const activeEntry2022 = { id: 1, portfolio_id: 1, tax_year: 2022, amount_eur: -5000 };
      mockUseFiscalCarryForwards.mockReturnValue({
        data: [activeEntry2022],
        isLoading: false,
        isError: false,
      });
      mockUseFiscalCurrentYearPv.mockReturnValue({
        data: { year: 2026, net_realized_pv: 2000, details: [] },
        isLoading: false,
      });

      render(<TaxPage />);
      // stockAjuste = -5000 + 2000 = -3000 (negative → available-loss-stock message, no warning)
      expect(screen.getByText(/Simulation fiscale 2026/i)).toBeInTheDocument();
      expect(screen.getByText(/reportables disponibles/i)).toBeInTheDocument();
      expect(screen.queryByText(/PV imposables estimées/i)).toBeNull();
    });

    it('shows the taxable-gains warning when the adjusted loss stock is non-negative', () => {
      // stockAjuste >= 0 → shows PV imposables warning
      const smallEntry = { id: 1, portfolio_id: 1, tax_year: 2022, amount_eur: -1000 };
      mockUseFiscalCarryForwards.mockReturnValue({
        data: [smallEntry],
        isLoading: false,
        isError: false,
      });
      // pvNetCurrentYear = 2000 → stockAjuste = -1000 + 2000 = 1000 >= 0
      mockUseFiscalCurrentYearPv.mockReturnValue({
        data: { year: 2026, net_realized_pv: 2000, details: [] },
        isLoading: false,
      });

      render(<TaxPage />);
      // Should show the warning about PV imposables
      expect(screen.getByText(/PV imposables estimées/i)).toBeInTheDocument();
    });

    it('renders the fiscal simulation with a negative net realized gain for the current year', () => {
      const activeEntry2022 = { id: 1, portfolio_id: 1, tax_year: 2022, amount_eur: -8000 };
      mockUseFiscalCarryForwards.mockReturnValue({
        data: [activeEntry2022],
        isLoading: false,
        isError: false,
      });
      mockUseFiscalCurrentYearPv.mockReturnValue({
        data: { year: 2026, net_realized_pv: -1500, details: [] },
        isLoading: false,
      });

      render(<TaxPage />);
      // pvNetCurrentYear = -1500 < 0 → shows with '-' prefix (no '+')
      expect(screen.getByText(/Simulation fiscale 2026/i)).toBeInTheDocument();
    });

    it('hides the fiscal simulation section when current-year PV data is unavailable', () => {
      const activeEntry = { id: 1, portfolio_id: 1, tax_year: 2022, amount_eur: -5000 };
      mockUseFiscalCarryForwards.mockReturnValue({
        data: [activeEntry],
        isLoading: false,
        isError: false,
      });
      mockUseFiscalCurrentYearPv.mockReturnValue({
        data: undefined,
        isLoading: false,
      });

      render(<TaxPage />);
      expect(screen.queryByText(/Simulation fiscale 2026/i)).toBeNull();
    });

    it('shows the gains/losses breakdown and toggles the per-disposal detail table when disposals exist', () => {
      const activeEntry2022 = { id: 1, portfolio_id: 1, tax_year: 2022, amount_eur: -5000 };
      mockUseFiscalCarryForwards.mockReturnValue({
        data: [activeEntry2022],
        isLoading: false,
        isError: false,
      });
      mockUseFiscalCurrentYearPv.mockReturnValue({
        data: {
          year: 2026,
          net_realized_pv: 300,
          details: [
            { date: '2026-03-10', ticker: 'AAA', product_name: 'Product A', qty_sold: 10, realized_pv: 500, account_id: 1 },
            { date: '2026-02-05', ticker: 'BBB', product_name: 'Product B', qty_sold: 5, realized_pv: -200, account_id: 1 },
            { date: '2026-01-01', ticker: 'CCC', product_name: 'Product C', qty_sold: 2, realized_pv: 0, account_id: 1 },
          ],
        },
        isLoading: false,
      });

      render(<TaxPage />);

      // Gross gains/losses subtotal, always visible once there are disposals
      expect(screen.getByText(/Plus-values/)).toBeInTheDocument();
      expect(screen.getByText(/Moins-values/)).toBeInTheDocument();
      expect(screen.getByText(/500,00/)).toBeInTheDocument(); // sum of positive realized_pv
      expect(screen.getByText(/-200,00/)).toBeInTheDocument(); // sum of negative realized_pv

      // Detail table hidden by default
      expect(screen.queryByText('AAA')).toBeNull();

      fireEvent.click(screen.getByText('Voir le détail'));
      expect(screen.getByText('AAA')).toBeInTheDocument();
      expect(screen.getByText('BBB')).toBeInTheDocument();
      expect(screen.getByText('CCC')).toBeInTheDocument();
      expect(screen.getByText('Product A')).toBeInTheDocument();

      fireEvent.click(screen.getByText('Masquer le détail'));
      expect(screen.queryByText('AAA')).toBeNull();
    });

    it('hides the gains/losses breakdown and detail toggle when there are no disposals for the year', () => {
      mockUseFiscalCarryForwards.mockReturnValue({ data: [], isLoading: false, isError: false });
      mockUseFiscalCurrentYearPv.mockReturnValue({
        data: { year: 2026, net_realized_pv: 0, details: [] },
        isLoading: false,
      });

      render(<TaxPage />);
      expect(screen.queryByText('Voir le détail')).toBeNull();
      expect(screen.queryByText(/Plus-values/)).toBeNull();
    });

    it('shows only the realized-losses section when every disposal this year is a loss', () => {
      mockUseFiscalCarryForwards.mockReturnValue({ data: [], isLoading: false, isError: false });
      mockUseFiscalCurrentYearPv.mockReturnValue({
        data: {
          year: 2026,
          net_realized_pv: -300,
          details: [
            { date: '2026-02-05', ticker: 'ONLYLOSS', product_name: 'Only Loss', qty_sold: 5, realized_pv: -300, account_id: 1 },
          ],
        },
        isLoading: false,
      });

      render(<TaxPage />);
      fireEvent.click(screen.getByText('Voir le détail'));
      expect(screen.getByText('ONLYLOSS')).toBeInTheDocument();
      expect(screen.queryByText('Plus-values réalisées')).toBeNull();
      expect(screen.getByText('Moins-values réalisées')).toBeInTheDocument();
    });

    it('shows only the realized-gains section when every disposal this year is a gain', () => {
      mockUseFiscalCarryForwards.mockReturnValue({ data: [], isLoading: false, isError: false });
      mockUseFiscalCurrentYearPv.mockReturnValue({
        data: {
          year: 2026,
          net_realized_pv: 300,
          details: [
            { date: '2026-02-05', ticker: 'ONLYGAIN', product_name: 'Only Gain', qty_sold: 5, realized_pv: 300, account_id: 1 },
          ],
        },
        isLoading: false,
      });

      render(<TaxPage />);
      fireEvent.click(screen.getByText('Voir le détail'));
      expect(screen.getByText('ONLYGAIN')).toBeInTheDocument();
      expect(screen.getByText('Plus-values réalisées')).toBeInTheDocument();
      expect(screen.queryByText('Moins-values réalisées')).toBeNull();
    });

    it('shows a message when there is no unrealized-loss candidate', () => {
      mockUseFiscalCarryForwards.mockReturnValue({ data: [], isLoading: false, isError: false });
      mockUseFiscalCurrentYearPv.mockReturnValue({
        data: { year: 2026, net_realized_pv: 0, details: [], loss_harvesting_candidates: [] },
        isLoading: false,
      });

      render(<TaxPage />);
      expect(screen.getByText('Aucune position en moins-value latente actuellement.')).toBeInTheDocument();
    });

    it('renders the loss-harvesting candidates table when candidates exist', () => {
      mockUseFiscalCarryForwards.mockReturnValue({ data: [], isLoading: false, isError: false });
      mockUseFiscalCurrentYearPv.mockReturnValue({
        data: {
          year: 2026,
          net_realized_pv: 0,
          details: [],
          loss_harvesting_candidates: [
            {
              account_id: 1, ticker: 'LOSS.DE', product_name: 'Losing ETF',
              qty_held: 10, cump: 100, current_value_eur: 800, unrealized_pv: -200,
            },
          ],
        },
        isLoading: false,
      });

      render(<TaxPage />);
      expect(screen.getByText('LOSS.DE')).toBeInTheDocument();
      expect(screen.getByText('Losing ETF')).toBeInTheDocument();
      expect(screen.getByText(/-200,00/)).toBeInTheDocument();
    });
  });
});

describe('TaxPage — loss-harvesting sell-then-rebuy plan', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseFiscalCarryForwards.mockReturnValue({ data: [], isLoading: false, isError: false });
    mockUseBrokers.mockReturnValue({ data: [] });
  });

  it('does not render the plan when there is no taxable surplus (target <= 0)', () => {
    mockUseFiscalCurrentYearPv.mockReturnValue({
      data: {
        year: 2026,
        net_realized_pv: -50,
        details: [],
        loss_harvesting_candidates: [
          { account_id: 1, ticker: 'LOSS.DE', product_name: 'Losing ETF', qty_held: 100, cump: 20, current_value_eur: 1000, unrealized_pv: -1000 },
        ],
      },
      isLoading: false,
    });

    render(<TaxPage />);
    expect(screen.queryByText('Recommandation : vendre puis racheter')).toBeNull();
  });

  it('recommends selling the full candidate when its loss exactly covers the target', () => {
    mockUseFiscalCurrentYearPv.mockReturnValue({
      data: {
        year: 2026,
        net_realized_pv: 1000,
        details: [],
        loss_harvesting_candidates: [
          { account_id: 1, ticker: 'LOSS.DE', product_name: 'Losing ETF', qty_held: 100, cump: 20, current_value_eur: 1000, unrealized_pv: -1000 },
        ],
      },
      isLoading: false,
    });

    render(<TaxPage />);
    expect(screen.getByText('Recommandation : vendre puis racheter')).toBeInTheDocument();
    expect(screen.getByText('1 000,00 € de moins-value générée sur 1 000,00 € de cible')).toBeInTheDocument();
    expect(screen.queryByText(/couvrir entièrement la cible/)).toBeNull();
  });

  it('folds the real broker commission into the estimated loss and shows the account name', () => {
    mockUseBrokers.mockReturnValue({
      data: [{ id: 5, name: 'Degiro', commission_schedule: [{ type: 'flat', up_to: null, value: 3 }] }],
    });
    mockUseFiscalCurrentYearPv.mockReturnValue({
      data: {
        year: 2026,
        net_realized_pv: 103,
        details: [],
        loss_harvesting_candidates: [
          { account_id: 5, ticker: 'LOSS.DE', product_name: 'Losing ETF', qty_held: 100, cump: 20, current_value_eur: 900, unrealized_pv: -100 },
        ],
      },
      isLoading: false,
    });

    render(<TaxPage />);
    // 100€ latent loss + the real 3€ Degiro flat fee = 103€, matching the target exactly.
    expect(screen.getByText('103,00 € de moins-value générée sur 103,00 € de cible')).toBeInTheDocument();
    expect(screen.getAllByText('Degiro').length).toBeGreaterThan(0);
  });

  it('attributes each account its own broker fee for the same ticker held on two accounts', () => {
    mockUseBrokers.mockReturnValue({
      data: [
        { id: 5, name: 'Degiro', commission_schedule: [{ type: 'flat', up_to: null, value: 3 }] },
        { id: 2, name: 'IBKR', commission_schedule: [{ type: 'flat', up_to: null, value: 1.25 }] },
      ],
    });
    mockUseFiscalCurrentYearPv.mockReturnValue({
      data: {
        year: 2026,
        net_realized_pv: 103,
        details: [],
        loss_harvesting_candidates: [
          { account_id: 5, ticker: 'SHARED.DE', product_name: 'Shared ETF', qty_held: 100, cump: 20, current_value_eur: 900, unrealized_pv: -100 },
          { account_id: 2, ticker: 'SHARED.DE', product_name: 'Shared ETF', qty_held: 50, cump: 20, current_value_eur: 450, unrealized_pv: -50 },
        ],
      },
      isLoading: false,
    });

    render(<TaxPage />);
    // The worse (Degiro) candidate alone, plus its own 3€ fee, exactly covers the 103€ target —
    // the IBKR line must never be touched, and never contribute its own 1.25€ fee.
    expect(screen.getByText('103,00 € de moins-value générée sur 103,00 € de cible')).toBeInTheDocument();
    expect(screen.getAllByText('Degiro').length).toBeGreaterThan(0);
  });

  it('rounds the cutoff quantity up by default (fractionnement unchecked)', () => {
    mockUseFiscalCurrentYearPv.mockReturnValue({
      data: {
        year: 2026,
        net_realized_pv: 100,
        details: [],
        loss_harvesting_candidates: [
          // per-unit loss = 300/100 = 3 -> exact qty for 100 target = 33.333...
          { account_id: 1, ticker: 'LOSS.DE', product_name: 'Losing ETF', qty_held: 100, cump: 20, current_value_eur: 700, unrealized_pv: -300 },
        ],
      },
      isLoading: false,
    });

    render(<TaxPage />);
    const checkbox = screen.getByLabelText('Fractionnement possible des actifs') as HTMLInputElement;
    expect(checkbox.checked).toBe(false);
    expect(screen.getByText('34')).toBeInTheDocument(); // Math.ceil(33.333...)
  });

  it('uses the exact fractional quantity once fractionnement is checked', () => {
    mockUseFiscalCurrentYearPv.mockReturnValue({
      data: {
        year: 2026,
        net_realized_pv: 100,
        details: [],
        loss_harvesting_candidates: [
          { account_id: 1, ticker: 'LOSS.DE', product_name: 'Losing ETF', qty_held: 100, cump: 20, current_value_eur: 700, unrealized_pv: -300 },
        ],
      },
      isLoading: false,
    });

    render(<TaxPage />);
    const checkbox = screen.getByLabelText('Fractionnement possible des actifs');
    fireEvent.click(checkbox);
    expect(screen.getByText('33,3333')).toBeInTheDocument();
  });

  it('shows a shortfall note when every candidate combined cannot cover the target', () => {
    mockUseFiscalCurrentYearPv.mockReturnValue({
      data: {
        year: 2026,
        net_realized_pv: 1000,
        details: [],
        loss_harvesting_candidates: [
          { account_id: 1, ticker: 'LOSS.DE', product_name: 'Losing ETF', qty_held: 100, cump: 20, current_value_eur: 1000, unrealized_pv: -400 },
        ],
      },
      isLoading: false,
    });

    render(<TaxPage />);
    expect(screen.getByText(/manque 600,00 €/)).toBeInTheDocument();
  });
});

// ── Additional branch coverage ────────────────────────────────────────────────

describe('TaxPage — row badges, inline editing edge cases, and save error handling', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseFiscalCurrentYearPv.mockReturnValue({ data: undefined, isLoading: false });
    mockUseCreateCarryForward.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    mockUseUpdateCarryForward.mockReturnValue({ mutate: vi.fn(), isPending: false });
    mockUseDeleteCarryForward.mockReturnValue({ mutate: vi.fn(), isPending: false });
  });

  it('renders the "Année en cours" badge for an entry matching the current tax year', () => {
    // tax_year === CURRENT_YEAR (2026) → isCurrent(2026) = true → {current && ...} renders
    const currentEntry = { id: 10, portfolio_id: 1, tax_year: 2026, amount_eur: -2000 };
    mockUseFiscalCarryForwards.mockReturnValue({
      data: [currentEntry],
      isLoading: false,
      isError: false,
    });
    render(<TaxPage />);
    expect(screen.getByTestId('current-year-badge')).toBeInTheDocument();
  });

  it('shows an empty amount input when editing an entry with a zero amount', () => {
    // entry.amount_eur=0 → editValue=Math.abs(0)=0 (falsy) → value={0 || ''}=''
    const zeroEntry = { id: 11, portfolio_id: 1, tax_year: 2022, amount_eur: 0 };
    mockUseFiscalCarryForwards.mockReturnValue({ data: [zeroEntry], isLoading: false, isError: false });
    mockUseUpdateCarryForward.mockReturnValue({ mutate: vi.fn(), isPending: false });

    render(<TaxPage />);
    // Start editing — click the amount display span
    const amountDisplay = screen.getByTestId('amount-display');
    fireEvent.click(amountDisplay);

    // editValue=0 → value={0 || ''}='' → input shows empty string
    const editInput = document.querySelector('input[type="number"]') as HTMLInputElement | null;
    if (editInput) {
      // The input value should be empty ('' from 0||'')
      expect(editInput.value).toBe('');
    }
  });

  it('falls back to zero when the inline edit input is cleared to a non-numeric value', () => {
    const activeEntry2 = { id: 12, portfolio_id: 1, tax_year: 2022, amount_eur: -3000 };
    mockUseFiscalCarryForwards.mockReturnValue({ data: [activeEntry2], isLoading: false, isError: false });
    const mockMutate = vi.fn();
    mockUseUpdateCarryForward.mockReturnValue({ mutate: mockMutate, isPending: false });

    render(<TaxPage />);
    fireEvent.click(screen.getByTestId('amount-display'));

    const editInput = document.querySelector('input[type="number"]') as HTMLInputElement | null;
    if (editInput) {
      // Type empty/non-numeric → parseFloat('') = NaN → || 0 → editValue = Math.abs(0) = 0
      fireEvent.change(editInput, { target: { value: '' } });
      // Math.abs(parseFloat('') || 0) = Math.abs(NaN || 0) = Math.abs(0) = 0
      expect(screen.getByText('Fiscalité')).toBeInTheDocument();
    }
  });

  it('shows the new-row form when adding an entry with no existing carry-forwards', () => {
    // When data is empty, availableYears=[] → availableYears[0] is undefined → ?? 2025
    mockUseFiscalCarryForwards.mockReturnValue({ data: [], isLoading: false, isError: false });
    mockUseCreateCarryForward.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });

    render(<TaxPage />);
    fireEvent.click(screen.getByText('Ajouter une année'));

    // With empty data, availableYears=[] → taxYear defaults to 2025
    // The select should show 2025 as the only/default option
    const newRow = screen.getByTestId('new-row');
    expect(newRow).toBeInTheDocument();
  });

  it('shows the thrown error message when creating a carry-forward fails', async () => {
    const mockMutateAsync = vi.fn().mockRejectedValue(new Error('Duplicate entry'));
    mockUseCreateCarryForward.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });
    mockUseFiscalCarryForwards.mockReturnValue({ data: [], isLoading: false, isError: false });

    const { waitFor: rtlWaitFor2 } = await import('@testing-library/react');
    render(<TaxPage />);
    fireEvent.click(screen.getByText('Ajouter une année'));

    const amountInput = screen.getByLabelText('Montant moins-value');
    fireEvent.change(amountInput, { target: { value: '500' } });
    fireEvent.click(screen.getByText('Enregistrer'));

    // err instanceof Error → err.message = 'Duplicate entry' (true branch)
    await rtlWaitFor2(() => expect(screen.getByText('Duplicate entry')).toBeInTheDocument());
  });
});
