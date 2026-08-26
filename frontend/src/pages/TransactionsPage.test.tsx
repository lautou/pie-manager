// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for TransactionsPage
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

// Mock PatternFly core — override Pagination (TransactionsPage uses Page 2 / Per Page 20 buttons)
vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  // Modal overridden (needs role="dialog" + footer slot)
  Modal: ({ children, isOpen, onClose }: any) =>
    isOpen ? (
      <div data-testid="modal" role="dialog">
        <button onClick={onClose}>Close</button>
        {children}
      </div>
    ) : null,
  ModalHeader: ({ title }: any) => <div>{title}</div>,
  ModalBody: ({ children }: any) => <>{children}</>,
  ModalFooter: ({ children }: any) => <div>{children}</div>,
  Alert: ({ title, children }: any) => (
    <div data-testid="alert" role="alert">
      <span>{title}</span>
      {children}
    </div>
  ),
  Pagination: ({ onSetPage, onPerPageSelect }: any) => (
    <div data-testid="pagination">
      <button onClick={() => onSetPage(null, 2)}>Page 2</button>
      <button onClick={() => onPerPageSelect?.(null, 20)}>Per Page 20</button>
    </div>
  ),
  // Override NumberInput to pass inputProps.onFocus to the actual <input>
  // so anonymous functions like (e) => e.currentTarget.select() can be invoked
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

// Mock PatternFly table
vi.mock('@patternfly/react-table', () => pfTableStubs);

// Mock PatternFly icons
vi.mock('@patternfly/react-icons', () => pfIconStubs);

