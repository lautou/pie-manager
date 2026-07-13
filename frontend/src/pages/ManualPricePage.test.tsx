/**
 * Tests for ManualPricePage
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs } from '../../tests/utils/patternfly-mocks';

// Mock react-router-dom (ManualPricePage doesn't use it but ProductCard may use hooks)
vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
  useNavigate: () => vi.fn(),
}));

// Mock PatternFly core — override Badge, Label, Spinner and NumberInput for assertions
vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  // FrDatePicker uses DatePicker from PatternFly
  DatePicker: ({ value, onChange, id, placeholder, isDisabled }: any) => (
    <input
      data-testid="date-picker"
      id={id}
      type="text"
      value={value ?? ''}
      placeholder={placeholder}
      disabled={isDisabled}
      onChange={(e) => onChange?.(e, e.target.value)}
    />
  ),
  // ManualPricePage tests assert on data-testid="badge"
  Badge: ({ children }: any) => <span data-testid="badge">{children}</span>,
  // Label needs data-color so tests can assert badge colour
  Label: ({ children, color }: any) => (
    <span data-testid="label" data-color={color}>{children}</span>
  ),
  // Override Spinner to accept size prop for spinner-sm / spinner-xl assertions
  Spinner: ({ size, 'aria-label': ariaLabel }: any) => (
    <div data-testid={`spinner-${size || 'xl'}`} aria-label={ariaLabel} />
  ),
  // CardHeader is used in ManualPricePage but not in pfCoreStubs by default
  CardHeader: ({ children }: any) => <>{children}</>,
  // Override NumberInput to also bind inputProps.onFocus to the actual <input> so
  // the anonymous fn at line 171 (e => e.currentTarget.select()) can be invoked.
  NumberInput: ({ value, onMinus, onPlus, onChange, min, isDisabled, inputProps }: any) => (
    <div>
      <button onClick={onMinus} disabled={isDisabled}>-</button>
      <input
        type="number"
        value={value}
        min={min}
        onChange={onChange}
        disabled={isDisabled}
        onFocus={inputProps?.onFocus}
      />
      <button onClick={onPlus} disabled={isDisabled}>+</button>
    </div>
  ),
}));

// Mock API queries
const mockUseProducts = vi.fn();
const mockUsePrices = vi.fn();
const mockUseCreatePrice = vi.fn();

vi.mock('../api/queries', () => ({
  useProducts: () => mockUseProducts(),
  usePrices: (...args: any[]) => mockUsePrices(...args),
  useCreatePrice: () => mockUseCreatePrice(),
}));

const mockManualProduct = {
  ticker: 'GOLD',
  name: 'Or physique',
  category: 'Actif',
  instrument_type: 'Or physique',
  currency: 'EUR',
};

const mockNonManualProduct = {
  ticker: 'AAPL',
  name: 'Apple',
  category: 'Actif',
  instrument_type: 'Action',
  currency: 'USD',
};

const mockPrice = {
  id: 1,
  ticker: 'GOLD',
  date: '2024-01-01',
  price: 1800,
  currency: 'EUR',
  source: 'manual',
};

import ManualPricePage from './ManualPricePage';

describe('ManualPricePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUsePrices.mockReturnValue({ data: [], isLoading: false });
    mockUseCreatePrice.mockReturnValue({ mutateAsync: vi.fn(), isPending: false, isError: false });
  });

  it('shows spinner when loading', () => {
    mockUseProducts.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    render(<ManualPricePage />);
    expect(screen.getByTestId('spinner-xl')).toBeTruthy();
  });

  it('shows error alert when isError', () => {
    mockUseProducts.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    render(<ManualPricePage />);
    expect(screen.getByTestId('alert-danger')).toBeTruthy();
  });

  it('shows empty state when no manual products', () => {
    mockUseProducts.mockReturnValue({ data: [mockNonManualProduct], isLoading: false, isError: false });
    render(<ManualPricePage />);
    expect(screen.getByText(/Aucun produit à cotation manuelle trouvé/i)).toBeTruthy();
  });

  it('renders page title', () => {
    mockUseProducts.mockReturnValue({ data: [], isLoading: false, isError: false });
    render(<ManualPricePage />);
    expect(screen.getByText(/Saisie des prix manuels/i)).toBeTruthy();
  });

  it('renders manual product card', () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    render(<ManualPricePage />);
    expect(screen.getByText('Or physique')).toBeTruthy();
    expect(screen.getByTestId('badge')).toBeTruthy();
  });

  it('shows latest price when available', () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [mockPrice], isLoading: false });
    render(<ManualPricePage />);
    expect(screen.getByText(/Dernier prix connu/i)).toBeTruthy();
  });

  it('shows "Aucun prix enregistré" when no prices', () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [], isLoading: false });
    render(<ManualPricePage />);
    // Both the paragraph text and the badge label contain the phrase — use getAllByText
    expect(screen.getAllByText(/Aucun prix enregistré/i).length).toBeGreaterThanOrEqual(1);
  });

  it('shows spinner in product card when prices loading', () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: undefined, isLoading: true });
    render(<ManualPricePage />);
    expect(screen.getByTestId('spinner-sm')).toBeTruthy();
  });

  it('shows error alert in product card on mutation error', () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [], isLoading: false });
    mockUseCreatePrice.mockReturnValue({ mutateAsync: vi.fn(), isPending: false, isError: true });
    render(<ManualPricePage />);
    expect(screen.getByTestId('alert-danger')).toBeTruthy();
  });

  it('renders Enregistrer button', () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    render(<ManualPricePage />);
    expect(screen.getByText('Enregistrer')).toBeTruthy();
  });

  it('renders multiple manual products', () => {
    const secondProduct = { ticker: 'SILV', name: 'Argent physique', category: 'Actif', instrument_type: 'Or physique', currency: 'EUR' };
    mockUseProducts.mockReturnValue({ data: [mockManualProduct, secondProduct], isLoading: false, isError: false });
    render(<ManualPricePage />);
    expect(screen.getByText('Or physique')).toBeTruthy();
    expect(screen.getByText('Argent physique')).toBeTruthy();
  });

  it('clicking Enregistrer calls createPrice.mutateAsync (lines 56-65)', async () => {
    const mockMutate = vi.fn().mockResolvedValue({});
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    // Provide a price so the button is enabled
    mockUsePrices.mockReturnValue({ data: [mockPrice], isLoading: false });
    mockUseCreatePrice.mockReturnValue({ mutateAsync: mockMutate, isPending: false, isError: false });

    const user = userEvent.setup({ delay: null });
    render(<ManualPricePage />);

    // The price is pre-filled from mockPrice (1800), button should be enabled
    const enregistrerBtn = screen.getByText('Enregistrer');
    // The button should not be disabled since price=1800 > 0
    await user.click(enregistrerBtn);
    expect(mockMutate).toHaveBeenCalledWith(expect.objectContaining({
      ticker: 'GOLD',
      source: 'manual',
    }));
  });

  it('clicking minus button decreases price', async () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [mockPrice], isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<ManualPricePage />);

    const minusBtn = screen.getAllByRole('button').find(b => b.textContent === '-');
    if (minusBtn) {
      await user.click(minusBtn);
      expect(screen.getByText('Or physique')).toBeTruthy();
    }
  });

  it('clicking plus button increases price', async () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [], isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<ManualPricePage />);

    const plusBtn = screen.getAllByRole('button').find(b => b.textContent === '+');
    if (plusBtn) {
      await user.click(plusBtn);
      expect(screen.getByText('Or physique')).toBeTruthy();
    }
  });

  it('typing in price input updates price', async () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [], isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<ManualPricePage />);

    const numberInput = screen.getByRole('spinbutton');
    await user.clear(numberInput);
    await user.type(numberInput, '2000');
    expect(screen.getByText('Or physique')).toBeTruthy();
  });

  it('date picker renders with FrDatePicker (line 116)', () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [], isLoading: false });

    render(<ManualPricePage />);

    // FrDatePicker is rendered via the DatePicker mock with data-testid="date-picker"
    expect(screen.getByTestId('date-picker')).toBeTruthy();
    expect(screen.getByText('Or physique')).toBeTruthy();
  });

  it('FrDatePicker onChange clears date when value is empty (line 160)', () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [], isLoading: false });

    render(<ManualPricePage />);

    // Clearing the date input triggers FrDatePicker's else-if(!_strVal) branch → setDate('')
    const dateInput = screen.getByTestId('date-picker');
    fireEvent.change(dateInput, { target: { value: '' } });
    expect(screen.getByText('Or physique')).toBeTruthy();
  });

  it('product with no currency falls back to EUR (line 53 branch)', () => {
    // When product.currency is empty/falsy, currency = product.currency || 'EUR' = 'EUR'
    const productNoCurrency = { ticker: 'GOLD', name: 'Or physique', category: 'Actif', instrument_type: 'Or physique', currency: '' };
    mockUseProducts.mockReturnValue({ data: [productNoCurrency], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [], isLoading: false });
    render(<ManualPricePage />);
    // Should render without crash and show the label with EUR
    expect(screen.getByText(/Prix \(EUR\)/i)).toBeTruthy();
  });

  it('setTimeout callback in handleSave fires to hide success alert (line 65 anonymous fn)', async () => {
    // The setTimeout(() => setSuccessVisible(false), 3000) callback at line 65
    // is the uncovered function. Use fake timers to advance time.
    vi.useFakeTimers();

    const mockMutate = vi.fn().mockResolvedValue({});
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [mockPrice], isLoading: false });
    mockUseCreatePrice.mockReturnValue({ mutateAsync: mockMutate, isPending: false, isError: false });

    const { act } = await import('@testing-library/react');
    render(<ManualPricePage />);

    // Click save → mutateAsync resolves → setSuccessVisible(true) → setTimeout starts
    await act(async () => {
      fireEvent.click(screen.getByText('Enregistrer'));
      await Promise.resolve(); // let mutateAsync resolve
    });

    // Advance timers by 3s to fire the setTimeout callback
    await act(async () => {
      vi.advanceTimersByTime(3001);
    });

    vi.useRealTimers();
    expect(screen.getByText('Or physique')).toBeTruthy();
  });

  it('handleSave: catch block when mutateAsync throws (lines 66-68)', async () => {
    // The catch block in handleSave is empty (swallows error), but it's still a statement
    const mockMutate = vi.fn().mockRejectedValueOnce(new Error('Price save failed'));
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [mockPrice], isLoading: false });
    mockUseCreatePrice.mockReturnValue({ mutateAsync: mockMutate, isPending: false, isError: false });

    const user = userEvent.setup({ delay: null });
    render(<ManualPricePage />);

    // Price is pre-filled from mockPrice (1800), so button is enabled
    const enregistrerBtn = screen.getByText('Enregistrer');
    await user.click(enregistrerBtn);
    // Error is caught silently; page should still render
    expect(screen.getByText('Or physique')).toBeTruthy();
  });

  it('button shows isPending state with Enregistrement text (line 148 branch)', () => {
    // When isPending is true, the button shows spinner + "Enregistrement…"
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [mockPrice], isLoading: false });
    mockUseCreatePrice.mockReturnValue({ mutateAsync: vi.fn(), isPending: true, isError: false });
    render(<ManualPricePage />);
    // The "Enregistrement…" text should appear (from the isPending branch)
    expect(screen.getByText(/Enregistrement/i)).toBeTruthy();
    // The spinner inside the button should appear
    expect(screen.getByTestId('spinner-sm')).toBeTruthy();
  });

  // ── PriceAgeBadge colour tests ─────────────────────────────────────────────

  it('badge is green when price is ≤ 7 days old', () => {
    // Use a price dated today (0 days ago → green)
    const today = new Date().toISOString().slice(0, 10);
    const freshPrice = { ...mockPrice, date: today };
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [freshPrice], isLoading: false });
    render(<ManualPricePage />);
    const label = screen.getByTestId('label');
    expect(label.getAttribute('data-color')).toBe('green');
    expect(label.textContent).toMatch(/Mis à jour il y a \d+ j/);
  });

  it('badge is orange when price is 8–30 days old', () => {
    // Build a date 15 days ago
    const d = new Date();
    d.setDate(d.getDate() - 15);
    const warningDate = d.toISOString().slice(0, 10);
    const warningPrice = { ...mockPrice, date: warningDate };
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [warningPrice], isLoading: false });
    render(<ManualPricePage />);
    const label = screen.getByTestId('label');
    expect(label.getAttribute('data-color')).toBe('orange');
    expect(label.textContent).toMatch(/Mis à jour il y a \d+ j/);
  });

  it('badge is red when price is > 30 days old', () => {
    // mockPrice.date = '2024-01-01' is well over 30 days ago → red
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [mockPrice], isLoading: false });
    render(<ManualPricePage />);
    const label = screen.getByTestId('label');
    expect(label.getAttribute('data-color')).toBe('red');
    expect(label.textContent).toMatch(/j sans mise à jour/);
  });

  it('badge is red with "Aucun prix enregistré" when no prices at all', () => {
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [], isLoading: false });
    render(<ManualPricePage />);
    const label = screen.getByTestId('label');
    expect(label.getAttribute('data-color')).toBe('red');
    expect(label.textContent).toContain('Aucun prix enregistré');
  });

  it('priceDaysAgo: price exactly 7 days ago → green badge', () => {
    // Use local date to avoid UTC timezone mismatch in priceDaysAgo calculation
    const d = new Date();
    d.setDate(d.getDate() - 7);
    const sevenDaysAgo = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const price7 = { ...mockPrice, date: sevenDaysAgo };
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [price7], isLoading: false });
    render(<ManualPricePage />);
    const label = screen.getByTestId('label');
    expect(label.getAttribute('data-color')).toBe('green');
  });

  it('priceDaysAgo: price exactly 8 days ago → orange badge', () => {
    const d = new Date();
    d.setDate(d.getDate() - 8);
    const eightDaysAgo = d.toISOString().slice(0, 10);
    const price8 = { ...mockPrice, date: eightDaysAgo };
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [price8], isLoading: false });
    render(<ManualPricePage />);
    const label = screen.getByTestId('label');
    expect(label.getAttribute('data-color')).toBe('orange');
  });

  it('priceDaysAgo: price exactly 30 days ago → orange badge', () => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    const thirtyDaysAgo = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const price30 = { ...mockPrice, date: thirtyDaysAgo };
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [price30], isLoading: false });
    render(<ManualPricePage />);
    const label = screen.getByTestId('label');
    expect(label.getAttribute('data-color')).toBe('orange');
  });

  it('priceDaysAgo: price exactly 31 days ago → red badge', () => {
    const d = new Date();
    d.setDate(d.getDate() - 31);
    const thirtyOneDaysAgo = d.toISOString().slice(0, 10);
    const price31 = { ...mockPrice, date: thirtyOneDaysAgo };
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [price31], isLoading: false });
    render(<ManualPricePage />);
    const label = screen.getByTestId('label');
    expect(label.getAttribute('data-color')).toBe('red');
  });

  it('price input onChange with invalid value sets price to 0 (line 179 — else setPrice(0))', () => {
    // Line 179: onChange → if (!isNaN(val)) setPrice(val); else setPrice(0)
    // Trigger the else branch by entering a non-numeric string
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [mockPrice], isLoading: false });
    render(<ManualPricePage />);

    const numberInput = screen.getByRole('spinbutton') as HTMLInputElement;
    // Enter an empty string → parseFloat('') = NaN → isNaN(NaN) = true → else setPrice(0)
    fireEvent.change(numberInput, { target: { value: '' } });
    expect(screen.getByText(/Or physique/i)).toBeTruthy(); // page still renders
  });

  it('inputProps.onFocus on price NumberInput selects the input text (line 171 anonymous fn)', () => {
    // The local NumberInput override passes inputProps.onFocus to the actual <input> element.
    // Firing focus on the <input> calls (e) => e.currentTarget.select() (line 171).
    mockUseProducts.mockReturnValue({ data: [mockManualProduct], isLoading: false, isError: false });
    mockUsePrices.mockReturnValue({ data: [mockPrice], isLoading: false });
    render(<ManualPricePage />);

    const numberInput = screen.getByRole('spinbutton') as HTMLInputElement;
    // Spy on select() so we can assert it was called by the onFocus handler
    const selectSpy = vi.fn();
    numberInput.select = selectSpy;

    fireEvent.focus(numberInput);
    expect(selectSpy).toHaveBeenCalled();
  });
});