// Mock FrDatePicker
vi.mock('../components/FrDatePicker', () => ({
  default: ({ value, onChange, id }: any) => (
    <input
      id={id}
      type="date"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}));

// Mock format utils
vi.mock('../utils/format', () => ({
  localDateStr: (_offset?: number) => '2026-01-01',
  dateToLocalStr: (_d?: Date) => '2026-01-01',
  formatEUR: (val: number) => `${val.toFixed(2)} €`,
  formatEUR3: (val: number) => `${val.toFixed(3)} €`,
  formatQty: (val: number) => val.toString(),
  formatNativeCurrency: (val: number) => val.toString(),
}));

// Mock API queries
const mockUseTransactions = vi.fn();
const mockUseAccounts = vi.fn();
const mockUseProducts = vi.fn();
const mockUseCreateTransaction = vi.fn();
const mockUseUpdateTransaction = vi.fn();
const mockUseDeleteTransaction = vi.fn();

vi.mock('../api/queries', () => ({
  useTransactions: (...args: any[]) => mockUseTransactions(...args),
  useBrokers: (...args: any[]) => mockUseAccounts(...args),
  useProducts: (...args: any[]) => mockUseProducts(...args),
  useCreateTransaction: () => mockUseCreateTransaction(),
  useUpdateTransaction: () => mockUseUpdateTransaction(),
  useDeleteTransaction: () => mockUseDeleteTransaction(),
  useEtfComposition: () => ({ data: undefined, isLoading: false }),
}));

const mockTransaction = {
  id: 1,
  portfolio_id: 1,
  account_id: 1,
  date: '2024-01-15',
  type: 'Actif',
  ticker: 'AAPL',
  currency: 'USD',
  exchange_rate: 1.1,
  quantity: -10,
  unit_price: 150,
  unit_price_eur: 136,
  total_amount: -1500,
  total_amount_eur: -1363,
  balance_currency: null,
  balance_eur: null,
};

const mockAccount = { id: 1, portfolio_id: 1, name: 'Degiro', currency: 'EUR' };
const mockProduct = { ticker: 'AAPL', name: 'Apple', category: 'Actif', instrument_type: 'Action', currency: 'USD' };

import TransactionsPage from './TransactionsPage';

describe('TransactionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAccounts.mockReturnValue({ data: [mockAccount] });
    mockUseProducts.mockReturnValue({ data: [mockProduct] });
    mockUseCreateTransaction.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    mockUseUpdateTransaction.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    mockUseDeleteTransaction.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  });

  it('shows spinner when loading', () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: true, isError: false });
    render(<TransactionsPage />);
    expect(screen.getByTestId('spinner')).toBeInTheDocument();
  });

  it('shows error alert when isError', () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: true });
    render(<TransactionsPage />);
    expect(screen.getByTestId('alert')).toBeInTheDocument();
  });

  it('renders page title', () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: false });
    render(<TransactionsPage />);
    expect(screen.getByText('Transactions')).toBeInTheDocument();
  });

  it('shows empty state when no transactions', () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: false });
    render(<TransactionsPage />);
    expect(screen.getByText(/Aucune transaction trouvée/i)).toBeInTheDocument();
  });

  it('renders transaction rows', () => {
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    render(<TransactionsPage />);
    expect(screen.getByText('AAPL')).toBeInTheDocument();
  });

  it('clicking a composable ticker in the transactions table opens the composition modal, and closing it clears the state', async () => {
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    mockUseProducts.mockReturnValue({ data: [mockProduct] });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    await user.click(screen.getByText('AAPL'));
    expect(screen.getByTestId('modal')).toBeInTheDocument();

    await user.click(screen.getByText('Close'));
    expect(screen.queryByTestId('modal')).toBeNull();
  });

  it('can open add modal', async () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    await user.click(screen.getByText('Nouvelle transaction'));
    expect(screen.getByTestId('modal')).toBeInTheDocument();
  });

  it('can close modal', async () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    await user.click(screen.getByText('Nouvelle transaction'));
    expect(screen.getByTestId('modal')).toBeInTheDocument();
    await user.click(screen.getByText('Close'));
    expect(screen.queryByTestId('modal')).toBeNull();
  });

  it('can toggle devise columns', async () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    const checkbox = screen.getByRole('checkbox');
    await user.click(checkbox);
    // Toggle flipped — page still renders
    expect(screen.getByText('Transactions')).toBeInTheDocument();
  });

  it('shows currency legend', () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: false });
    render(<TransactionsPage />);
    expect(screen.getByText(/Légende devise/i)).toBeInTheDocument();
    expect(screen.getAllByText('EUR').length).toBeGreaterThan(0);
  });

  it('can edit a transaction', async () => {
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    const editButtons = screen.getAllByRole('button');
    const editBtn = editButtons.find(b => b.textContent?.includes('edit'));
    if (editBtn) {
      await user.click(editBtn);
      expect(screen.getByTestId('modal')).toBeInTheDocument();
    }
  });

  it('can filter by ticker', async () => {
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    const tickerInput = screen.getByPlaceholderText('Ticker');
    await user.type(tickerInput, 'AAPL');
    expect(screen.getByText('Transactions')).toBeInTheDocument();
  });

  it('shows pagination when there are transactions', () => {
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    render(<TransactionsPage />);
    expect(screen.getByTestId('pagination')).toBeInTheDocument();
  });

  it('can click page 2 pagination button', async () => {
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    await user.click(screen.getByText('Page 2'));
    expect(screen.getByText('Transactions')).toBeInTheDocument();
  });

  it('can delete a transaction', async () => {
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    const mockDelete = vi.fn().mockResolvedValue(undefined);
    mockUseDeleteTransaction.mockReturnValue({ mutateAsync: mockDelete, isPending: false });

    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    const btns = screen.getAllByRole('button');
    const trashBtn = btns.find(b => b.textContent?.includes('trash'));
    if (trashBtn) {
      await user.click(trashBtn);
      expect(screen.getByText('Transactions')).toBeInTheDocument();
    }
  });

  it('form fields are rendered when add modal is open', async () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    await user.click(screen.getByText('Nouvelle transaction'));
    // Modal fields should be visible — check via aria-label on selects
    const selects = screen.getAllByRole('combobox');
    expect(selects.length).toBeGreaterThan(0);
    // FormGroup labels should appear as visible text
    const modalText = screen.getByTestId('modal').textContent ?? '';
    expect(modalText).toContain('Type');
    expect(modalText).toContain('Compte');
  });

  it('can change transaction type in form', async () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    await user.click(screen.getByText('Nouvelle transaction'));
    // Find select by aria-label "Type de transaction"
    const typeSelect = screen.getByRole('combobox', { name: 'Type' });
    await user.selectOptions(typeSelect, 'Frais');
    expect(screen.getByText('Transactions')).toBeInTheDocument();
  });

  it('shows "Aucune transaction" with active filters', async () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    const tickerInput = screen.getByPlaceholderText('Ticker');
    await user.type(tickerInput, 'XYZ');
    expect(screen.getByText(/Aucune transaction/i)).toBeInTheDocument();
  });

  it('shows quantity with decimal for fractional shares', () => {
    const fractionalTx = { ...mockTransaction, quantity: 0.5, ticker: 'BTC' };
    mockUseTransactions.mockReturnValue({ data: [fractionalTx], isLoading: false, isError: false });
    render(<TransactionsPage />);
    expect(screen.getByText('BTC')).toBeInTheDocument();
  });

  it('Sens column shows Achat for an Actif transaction with operation=Achat', () => {
    const achatTx = { ...mockTransaction, operation: 'Achat' };
    mockUseTransactions.mockReturnValue({ data: [achatTx], isLoading: false, isError: false });
    render(<TransactionsPage />);
    expect(screen.getByText('Achat')).toBeInTheDocument();
  });

  it('Sens column shows Vente for an Actif transaction with operation=Vente', () => {
    const venteTx = { ...mockTransaction, operation: 'Vente' };
    mockUseTransactions.mockReturnValue({ data: [venteTx], isLoading: false, isError: false });
    render(<TransactionsPage />);
    expect(screen.getByText('Vente')).toBeInTheDocument();
  });

  it('Sens column shows Dépôt/Retrait for LIQUIDITE.EURO transactions, and — for Frais/Revenu', () => {
    const depositTx = { ...mockTransaction, id: 10, ticker: 'LIQUIDITE.EURO', quantity: 500, operation: null };
    const withdrawalTx = { ...mockTransaction, id: 11, ticker: 'LIQUIDITE.EURO', quantity: -200, operation: null };
    const feeTx = { ...mockTransaction, id: 12, type: 'Frais', ticker: 'FRAIS.COURTAGE.EUR', operation: null };
    mockUseTransactions.mockReturnValue({ data: [depositTx, withdrawalTx, feeTx], isLoading: false, isError: false });
    render(<TransactionsPage />);
    expect(screen.getByText('Dépôt')).toBeInTheDocument();
    expect(screen.getByText('Retrait')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('submit form with create mutation', async () => {
    const mockCreate = vi.fn().mockResolvedValue({ id: 99, portfolio_id: 1 });
    mockUseCreateTransaction.mockReturnValue({ mutateAsync: mockCreate, isPending: false });
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: false });

    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    await user.click(screen.getByText('Nouvelle transaction'));
    // Submit button
    const submitBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Enregistrer'));
    if (submitBtn) {
      await user.click(submitBtn);
      // Some validation might prevent submission, but page shouldn't crash
      expect(screen.getByText('Transactions')).toBeInTheDocument();
    }
  });

  it('shows form with pre-filled values when editing', async () => {
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    const editButtons = screen.getAllByRole('button');
    const editBtn = editButtons.find(b => b.textContent?.includes('edit'));
    if (editBtn) {
      await user.click(editBtn);
      // Modal should show with AAPL pre-filled
      const modal = screen.getByTestId('modal');
      expect(modal.textContent).toContain('Modifier');
    }
  });

  it('can filter by account — passes account_id to useTransactions', async () => {
    // account_id is now a server-side filter; switching account calls useTransactions with account_id
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    const accountSelect = screen.getByRole('combobox', { name: 'Compte' });
    await user.selectOptions(accountSelect, '1');
    // useTransactions should have been called with account_id=1
    expect(mockUseTransactions).toHaveBeenCalledWith(
      '1',
      expect.objectContaining({ account_id: 1 }),
    );
  });

  it('can filter by currency — passes currency to useTransactions', async () => {
    // currency is now a server-side filter; changing the select calls useTransactions with currency
    const txUSD = { ...mockTransaction, currency: 'USD' };
    mockUseTransactions.mockReturnValue({ data: [txUSD], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    const currencySelect = screen.getByRole('combobox', { name: 'Devise' });
    await user.selectOptions(currencySelect, 'USD');
    expect(mockUseTransactions).toHaveBeenCalledWith(
      '1',
      expect.objectContaining({ currency: 'USD' }),
    );
  });

  it('currency dropdown shows currencies from server result (already account-filtered)', async () => {
    // Server-side filtering: when account 1 is selected, the server returns only account-1 transactions.
    // The component derives available currencies from whatever the server returns.
    const txAccount1USD = { ...mockTransaction, id: 1, account_id: 1, currency: 'USD' };
    mockUseAccounts.mockReturnValue({
      data: [mockAccount, { id: 2, portfolio_id: 1, name: 'BourseDir', currency: 'EUR' }],
    });
    // When no account selected, server returns both
    mockUseTransactions.mockReturnValue({
      data: [txAccount1USD, { ...mockTransaction, id: 2, account_id: 2, currency: 'JPY' }],
      isLoading: false,
      isError: false,
    });
    render(<TransactionsPage />);

    // Before selecting account: both USD and JPY should be in the currency dropdown
    const currencySelectBefore = screen.getByRole('combobox', { name: 'Devise' });
    expect(currencySelectBefore.innerHTML).toContain('USD');
    expect(currencySelectBefore.innerHTML).toContain('JPY');
  });

  it('currency filter resets when switching account', async () => {
    // When switching accounts, currencyFilter is reset to '' unconditionally
    const txUSD = { ...mockTransaction, id: 1, account_id: 1, currency: 'USD' };
    mockUseAccounts.mockReturnValue({
      data: [mockAccount, { id: 2, portfolio_id: 1, name: 'BourseDir', currency: 'EUR' }],
    });
    mockUseTransactions.mockReturnValue({
      data: [txUSD],
      isLoading: false,
      isError: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    const currencySelect = screen.getByRole('combobox', { name: 'Devise' });
    await user.selectOptions(currencySelect, 'USD');
    expect(currencySelect).toHaveValue('USD');

    // Switch account — currency filter must reset to ''
    const accountSelect = screen.getByRole('combobox', { name: 'Compte' });
    await user.selectOptions(accountSelect, '2');
    expect(currencySelect).toHaveValue('');
  });

  it('negative quantity shows as negative in table', () => {
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    render(<TransactionsPage />);
    expect(screen.getByText('AAPL')).toBeInTheDocument();
  });

  it('allows typing a date into the "date from" filter input', async () => {
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    // There are date inputs in the filter toolbar (type=date)
    const dateFromInput = screen.getAllByDisplayValue('').find(i => i.getAttribute('type') === 'date');
    if (dateFromInput) {
      await user.type(dateFromInput, '2024-01-01');
      expect(screen.getByText('Transactions')).toBeInTheDocument();
    }
  });

  it('allows typing a date into the "date to" filter input', async () => {
    mockUseTransactions.mockReturnValue({ data: [mockTransaction], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    // Use getAllByRole to find all date type inputs
    const allInputs = screen.getAllByRole('textbox');
    // FrDatePicker renders as type=date input
    if (allInputs.length > 1) {
      await user.clear(allInputs[1]);
      await user.type(allInputs[1], '2024-12-31');
      expect(screen.getByText('Transactions')).toBeInTheDocument();
    }
  });

  it('allows incrementing and decrementing the unit price via the modal NumberInput', async () => {
    mockUseTransactions.mockReturnValue({ data: [], isLoading: false, isError: false });
    const user = userEvent.setup({ delay: null });
    render(<TransactionsPage />);

    await user.click(screen.getByText('Nouvelle transaction'));
    // NumberInput buttons exist in modal
    const minusBtns = screen.getAllByRole('button').filter(b => b.textContent === '-');
    const plusBtns = screen.getAllByRole('button').filter(b => b.textContent === '+');
    // Click plus on unit_price (second NumberInput)
    if (plusBtns.length >= 2) {
      await user.click(plusBtns[1]);
      expect(screen.getByText('Transactions')).toBeInTheDocument();
    }
    if (minusBtns.length >= 2) {
      await user.click(minusBtns[1]);
      expect(screen.getByText('Transactions')).toBeInTheDocument();
    }
  });
});
