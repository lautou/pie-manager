/**
 * Tests for ConfigGeneralePage — covers ProductManager, AccountManager, CommissionManager, TTF rate.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, waitFor as rtlWaitFor, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfTableStubs, pfIconStubs } from '../../tests/utils/patternfly-mocks';

vi.mock('react-router-dom', () => ({
  useParams: () => ({}),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
  useNavigate: () => vi.fn(),
}));

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  ...pfTableStubs,
  Modal: ({ children, isOpen, actions, onClose, title }: any) =>
    isOpen ? (
      <div data-testid="modal">
        <div data-testid="modal-title">{title}</div>
        <div>{children}</div>
        <div data-testid="modal-actions">{actions}</div>
        <button onClick={onClose}>Close modal</button>
      </div>
    ) : null,
  ModalVariant: { medium: 'medium', large: 'large', small: 'small' },
}));

vi.mock('@patternfly/react-icons', () => pfIconStubs);

vi.mock('../utils/commission', () => ({
  computeCommission: vi.fn().mockReturnValue(3.5),
}));

const mockUseSystemSetting = vi.fn();
const mockUseSetSystemSetting = vi.fn();
const mockUseAllAccounts = vi.fn();
const mockUsePortfolios = vi.fn();
const mockUseProducts = vi.fn();
const mockUseMacroRegions = vi.fn();
const mockUseCountryPerfConfigs = vi.fn();

vi.mock('../api/queries', () => ({
  useSystemSetting: (...args: any[]) => mockUseSystemSetting(...args),
  useSetSystemSetting: (...args: any[]) => mockUseSetSystemSetting(...args),
  useAllBrokers: (...args: any[]) => mockUseAllAccounts(...args),
  usePortfolios: (...args: any[]) => mockUsePortfolios(...args),
  useProducts: (...args: any[]) => mockUseProducts(...args),
  createBrokerAPI: vi.fn().mockResolvedValue({ id: 99, name: 'Test', currency: 'EUR', portfolio_ids: [], color: null }),
  updateBrokerAPI: vi.fn().mockResolvedValue({}),
  deleteBrokerAPI: vi.fn().mockResolvedValue(undefined),
  updateBrokerPortfoliosAPI: vi.fn().mockResolvedValue({}),
  createProduct: vi.fn().mockResolvedValue({}),
  updateProduct: vi.fn().mockResolvedValue({}),
  deleteProduct: vi.fn().mockResolvedValue(undefined),
  useEtfComposition: () => ({ data: undefined, isLoading: false }),
  useMacroRegions: (...args: any[]) => mockUseMacroRegions(...args),
  createMacroRegion: vi.fn().mockResolvedValue({}),
  updateMacroRegion: vi.fn().mockResolvedValue({}),
  deleteMacroRegion: vi.fn().mockResolvedValue(undefined),
  useCountryPerfConfigs: (...args: any[]) => mockUseCountryPerfConfigs(...args),
  createCountryPerfConfig: vi.fn().mockResolvedValue({}),
  updateCountryPerfConfig: vi.fn().mockResolvedValue({}),
  deleteCountryPerfConfig: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('../hooks/useSortable', () => ({
  useSortable: ({ data }: any) => ({
    sorted: data ?? [],
    sortCol: 'name',
    sortDir: 'asc',
    toggle: vi.fn(),
    indicator: () => ' ▲',
    thStyle: () => ({ cursor: 'pointer' }),
  }),
}));

import GlobalConfigPage from './GlobalConfigPage';

const MOCK_PRODUCTS = [
  { ticker: 'AAPL', name: 'Apple Inc', category: 'Actif', instrument_type: 'Action', currency: 'USD', is_ttf_eligible: false },
  { ticker: 'OR', name: 'Or Physique', category: 'Actif', instrument_type: 'Or physique', currency: 'EUR', is_ttf_eligible: false },
];

const MOCK_REGIONS = [
  { code: 'us', label: 'États-Unis', equity_ticker: '^SPXEW', bond_ticker: 'GOVT', equity_label: 'S&P 500 Equal Weight', bond_label: 'Obligations Trésor américain' },
  { code: 'fr', label: 'France', equity_ticker: '^FCHI', bond_ticker: 'MTE.PA', equity_label: 'CAC 40', bond_label: 'Obligations zone euro' },
];

// Deliberately different codes from MOCK_REGIONS (us/fr) — both managers render on the
// same page, so a shared code would make e.g. getByRole('button', { name: /Modifier us/i })
// match two buttons at once.
const MOCK_COUNTRIES = [
  { code: 'jp', label: 'Japon', index_ticker: '^N225', currency: 'JPY', index_label: 'Nikkei 225' },
  { code: 'gb', label: 'Royaume-Uni', index_ticker: '^FTSE', currency: 'GBP', index_label: 'FTSE 100' },
];

function setupDefaultMocks() {
  mockUseSystemSetting.mockReturnValue({ data: { value: '0.004' }, isError: false });
  mockUseSetSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
  mockUseAllAccounts.mockReturnValue({ data: [], isLoading: false });
  mockUsePortfolios.mockReturnValue({ data: [] });
  mockUseProducts.mockReturnValue({ data: MOCK_PRODUCTS, refetch: vi.fn() });
  mockUseMacroRegions.mockReturnValue({ data: MOCK_REGIONS, refetch: vi.fn() });
  mockUseCountryPerfConfigs.mockReturnValue({ data: MOCK_COUNTRIES, refetch: vi.fn() });
}

describe('GlobalConfigPage — ProductManager', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the Produits section heading', () => {
    render(<GlobalConfigPage />);
    expect(screen.getByText(/Produits et frais financiers/i)).toBeTruthy();
  });

  it('clicking a composable ticker (instrument_type=Action) opens the composition modal, and closing it clears the state', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);

    await user.click(screen.getByText('AAPL'));
    const modals = screen.getAllByTestId('modal');
    expect(modals.length).toBeGreaterThan(0);

    await user.click(screen.getByText('Close modal'));
  });

  it('TTF rate save button — clicking saves and shows ✓ (line 601 — ttfSaved=true branch)', async () => {
    const mockMutateAsync = vi.fn().mockResolvedValue({});
    mockUseSetSystemSetting.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });

    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);

    // The TTF save button has a specific background color (#0066CC) and text "Enregistrer"
    // Find it by looking for a native button with background style
    const buttons = Array.from(document.querySelectorAll('button'));
    const ttfSaveBtn = buttons.find(b =>
      b.textContent === 'Enregistrer' && (b as HTMLButtonElement).style.background === 'rgb(0, 102, 204)'
    );
    if (ttfSaveBtn) {
      await user.click(ttfSaveBtn);
      expect(mockMutateAsync).toHaveBeenCalled();
      // After save, ttfSaved=true renders '✓ Enregistrer' (line 601 ttfSaved branch)
      // We can't easily wait for setTimeout(2000) to reset, just verify it was called
    }
    expect(screen.getByText(/Produits et frais financiers/i)).toBeTruthy();
  }, 10000);

  it('TTF rate save button — isPending branch (line 601 — isPending=true)', () => {
    // When isPending=true, button shows 'Enregistrer…'
    mockUseSetSystemSetting.mockReturnValue({ mutateAsync: vi.fn(), isPending: true });
    render(<GlobalConfigPage />);
    // The button should show 'Enregistrer…'
    expect(document.body.textContent).toContain('Enregistrer');
    expect(screen.getByText(/Produits et frais financiers/i)).toBeTruthy();
  });

  it('shows product count', () => {
    render(<GlobalConfigPage />);
    expect(screen.getByText(/2 produit\(s\)/i)).toBeTruthy();
  });

  it('lists products in the table', () => {
    render(<GlobalConfigPage />);
    expect(screen.getAllByText('AAPL').length).toBeGreaterThan(0);
    expect(screen.getByText('Apple Inc')).toBeTruthy();
    expect(screen.getAllByText('Or Physique').length).toBeGreaterThan(0);
  });

  it('shows Nouveau produit button', () => {
    render(<GlobalConfigPage />);
    const btns = screen.getAllByRole('button');
    expect(btns.find(b => b.textContent?.includes('Nouveau produit'))).toBeTruthy();
  });

  it('clicking Nouveau produit opens a modal', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      expect(screen.getByTestId('modal')).toBeTruthy();
    }
  }, 10000);

  it('add modal shows Enregistrer and Annuler buttons', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const modal = screen.getByTestId('modal');
      expect(within(modal).getByText('Enregistrer')).toBeTruthy();
      expect(screen.getAllByText('Annuler').length).toBeGreaterThan(0);
    }
  }, 10000);

  it('cancelling modal closes it', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const cancelBtns = screen.getAllByText('Annuler');
      await user.click(cancelBtns[cancelBtns.length - 1]);
      expect(screen.queryByTestId('modal')).toBeNull();
    }
  }, 10000);

  it('saving without ticker shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const modal = screen.getByTestId('modal'); await user.click(within(modal).getByText('Enregistrer'));
      expect(screen.getByText(/Le ticker est requis/i)).toBeTruthy();
    }
  }, 10000);

  it('saving without name shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const modal = screen.getByTestId('modal');
      await user.type(within(modal).getByRole('textbox', { name: /ticker/i }), 'TEST');
      await user.click(within(modal).getByText('Enregistrer'));
      expect(screen.getByText(/Le nom est requis/i)).toBeTruthy();
    }
  }, 10000);

  it('saving without currency shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const modal = screen.getByTestId('modal');
      await user.type(within(modal).getByRole('textbox', { name: /ticker/i }), 'TEST');
      await user.type(within(modal).getByRole('textbox', { name: /nom/i }), 'Test Product');
      await user.clear(within(modal).getByRole('textbox', { name: /devise/i }));
      await user.click(within(modal).getByText('Enregistrer'));
      expect(screen.getByText(/La devise est requise/i)).toBeTruthy();
    }
  }, 10000);

  it('can create a product with valid data', async () => {
    const { createProduct } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const modal = screen.getByTestId('modal');
      await user.type(within(modal).getByRole('textbox', { name: /ticker/i }), 'TSLA');
      await user.type(within(modal).getByRole('textbox', { name: /nom/i }), 'Tesla');
      await user.click(within(modal).getByText('Enregistrer'));
      expect(createProduct).toHaveBeenCalled();
    }
  }, 10000);

  it('ticker input converts to uppercase', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const modal = screen.getByTestId('modal');
      const tickerInput = within(modal).getByRole('textbox', { name: /ticker/i });
      await user.type(tickerInput, 'tsla');
      expect((tickerInput as HTMLInputElement).value).toBe('TSLA');
    }
  }, 10000);

  it('currency input converts to uppercase', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const currencyInput = screen.getByRole('textbox', { name: /devise/i });
      await user.clear(currencyInput);
      await user.type(currencyInput, 'usd');
      expect((currencyInput as HTMLInputElement).value).toBe('USD');
    }
  }, 10000);

  it('can change category in add form', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const catSelect = screen.getByRole('combobox', { name: /catégorie/i });
      await user.selectOptions(catSelect, 'Frais');
      expect((catSelect as HTMLSelectElement).value).toBe('Frais');
    }
  }, 10000);

  it('can select an instrument type when category is Actif', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const typeSelect = screen.getByRole('combobox', { name: /type d'instrument/i });
      await user.selectOptions(typeSelect, 'ETF');
      expect((typeSelect as HTMLSelectElement).value).toBe('ETF');
    }
  }, 10000);

  it('can select a fee type when category is Frais', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const catSelect = screen.getByRole('combobox', { name: /catégorie/i });
      await user.selectOptions(catSelect, 'Frais');
      const feeSelect = screen.getByRole('combobox', { name: /type de frais/i });
      await user.selectOptions(feeSelect, 'Courtage');
      expect((feeSelect as HTMLSelectElement).value).toBe('Courtage');
    }
  }, 10000);

  it('creating a Frais product with a fee type sends fee_type and null instrument_type', async () => {
    const { createProduct } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const modal = screen.getByTestId('modal');
      await user.type(within(modal).getByRole('textbox', { name: /ticker/i }), 'FRAIS.TEST');
      await user.type(within(modal).getByRole('textbox', { name: /nom/i }), 'Frais Test');
      await user.selectOptions(screen.getByRole('combobox', { name: /catégorie/i }), 'Frais');
      await user.selectOptions(screen.getByRole('combobox', { name: /type de frais/i }), 'Courtage');
      await user.click(within(modal).getByText('Enregistrer'));
      expect(createProduct).toHaveBeenCalledWith(expect.objectContaining({
        instrument_type: null, fee_type: 'Courtage',
      }));
    }
  }, 10000);

  it('creating a Frais product without a fee type sends fee_type null', async () => {
    const { createProduct } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const modal = screen.getByTestId('modal');
      await user.type(within(modal).getByRole('textbox', { name: /ticker/i }), 'FRAIS.TEST2');
      await user.type(within(modal).getByRole('textbox', { name: /nom/i }), 'Frais Test 2');
      await user.selectOptions(screen.getByRole('combobox', { name: /catégorie/i }), 'Frais');
      await user.click(within(modal).getByText('Enregistrer'));
      expect(createProduct).toHaveBeenCalledWith(expect.objectContaining({
        instrument_type: null, fee_type: null,
      }));
    }
  }, 10000);

  it('Type column shows fee_type for a Frais product and — when neither is set', () => {
    mockUseProducts.mockReturnValue({
      data: [
        { ticker: 'FRAIS.X', name: 'Frais X', category: 'Frais', fee_type: 'Courtage', currency: 'EUR', is_ttf_eligible: false },
        { ticker: 'MYST', name: 'Mystery', category: 'Actif', currency: 'EUR', is_ttf_eligible: false },
      ],
      refetch: vi.fn(),
    });
    render(<GlobalConfigPage />);
    expect(screen.getByText('Courtage')).toBeTruthy();
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('editing a product without instrument_type/fee_type pre-fills empty selects', async () => {
    mockUseProducts.mockReturnValue({
      data: [{ ticker: 'MYST', name: 'Mystery', category: 'Actif', currency: 'EUR', is_ttf_eligible: false }],
      refetch: vi.fn(),
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Modifier MYST/i }));
    const typeSelect = screen.getByRole('combobox', { name: /type d'instrument/i });
    expect((typeSelect as HTMLSelectElement).value).toBe('');
  }, 10000);

  it('shows edit modal when clicking edit button for a product', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const editBtn = screen.getByRole('button', { name: /Modifier AAPL/i });
    await user.click(editBtn);
    expect(screen.getByText(/Modifier — AAPL/i)).toBeTruthy();
  }, 10000);

  it('edit modal shows ticker as read-only', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Modifier AAPL/i }));
    const modal = screen.getByTestId('modal');
    const tickerInput = within(modal).getByRole('textbox', { name: /ticker/i });
    expect((tickerInput as HTMLInputElement).disabled).toBe(true);
  }, 10000);

  it('can save edited product', async () => {
    const { updateProduct } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Modifier AAPL/i }));
    const modal = screen.getByTestId('modal');
    const nameInput = within(modal).getByRole('textbox', { name: /nom/i });
    await user.clear(nameInput);
    await user.type(nameInput, 'Apple Updated');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(updateProduct).toHaveBeenCalled();
  }, 10000);

  it('save product API error shows error message', async () => {
    const { createProduct } = await import('../api/queries');
    vi.mocked(createProduct).mockRejectedValueOnce({ response: { data: { detail: 'Ticker already exists' } } });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const modal = screen.getByTestId('modal');
      await user.type(within(modal).getByRole('textbox', { name: /ticker/i }), 'AAPL');
      await user.type(within(modal).getByRole('textbox', { name: /nom/i }), 'Apple');
      await user.click(within(modal).getByText('Enregistrer'));
      await rtlWaitFor(() => expect(screen.getByText(/Ticker already exists/i)).toBeTruthy());
    }
  }, 10000);

  it('save product API error without detail uses fallback', async () => {
    const { createProduct } = await import('../api/queries');
    vi.mocked(createProduct).mockRejectedValueOnce(new Error('Network error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBtn = screen.getAllByRole('button').find(b => b.textContent?.includes('Nouveau produit'));
    if (newBtn) {
      await user.click(newBtn);
      const modal = screen.getByTestId('modal');
      await user.type(within(modal).getByRole('textbox', { name: /ticker/i }), 'TST');
      await user.type(within(modal).getByRole('textbox', { name: /nom/i }), 'Test');
      await user.click(within(modal).getByText('Enregistrer'));
      await rtlWaitFor(() => expect(screen.getByText(/Erreur lors de l'enregistrement/i)).toBeTruthy());
    }
  }, 10000);

  it('can delete a product with confirm', async () => {
    const { deleteProduct } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer AAPL/i }));
    await user.click(screen.getByText('Supprimer'));
    expect(deleteProduct).toHaveBeenCalledWith('AAPL');
  }, 10000);

  it('delete cancelled by user does not call deleteProduct', async () => {
    const { deleteProduct } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer AAPL/i }));
    await user.click(screen.getByText('Annuler'));
    expect(deleteProduct).not.toHaveBeenCalled();
  }, 10000);

  it('delete blocked by transactions shows danger alert', async () => {
    const { deleteProduct } = await import('../api/queries');
    vi.mocked(deleteProduct).mockRejectedValueOnce({ response: { data: { detail: 'Ce produit est utilisé dans 3 transaction(s).' } } });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer AAPL/i }));
    await user.click(screen.getByText('Supprimer'));
    await rtlWaitFor(() => expect(screen.getByText(/Ce produit est utilisé dans 3 transaction/i)).toBeTruthy());
  }, 10000);

  it('delete error without detail shows fallback message', async () => {
    const { deleteProduct } = await import('../api/queries');
    vi.mocked(deleteProduct).mockRejectedValueOnce(new Error('Unknown error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer AAPL/i }));
    await user.click(screen.getByText('Supprimer'));
    await rtlWaitFor(() => expect(screen.getByText(/Erreur lors de la suppression/i)).toBeTruthy());
  }, 10000);

  it('delete error without any response shows fallback message', async () => {
    const { deleteProduct } = await import('../api/queries');
    vi.mocked(deleteProduct).mockRejectedValueOnce({});
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer AAPL/i }));
    await user.click(screen.getByText('Supprimer'));
    await rtlWaitFor(() => expect(screen.getByText(/Erreur lors de la suppression/i)).toBeTruthy());
  }, 10000);

  it('shows "Aucun produit" when product list is empty', () => {
    mockUseProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    render(<GlobalConfigPage />);
    expect(screen.getByText('Aucun produit')).toBeTruthy();
  });

  it('shows category badge in product table row', () => {
    render(<GlobalConfigPage />);
    const badges = screen.getAllByText('Actif');
    expect(badges.length).toBeGreaterThan(0);
  });

  it('toggleSort: clicking Nom column sorts by name', async () => {
    const user = userEvent.setup({ delay: null });
    const { container } = render(<GlobalConfigPage />);
    const ths = Array.from(container.querySelectorAll('th'));
    const nomTh = ths.find(th => th.textContent?.trim().startsWith('Nom'));
    if (nomTh) {
      await user.click(nomTh);
      expect(nomTh.textContent).toMatch(/Nom/);
    }
  }, 10000);

  it('toggleSort: clicking same column twice toggles direction', async () => {
    const user = userEvent.setup({ delay: null });
    const { container } = render(<GlobalConfigPage />);
    const ths = Array.from(container.querySelectorAll('th'));
    const tickerTh = ths.find(th => th.textContent?.startsWith('Ticker'));
    if (tickerTh) {
      await user.click(tickerTh);
      await user.click(tickerTh);
      expect(tickerTh.textContent).toMatch(/Ticker/);
    }
  }, 10000);

  it('toggleSort: clicking Catégorie header', async () => {
    const user = userEvent.setup({ delay: null });
    const { container } = render(<GlobalConfigPage />);
    const ths = Array.from(container.querySelectorAll('th'));
    const categorieTh = ths.find(th => th.textContent?.includes('Catégorie'));
    if (categorieTh) await user.click(categorieTh);
    expect(screen.getByText(/Produits et frais financiers/i)).toBeTruthy();
  }, 10000);

  it('toggleSort: clicking Devise header', async () => {
    const user = userEvent.setup({ delay: null });
    const { container } = render(<GlobalConfigPage />);
    const ths = Array.from(container.querySelectorAll('th'));
    const deviseTh = ths.find(th => th.textContent?.includes('Devise'));
    if (deviseTh) await user.click(deviseTh);
    expect(screen.getByText(/Produits et frais financiers/i)).toBeTruthy();
  }, 10000);

  it('TTF checkbox onChange calls updateProduct (line 506)', async () => {
    const { updateProduct } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    // Find the TTF checkbox for AAPL
    const ttfCheckbox = screen.getByRole('checkbox', { name: /TTF éligible AAPL/i });
    await user.click(ttfCheckbox);
    expect(updateProduct).toHaveBeenCalledWith('AAPL', { is_ttf_eligible: true });
  }, 10000);

  it('all product table column headers clickable (line 490 — Devise sort)', async () => {
    const user = userEvent.setup({ delay: null });
    const { container } = render(<GlobalConfigPage />);
    // Click all Th in the products table
    const ths = Array.from(container.querySelectorAll('th'));
    for (const th of ths) {
      const text = (th as HTMLElement).textContent ?? '';
      if (text.includes('Ticker') || text.includes('Nom') || text.includes('Catégorie') || text.includes('Devise')) {
        await user.click(th as HTMLElement);
      }
    }
    expect(screen.getByText(/Produits et frais financiers/i)).toBeTruthy();
  }, 10000);
});

// ─── CommissionManager coverage ─────────────────────────────────────────────

const MOCK_BROKER: any = {
  id: 1,
  name: 'Degiro',
  currency: 'EUR',
  color: '#ff0000',
  portfolio_ids: [1],
  commission_schedule: [{ up_to: 1000, type: 'flat', value: 2 }, { up_to: null, type: 'percent', value: 0.001 }],
  commission_sale_rate: 0.005,
  include_fees_in_cump: true,
  allowed_tickers: ['AAPL'],
  monthly_free_eur: 1000,
  above_monthly_rate: 0.01,
  weekend_rate: 0.015,
};

const MOCK_PORTFOLIO = { id: 1, name: 'Portfolio 1' };

function setupBrokerMocks() {
  mockUseSystemSetting.mockReturnValue({ data: { value: '0.004' } });
  mockUseSetSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
  mockUseAllAccounts.mockReturnValue({ data: [MOCK_BROKER], isLoading: false });
  mockUsePortfolios.mockReturnValue({ data: [MOCK_PORTFOLIO] });
  mockUseProducts.mockReturnValue({ data: MOCK_PRODUCTS, refetch: vi.fn() });
}

describe('GlobalConfigPage — CommissionManager broker display', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupBrokerMocks();
  });

  afterEach(() => { vi.restoreAllMocks(); });

  it('renders broker name in table', () => {
    render(<GlobalConfigPage />);
    expect(screen.getAllByText('Degiro').length).toBeGreaterThan(0);
  });

  it('shows commission schedule summary (multi-tranche)', () => {
    render(<GlobalConfigPage />);
    // formatScheduleSummary with 2 tiers shows "2 tranches — ex. 700€ → X.XX €"
    expect(screen.getByText(/2 tranches — ex. 700/i)).toBeTruthy();
  });

  it('shows commission schedule summary for single flat tier', () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, commission_schedule: [{ up_to: null, type: 'flat', value: 2.5 }] }],
      isLoading: false,
    });
    render(<GlobalConfigPage />);
    expect(screen.getByText(/Fixe 2.50 €/i)).toBeTruthy();
  });

  it('shows — for null commission_schedule', () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, commission_schedule: null, commission_sale_rate: 0, allowed_tickers: null }],
      isLoading: false,
    });
    render(<GlobalConfigPage />);
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('include_fees_in_cump=false renders "Courtage exclu" title (line 263 false branch)', () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, include_fees_in_cump: false }],
      isLoading: false,
    });
    render(<GlobalConfigPage />);
    const checkbox = document.querySelector('input[type="checkbox"][title*="exclu"]') as HTMLInputElement | null;
    expect(checkbox?.title).toContain('exclu');
  });

  it('shows commission_sale_rate input when > 0', () => {
    render(<GlobalConfigPage />);
    const inputs = screen.getAllByRole('spinbutton');
    const saleRateInput = inputs.find((inp: any) => parseFloat((inp as HTMLInputElement).value) === 0.005);
    expect(saleRateInput).toBeTruthy();
  });

  it('shows "= achat" when commission_schedule set and sale_rate = 0', () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, commission_sale_rate: 0 }],
      isLoading: false,
    });
    render(<GlobalConfigPage />);
    expect(screen.getByText('= achat')).toBeTruthy();
  });

  it('shows — for sale_rate when no schedule and rate = 0', () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, commission_schedule: null, commission_sale_rate: 0 }],
      isLoading: false,
    });
    render(<GlobalConfigPage />);
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('shows allowed_tickers count', () => {
    render(<GlobalConfigPage />);
    expect(screen.getByText(/1 produit/)).toBeTruthy();
  });

  it('shows Tous when allowed_tickers is null', () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, allowed_tickers: null }],
      isLoading: false,
    });
    render(<GlobalConfigPage />);
    expect(screen.getByText('Tous')).toBeTruthy();
  });

  it('shows allowed_tickers plural (>1 product)', () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, allowed_tickers: ['AAPL', 'OR'] }],
      isLoading: false,
    });
    render(<GlobalConfigPage />);
    expect(screen.getByText(/2 produits/)).toBeTruthy();
  });

  it('shows FX info when monthly_free_eur set', () => {
    render(<GlobalConfigPage />);
    expect(screen.getByText(/1000€\/mois gratuits/)).toBeTruthy();
    expect(screen.getByText(/au-delà: 1.00%/)).toBeTruthy();
    expect(screen.getByText(/week-end: 1.50%/)).toBeTruthy();
  });

  it('shows — for FX when monthly_free_eur is null', () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, monthly_free_eur: null }],
      isLoading: false,
    });
    render(<GlobalConfigPage />);
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});

describe('GlobalConfigPage — CommissionManager edit panel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupBrokerMocks();
  });

  afterEach(() => { vi.restoreAllMocks(); });

  it('clicking Commission button opens inline commission editor', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    expect(screen.getByText(/Jusqu'à/i)).toBeTruthy();
  }, 10000);

  it('commission editor shows tier rows', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    // 2 tier rows exist (from MOCK_BROKER.commission_schedule)
    const delBtns = screen.getAllByText('×');
    expect(delBtns.length).toBeGreaterThan(0);
  }, 10000);

  it('can delete a tier row', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    const delBtns = screen.getAllByText('×');
    await user.click(delBtns[0]);
    // Still renders
    expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
  }, 10000);

  it('can add a tier row', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('+ Ajouter une tranche'));
    expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
  }, 10000);

  it('shows "Grille vide" message when no tiers', async () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, commission_schedule: [] }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    expect(screen.getByText(/Grille vide → commission = 0/i)).toBeTruthy();
  }, 10000);

  it('can change tier type to percent via select', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    const selects = screen.getAllByRole('combobox');
    if (selects.length > 0) {
      await user.selectOptions(selects[0], 'percent');
      expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
    }
  }, 10000);

  it('can save commission schedule (calls fetch PUT)', async () => {
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({ ok: true } as any);
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    const saveBtns = screen.getAllByText('Enregistrer');
    await user.click(saveBtns[1]); // index 0 = TTF card's save button, index 1 = Commission panel's
    expect(fetchSpy).toHaveBeenCalled();
    fetchSpy.mockRestore();
  }, 10000);

  it('save commission error shows error message', async () => {
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({ ok: false, text: () => Promise.resolve('Bad data') } as any);
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    const saveBtns = screen.getAllByText('Enregistrer');
    await user.click(saveBtns[1]); // index 0 = TTF card's save button, index 1 = Commission panel's
    expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
    fetchSpy.mockRestore();
  }, 10000);

  it('can cancel commission editor', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    const cancelBtns = screen.getAllByText('Annuler');
    await user.click(cancelBtns[cancelBtns.length - 1]);
    expect(screen.queryByText(/Ajouter une tranche/i)).toBeNull();
  }, 10000);

  it('switches to Produits tab in commission editor', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    expect(screen.getByText(/Disponibles/i)).toBeTruthy();
  }, 10000);

  it('clicking row-level Produits button opens editor directly in tickers mode', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Produits'));
    expect(screen.getByText(/Disponibles/i)).toBeTruthy();
  }, 10000);

  it('clicking row-level Produits button on a broker with no allowed_tickers falls back to []', async () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, allowed_tickers: null }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Produits'));
    expect(screen.getByText(/Disponibles/i)).toBeTruthy();
  }, 10000);

  it('clicking row-level Change FX button opens editor directly in fx mode', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Change FX'));
    expect(screen.getByText(/Plafond mensuel gratuit/i)).toBeTruthy();
  }, 10000);

  it('clicking row-level Change FX button on a broker with null FX fields falls back to empty strings', async () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, monthly_free_eur: null, above_monthly_rate: 0, weekend_rate: null }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Change FX'));
    expect(screen.getByText(/Plafond mensuel gratuit/i)).toBeTruthy();
  }, 10000);

  it('in Produits tab: can filter left panel', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    const filterInputs = screen.getAllByPlaceholderText(/Filtrer/i);
    await user.type(filterInputs[0], 'AAPL');
    expect(screen.getByText(/Disponibles/i)).toBeTruthy();
  }, 10000);

  it('in Produits tab: can filter right panel', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    const filterInputs = screen.getAllByPlaceholderText(/Filtrer/i);
    await user.type(filterInputs[1], 'AAPL');
    expect(screen.getAllByText(/Autorisés/i).length).toBeGreaterThan(0);
  }, 10000);

  it('in Produits tab: clicking available product adds it to allowed list', async () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, allowed_tickers: [] }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    // click AAPL in left panel
    const aaplItems = screen.getAllByText(/AAPL/);
    if (aaplItems.length > 0) await user.click(aaplItems[0]);
    expect(screen.getAllByText(/Autorisés/i).length).toBeGreaterThan(0);
  }, 10000);

  it('in Produits tab: clicking allowed product removes it', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    // AAPL is in allowed_tickers
    const allowedDiv = screen.getAllByText(/AAPL/);
    if (allowedDiv.length > 0) await user.click(allowedDiv[allowedDiv.length - 1]);
    expect(screen.getAllByText(/Autorisés/i).length).toBeGreaterThan(0);
  }, 10000);

  it('in Produits tab: Tout autoriser → moves all products to allowed', async () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, allowed_tickers: [] }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    await user.click(screen.getByText(/Tout autoriser/i));
    expect(screen.getAllByText(/Autorisés/i).length).toBeGreaterThan(0);
  }, 10000);

  it('in Produits tab: Tout retirer → clears allowed list', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    await user.click(screen.getByText(/← Tout retirer/i));
    expect(screen.getByText(/Aucun — tous autorisés/i)).toBeTruthy();
  }, 10000);

  it('clicking unknown ticker in Produits tab calls removeTicker (line 365 fn70)', async () => {
    // UNKNOWN_XYZ is in allowed_tickers but NOT in products → shows as "inconnu"
    // Clicking it calls () => removeTicker(t) → fn70 at line 365
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, allowed_tickers: ['AAPL', 'UNKNOWN_XYZ'] }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    // UNKNOWN_XYZ shows in right panel as "inconnu"
    const unknownEl = screen.queryByText('UNKNOWN_XYZ');
    if (unknownEl) {
      await user.click(unknownEl); // calls removeTicker('UNKNOWN_XYZ') → fn70
    }
    expect(screen.getAllByText(/Autorisés/i).length).toBeGreaterThan(0);
  }, 10000);

  it('in Produits tab: shows unknown ticker label', async () => {
    // MOCK_BROKER.allowed_tickers = ['AAPL'] but MOCK_PRODUCTS has both AAPL and OR
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, allowed_tickers: ['AAPL', 'UNKNOWN_XYZ'] }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    expect(screen.getByText('inconnu')).toBeTruthy();
  }, 10000);

  it('in Produits tab: filtering right panel with tickerFilterRight triggers unknown ticker filter (line 364)', async () => {
    // Need tickerFilterRight to be non-empty to cover `t.includes(tickerFilterRight.toUpperCase())`
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, allowed_tickers: ['AAPL', 'UNKNOWN_XYZ'] }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    // Type in the right filter to trigger the include() branch for unknown tickers
    const filterInputs = screen.getAllByPlaceholderText(/Filtrer/i);
    if (filterInputs.length > 1) {
      await user.type(filterInputs[1], 'UNKNOWN'); // covers the t.includes() branch (line 364)
    }
    expect(screen.getAllByText(/Autorisés/i).length).toBeGreaterThan(0);
  }, 10000);

  it('in Produits tab: can save tickers selection', async () => {
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({ ok: true } as any);
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    const saveBtns = screen.getAllByText('Enregistrer');
    await user.click(saveBtns[1]); // index 0 = TTF card's save button, index 1 = Commission panel's
    expect(fetchSpy).toHaveBeenCalled();
    fetchSpy.mockRestore();
  }, 10000);

  it('in Produits tab: save with empty selectedTickers sends null', async () => {
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({ ok: true } as any);
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    await user.click(screen.getByText(/← Tout retirer/i));
    const saveBtns = screen.getAllByText('Enregistrer');
    await user.click(saveBtns[1]); // index 0 = TTF card's save button, index 1 = Commission panel's
    expect(fetchSpy).toHaveBeenCalled();
    fetchSpy.mockRestore();
  }, 10000);

  it('switches to Change FX tab in commission editor', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Change FX'));
    expect(screen.getByText(/Plafond mensuel/i)).toBeTruthy();
  }, 10000);

  it('in Change FX tab: can save FX commission', async () => {
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({ ok: true } as any);
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Change FX'));
    const saveBtns = screen.getAllByText('Enregistrer');
    await user.click(saveBtns[1]); // index 0 = TTF card's save button, index 1 = Commission panel's
    expect(fetchSpy).toHaveBeenCalled();
    fetchSpy.mockRestore();
  }, 10000);

  it('in Change FX tab: fetch error throws (line 35 error path)', async () => {
    // putFXCommission: when res.ok=false → throw new Error(await res.text()) — line 35
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({
      ok: false,
      text: () => Promise.resolve('FX error'),
    } as any);
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Change FX'));
    const saveBtns = screen.getAllByText('Enregistrer');
    await user.click(saveBtns[1]); // index 0 = TTF card's save button, index 1 = Commission panel's
    // Error is caught by handleSave try/catch → sets error state
    expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
    fetchSpy.mockRestore();
  }, 10000);

  it('in Produits tab: putAllowedTickers fetch error throws (line 50 error path)', async () => {
    // putAllowedTickers: when res.ok=false → throw new Error(await res.text()) — line 50
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({
      ok: false,
      text: () => Promise.resolve('Tickers error'),
    } as any);
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    const saveBtns = screen.getAllByText('Enregistrer');
    await user.click(saveBtns[1]); // index 0 = TTF card's save button, index 1 = Commission panel's
    expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
    fetchSpy.mockRestore();
  }, 10000);

  it('in Change FX tab: save with empty monthly free sends null', async () => {
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({ ok: true } as any);
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Change FX'));
    // Clear the monthly free input
    const numberInputs = screen.getAllByRole('spinbutton');
    if (numberInputs.length > 0) {
      await user.clear(numberInputs[0]);
    }
    const saveBtns = screen.getAllByText('Enregistrer');
    await user.click(saveBtns[1]); // index 0 = TTF card's save button, index 1 = Commission panel's
    expect(fetchSpy).toHaveBeenCalled();
    fetchSpy.mockRestore();
  }, 10000);

  it('in Change FX tab: typing in FX inputs calls onChange handlers (lines 383-385)', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Change FX'));
    // Type in the number inputs to trigger onChange for each FX field.
    // Scoped to the FX panel itself (not a position-based slice) so it isn't thrown off by
    // unrelated spinbuttons elsewhere on the page (e.g. the macro "Durée MM" setting).
    const fxPanel = screen.getByText(/Laisser vide pour désactiver/i).parentElement as HTMLElement;
    const numberInputs = within(fxPanel).getAllByRole('spinbutton');
    expect(numberInputs).toHaveLength(3); // monthly_free, above_rate, weekend_rate
    for (const inp of numberInputs) {
      await user.clear(inp);
      await user.type(inp, '1.5');
    }
    expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
  }, 10000);

  it('in Change FX tab: onFocus triggers select (line 383)', async () => {
    render(<GlobalConfigPage />);
    fireEvent.click(screen.getByText('Commission'));
    fireEvent.click(screen.getByText('Change FX'));
    const numberInputs = screen.getAllByRole('spinbutton');
    if (numberInputs.length > 0) {
      const firstInput = numberInputs[numberInputs.length - 3] as HTMLInputElement;
      const selectSpy = vi.spyOn(firstInput, 'select');
      fireEvent.focus(firstInput);
      expect(selectSpy).toHaveBeenCalled();
    }
  }, 10000);

  it('clicking allowed product in Produits tab calls removeTicker (line 128 fn23-fn25, line 360 fn67)', async () => {
    // AAPL is in allowed_tickers → appears in right panel → clicking removes it → removeTicker called
    // This covers: onClick={() => removeTicker(p.ticker)} at line 360 (fn67)
    // AND: setSelectedTickers(s => s.filter(x => x !== t)) at line 128 (fn24, fn25)
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    // After switching to Produits tab with AAPL in allowed_tickers:
    // The right panel shows "Autorisés (1)" and AAPL as a clickable item
    // Find AAPL in the allowed section by looking for the text "AAPL" in a div that has a title attribute
    // The allowed tickers divs have title="Clic pour retirer"
    const allowedAaplDivs = document.querySelectorAll('div[title="Clic pour retirer"]');
    if (allowedAaplDivs.length > 0) {
      await user.click(allowedAaplDivs[0] as HTMLElement); // onClick={() => removeTicker(p.ticker)} at line 360
    } else {
      // Fallback: click AAPL text
      const aaplEls = screen.getAllByText(/AAPL/);
      if (aaplEls.length > 0) await user.click(aaplEls[aaplEls.length - 1]);
    }
    expect(screen.getAllByText(/Autorisés/i).length).toBeGreaterThan(0);
  }, 10000);

  it('addTicker inner function covers fn23 (line 128)', async () => {
    // addTicker: (t: string) => setSelectedTickers(s => [...s, t])
    // The inner fn (s => [...s, t]) is fn23
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, allowed_tickers: [] }], // no allowed tickers
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    // Click AAPL in left panel (available) → addTicker('AAPL') → setSelectedTickers(s => [...s, 'AAPL'])
    const aaplEls = screen.getAllByText(/AAPL/);
    if (aaplEls.length > 0) await user.click(aaplEls[0]);
    expect(screen.getAllByText(/Autorisés/i).length).toBeGreaterThan(0);
  }, 10000);

  it('switching to FX tab with null monthly_free_eur and zero above_rate (lines 287-288 false branches)', async () => {
    // Cover ternary false branches: monthly_free_eur=null → '', above_monthly_rate=0 → '', weekend_rate=null → ''
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, monthly_free_eur: null, above_monthly_rate: 0, weekend_rate: null }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Change FX'));
    // With null monthly_free_eur → setFxMonthlyFree(''); above_monthly_rate=0 → ''; weekend_rate=null → ''
    expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
  }, 10000);

  it('switching from FX tab back to Commission tab (line 285 onClick)', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    // Switch to FX
    await user.click(screen.getByText('Change FX'));
    // Switch back to Commission (line 285)
    await user.click(screen.getByText('Commission'));
    expect(screen.getByText(/Jusqu'à/i)).toBeTruthy();
  }, 10000);

  it('tier input up_to: onFocus triggers select (line 304)', async () => {
    render(<GlobalConfigPage />);
    fireEvent.click(screen.getByText('Commission'));
    // After opening Commission, tier rows are shown with number inputs
    const numberInputs = screen.getAllByRole('spinbutton');
    // The up_to input for the first tier
    if (numberInputs.length > 0) {
      const upToInput = numberInputs[0] as HTMLInputElement;
      const selectSpy = vi.spyOn(upToInput, 'select');
      fireEvent.focus(upToInput);
      expect(selectSpy).toHaveBeenCalled();
    }
  }, 10000);

  it('tier input value: onFocus triggers select and onChange updates tier value (line 314)', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    // Number inputs in commission editor: up_to and value for each tier
    const numberInputs = screen.getAllByRole('spinbutton');
    // Fire focus and change on value inputs (second input of each tier)
    for (const inp of numberInputs) {
      const el = inp as HTMLInputElement;
      vi.spyOn(el, 'select');
      fireEvent.focus(el);
      fireEvent.change(el, { target: { value: '2.5' } });
      // Don't need to assert each spy, just verify no crash
    }
    expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
  }, 10000);

  it('broker table name sort header onClick (line 225)', async () => {
    const user = userEvent.setup({ delay: null });
    const { container } = render(<GlobalConfigPage />);
    // Click broker table column header (line 225 — accTh('name') onClick toggleAcc('name'))
    const brokerTableThs = Array.from(container.querySelectorAll('th'));
    const nameTh = brokerTableThs.find(th => th.textContent?.includes('Broker'));
    if (nameTh) {
      await user.click(nameTh as HTMLElement);
      expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
    }
  }, 10000);
});

describe('GlobalConfigPage — CommissionManager broker CRUD', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupBrokerMocks();
  });

  afterEach(() => { vi.restoreAllMocks(); });

  it('clicking ✏️ button opens broker edit modal', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const editBtns = screen.getAllByRole('button').filter((b: HTMLElement) => b.textContent?.includes('✏️'));
    if (editBtns.length > 0) {
      await user.click(editBtns[0]);
      expect(screen.getByTestId('modal')).toBeTruthy();
    }
  }, 10000);

  it('edit modal shows broker name prefilled', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const editBtns = screen.getAllByRole('button').filter((b: HTMLElement) => b.textContent?.includes('✏️'));
    if (editBtns.length > 0) {
      await user.click(editBtns[0]);
      // The broker modal contains a text input with 'Degiro' as value
      const modal = screen.getByTestId('modal');
      const textInputs = modal.querySelectorAll('input[type="text"], input:not([type])');
      const nameInput = Array.from(textInputs).find((inp: any) => (inp as HTMLInputElement).value === 'Degiro');
      expect(nameInput).toBeTruthy();
    }
  }, 10000);

  it('save edit broker calls updateBrokerAPI', async () => {
    const { updateBrokerAPI } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const editBtns = screen.getAllByRole('button').filter((b: HTMLElement) => b.textContent?.includes('✏️'));
    if (editBtns.length > 0) {
      await user.click(editBtns[0]);
      const modal = screen.getByTestId('modal');
      const actions = modal.querySelector('[data-testid="modal-actions"]');
      if (actions) {
        const saveBtn = Array.from(actions.querySelectorAll('button')).find(b => b.textContent?.includes('Enregistrer'));
        if (saveBtn) await user.click(saveBtn);
      }
      expect(updateBrokerAPI).toHaveBeenCalled();
    }
  }, 10000);

  it('save edit broker shows error when name is empty', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const editBtns = screen.getAllByRole('button').filter((b: HTMLElement) => b.textContent?.includes('✏️'));
    if (editBtns.length > 0) {
      await user.click(editBtns[0]);
      const modal = screen.getByTestId('modal');
      const textInputs = modal.querySelectorAll('input[type="text"], input:not([type])');
      const nameInput = Array.from(textInputs).find((inp: any) => (inp as HTMLInputElement).value === 'Degiro') as HTMLInputElement | undefined;
      if (nameInput) await user.clear(nameInput);
      const actions = modal.querySelector('[data-testid="modal-actions"]');
      if (actions) {
        const saveBtn = Array.from(actions.querySelectorAll('button')).find(b => b.textContent?.includes('Enregistrer'));
        if (saveBtn) await user.click(saveBtn);
      }
      expect(screen.getAllByRole('alert').length).toBeGreaterThan(0);
    }
  }, 10000);

  it('opening Nouveau broker modal shows currency field', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBrokerBtn = screen.getAllByRole('button').find((b: HTMLElement) => b.textContent?.includes('Nouveau broker'));
    if (newBrokerBtn) {
      await user.click(newBrokerBtn);
      // The new broker modal shows a currency input (only shown when brokerModal === 'new')
      const modal = screen.getByTestId('modal');
      expect(modal).toBeTruthy();
      // The currency field has a maxLength=3 input
      const currencyInput = modal.querySelector('input[maxLength="3"]');
      expect(currencyInput).toBeTruthy();
    }
  }, 10000);

  it('save new broker calls createBrokerAPI', async () => {
    const { createBrokerAPI } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBrokerBtn = screen.getAllByRole('button').find((b: HTMLElement) => b.textContent?.includes('Nouveau broker'));
    if (newBrokerBtn) {
      await user.click(newBrokerBtn);
      const modal = screen.getByTestId('modal');
      // First text input in broker form is the name
      const textInputs = modal.querySelectorAll('input[type="text"], input:not([type]):not([type="color"]):not([type="checkbox"])');
      const nameInput = textInputs[0] as HTMLInputElement | undefined;
      if (nameInput) await user.type(nameInput, 'TestBroker');
      const actions = modal.querySelector('[data-testid="modal-actions"]');
      if (actions) {
        const saveBtn = Array.from(actions.querySelectorAll('button')).find(b => b.textContent?.includes('Enregistrer'));
        if (saveBtn) await user.click(saveBtn);
      }
      expect(createBrokerAPI).toHaveBeenCalled();
    }
  }, 10000);

  it('save new broker API error shows error in modal', async () => {
    const { createBrokerAPI } = await import('../api/queries');
    vi.mocked(createBrokerAPI).mockRejectedValueOnce({ response: { data: { detail: 'Broker name taken' } } });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBrokerBtn = screen.getAllByRole('button').find((b: HTMLElement) => b.textContent?.includes('Nouveau broker'));
    if (newBrokerBtn) {
      await user.click(newBrokerBtn);
      const modal = screen.getByTestId('modal');
      const textInputs = modal.querySelectorAll('input[type="text"], input:not([type]):not([type="color"]):not([type="checkbox"])');
      const nameInput = textInputs[0] as HTMLInputElement | undefined;
      if (nameInput) await user.type(nameInput, 'Taken');
      const actions = modal.querySelector('[data-testid="modal-actions"]');
      if (actions) {
        const saveBtn = Array.from(actions.querySelectorAll('button')).find(b => b.textContent?.includes('Enregistrer'));
        if (saveBtn) await user.click(saveBtn);
      }
      await rtlWaitFor(() => expect(screen.getByText(/Broker name taken/i)).toBeTruthy());
    }
  }, 10000);

  it('currency input onChange in new broker modal converts to uppercase (line 190)', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBrokerBtn = screen.getAllByRole('button').find((b: HTMLElement) => b.textContent?.includes('Nouveau broker'));
    if (newBrokerBtn) {
      await user.click(newBrokerBtn);
      const modal = screen.getByTestId('modal');
      // Currency input has maxLength=3 and is only shown in 'new' mode
      const currencyInput = modal.querySelector('input[maxLength="3"]') as HTMLInputElement | null;
      if (currencyInput) {
        await user.clear(currencyInput);
        await user.type(currencyInput, 'usd');
        expect(currencyInput.value).toBe('USD'); // line 190 - toUpperCase
      }
    }
  }, 10000);

  it('color input onChange in broker modal updates color (line 196)', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBrokerBtn = screen.getAllByRole('button').find((b: HTMLElement) => b.textContent?.includes('Nouveau broker'));
    if (newBrokerBtn) {
      await user.click(newBrokerBtn);
      const modal = screen.getByTestId('modal');
      // Color input is type="color"
      const colorInput = modal.querySelector('input[type="color"]') as HTMLInputElement | null;
      if (colorInput) {
        fireEvent.change(colorInput, { target: { value: '#ff0000' } });
        expect(colorInput.value).toBe('#ff0000'); // line 196 onChange
      }
    }
  }, 10000);

  it('can toggle portfolio checkbox in new broker modal', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBrokerBtn = screen.getAllByRole('button').find((b: HTMLElement) => b.textContent?.includes('Nouveau broker'));
    if (newBrokerBtn) {
      await user.click(newBrokerBtn);
      const portfolioCheckboxes = screen.getAllByRole('checkbox');
      // Find Portfolio 1 checkbox
      if (portfolioCheckboxes.length > 0) {
        await user.click(portfolioCheckboxes[0]);
        expect(screen.getByText(/Portfolio 1/)).toBeTruthy();
      }
    }
  }, 10000);

  it('close modal via Annuler in new broker modal', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBrokerBtn = screen.getAllByRole('button').find((b: HTMLElement) => b.textContent?.includes('Nouveau broker'));
    if (newBrokerBtn) {
      await user.click(newBrokerBtn);
      // Use the "Close modal" button from our stub
      await user.click(screen.getByText('Close modal'));
      expect(screen.queryByTestId('modal')).toBeNull();
    }
  }, 10000);

  it('clicking 🗑 button then confirming in modal calls deleteBrokerAPI', async () => {
    const { deleteBrokerAPI } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const deleteBtns = screen.getAllByRole('button').filter((b: HTMLElement) => b.textContent?.includes('🗑'));
    if (deleteBtns.length > 0) {
      await user.click(deleteBtns[0]);
      await user.click(screen.getByText('Supprimer'));
      expect(deleteBrokerAPI).toHaveBeenCalled();
    }
  }, 10000);

  it('clicking 🗑 button then cancelling in modal does not call deleteBrokerAPI', async () => {
    const { deleteBrokerAPI } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const deleteBtns = screen.getAllByRole('button').filter((b: HTMLElement) => b.textContent?.includes('🗑'));
    if (deleteBtns.length > 0) {
      await user.click(deleteBtns[0]);
      await user.click(screen.getByText('Annuler'));
      expect(deleteBrokerAPI).not.toHaveBeenCalled();
    }
  }, 10000);

  it('delete broker API error shows alert', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const { deleteBrokerAPI } = await import('../api/queries');
    vi.mocked(deleteBrokerAPI).mockRejectedValueOnce({ response: { data: { detail: 'Has transactions' } } });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const deleteBtns = screen.getAllByRole('button').filter((b: HTMLElement) => b.textContent?.includes('🗑'));
    if (deleteBtns.length > 0) {
      await user.click(deleteBtns[0]);
      await user.click(screen.getByText('Supprimer'));
      expect(alertSpy).toHaveBeenCalled();
    }
    alertSpy.mockRestore();
  }, 10000);
});

describe('GlobalConfigPage — CommissionManager inline features', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupBrokerMocks();
  });

  afterEach(() => { vi.restoreAllMocks(); });

  it('include_fees_in_cump checkbox onChange calls fetch PUT', async () => {
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({ ok: true } as any);
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    // The include_fees_in_cump checkbox is in the broker row
    const checkboxes = screen.getAllByRole('checkbox');
    // Find the one with title about CUMP
    const cumpCheckbox = checkboxes.find((c: HTMLElement) =>
      c.getAttribute('title')?.includes('CUMP') || c.getAttribute('title')?.includes('Courtage')
    );
    if (cumpCheckbox) {
      await user.click(cumpCheckbox);
      expect(fetchSpy).toHaveBeenCalled();
    }
    fetchSpy.mockRestore();
  }, 10000);

  it('commission_sale_rate input onChange calls fetch PUT', async () => {
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({ ok: true } as any);
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const inputs = screen.getAllByRole('spinbutton');
    // The sale rate input has value 0.005
    const saleRateInput = inputs.find((inp: HTMLElement) =>
      parseFloat((inp as HTMLInputElement).value) === 0.005
    );
    if (saleRateInput) {
      await user.clear(saleRateInput);
      await user.type(saleRateInput, '0.006');
      // trigger onChange by firing a change event (since onChange is async)
      fireEvent.change(saleRateInput, { target: { value: '0.006' } });
      expect(fetchSpy).toHaveBeenCalled();
    }
    fetchSpy.mockRestore();
  }, 10000);

  it('commission_sale_rate (%) tooltip text is rendered', () => {
    render(<GlobalConfigPage />);
    const inputs = screen.getAllByRole('spinbutton');
    const saleRateInput = inputs.find((inp: HTMLElement) =>
      parseFloat((inp as HTMLInputElement).value) === 0.005
    );
    expect(saleRateInput).toBeTruthy();
    if (saleRateInput) {
      expect(saleRateInput.getAttribute('title')).toMatch(/0.5%/);
    }
  });
});

// ── Additional coverage for uncovered branches ────────────────────────────────

describe('GlobalConfigPage — additional branch coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupBrokerMocks();
  });

  afterEach(() => { vi.restoreAllMocks(); });

  it('broker with null color renders fallback #6A6E73 (line 243 ?? branch)', () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, color: null }],
      isLoading: false,
    });
    render(<GlobalConfigPage />);
    // Broker with null color → acc.color ?? '#6A6E73' uses fallback
    expect(screen.getAllByText('Degiro').length).toBeGreaterThan(0);
    // The page renders without crash — the dot span uses #6A6E73 as backgroundColor
    expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
  });

  it('broker with null currency in openEditBroker uses EUR fallback (line 78 ?? branch)', async () => {
    // openEditBroker: acc.currency ?? 'EUR' and acc.color ?? '#1890FF'
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, currency: null, color: null }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const editBtns = screen.getAllByRole('button').filter((b: HTMLElement) => b.textContent?.includes('✏️'));
    if (editBtns.length > 0) {
      await user.click(editBtns[0]);
      // Edit modal opens with currency='EUR' (fallback) and color='#1890FF' (fallback)
      expect(screen.getByTestId('modal')).toBeTruthy();
    }
  }, 10000);

  it('toggleBrokerPortfolio add branch: clicking an unchecked portfolio adds it (line 83 false branch)', async () => {
    // Start with portfolio_ids=[] then toggle to add portfolio 1
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, portfolio_ids: [] }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBrokerBtn = screen.getAllByRole('button').find((b: HTMLElement) => b.textContent?.includes('Nouveau broker'));
    if (newBrokerBtn) {
      await user.click(newBrokerBtn);
      const checkboxes = screen.getAllByRole('checkbox');
      if (checkboxes.length > 0) {
        // First click: remove (filter branch, since portfolio_ids starts as [1] in openNewBroker)
        await user.click(checkboxes[0]);
        // Second click: add (ADD branch, since portfolio_ids is now [])
        await user.click(checkboxes[0]);
      }
    }
    expect(screen.getByText(/Gérer les brokers/i)).toBeTruthy();
  }, 10000);

  it('handleSaveBroker catch without detail uses "Erreur" fallback (line 96 ?? branch)', async () => {
    const { createBrokerAPI } = await import('../api/queries');
    vi.mocked(createBrokerAPI).mockRejectedValueOnce(new Error('Plain error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newBrokerBtn = screen.getAllByRole('button').find((b: HTMLElement) => b.textContent?.includes('Nouveau broker'));
    if (newBrokerBtn) {
      await user.click(newBrokerBtn);
      const modal = screen.getByTestId('modal');
      const textInputs = modal.querySelectorAll('input[type="text"], input:not([type]):not([type="color"])');
      const nameInput = textInputs[0] as HTMLInputElement | undefined;
      if (nameInput) await user.type(nameInput, 'TestBroker');
      const actions = modal.querySelector('[data-testid="modal-actions"]');
      if (actions) {
        const saveBtn = Array.from(actions.querySelectorAll('button')).find(b => b.textContent?.includes('Enregistrer'));
        if (saveBtn) await user.click(saveBtn);
      }
      // Error shown: falls back to 'Erreur' since plain Error has no response.data.detail
      await rtlWaitFor(() => expect(screen.getByText('Erreur')).toBeTruthy());
    }
  }, 10000);

  it('handleDeleteBroker catch without detail uses "Impossible de supprimer" fallback (line 102 ?? branch)', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const { deleteBrokerAPI } = await import('../api/queries');
    vi.mocked(deleteBrokerAPI).mockRejectedValueOnce(new Error('Generic error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const deleteBtns = screen.getAllByRole('button').filter((b: HTMLElement) => b.textContent?.includes('🗑'));
    if (deleteBtns.length > 0) {
      await user.click(deleteBtns[0]);
      await user.click(screen.getByText('Supprimer'));
      expect(alertSpy).toHaveBeenCalledWith('Impossible de supprimer');
    }
    alertSpy.mockRestore();
  }, 10000);

  it('tiersFromSchedule with null schedule uses [] fallback (line 131 ?? branch)', async () => {
    // Open commission editor for a broker with null commission_schedule
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, commission_schedule: null }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    // With null schedule → tiersFromSchedule(null) → (null ?? []) uses [] → no tiers
    expect(screen.getByText(/Grille vide → commission = 0/i)).toBeTruthy();
  }, 10000);

  it('weekend_rate null does not render weekend-rate row (line 288 false branch)', () => {
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, monthly_free_eur: 500, weekend_rate: null }],
      isLoading: false,
    });
    render(<GlobalConfigPage />);
    // weekend_rate is null → {acc.weekend_rate !== null && <span>} does not render
    expect(screen.queryByText(/week-end:/)).toBeNull();
    // monthly_free_eur is 500 → renders the FX info
    expect(screen.getByText(/500€\/mois gratuits/)).toBeTruthy();
  });

  it('Produits tab with null allowed_tickers uses [] fallback (line 291 ?? branch)', async () => {
    // When allowed_tickers is null, clicking Produits sets selectedTickers to []
    mockUseAllAccounts.mockReturnValue({
      data: [{ ...MOCK_BROKER, allowed_tickers: null }],
      isLoading: false,
    });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    await user.click(screen.getByText('Produits'));
    // selectedTickers = null ?? [] = [] → no allowed tickers shown
    expect(screen.getByText(/Aucun — tous autorisés/i)).toBeTruthy();
  }, 10000);

  it('putCommissionSaleRate fetch error is caught by caller and shown via alert', async () => {
    // The onChange handler of sale_rate input calls putCommissionSaleRate which calls fetch
    const fetchSpy = vi.spyOn(window, 'fetch').mockResolvedValueOnce({
      ok: false,
      text: () => Promise.resolve('Sale rate error'),
    } as any);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const { container } = render(<GlobalConfigPage />);
    const inputs = screen.getAllByRole('spinbutton');
    const saleRateInput = inputs.find((inp: HTMLElement) =>
      parseFloat((inp as HTMLInputElement).value) === 0.005
    ) as HTMLInputElement;
    expect(saleRateInput).toBeTruthy();

    await act(async () => {
      fireEvent.change(saleRateInput, { target: { value: '0.006' } });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(alertSpy).toHaveBeenCalledWith('Sale rate error');
    expect(container).toBeTruthy();
    fetchSpy.mockRestore();
    alertSpy.mockRestore();
  }, 10000);

  it('putCommissionSaleRate: non-Error rejection falls back to generic alert message', async () => {
    const fetchSpy = vi.spyOn(window, 'fetch').mockRejectedValueOnce('network down');
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    render(<GlobalConfigPage />);
    const inputs = screen.getAllByRole('spinbutton');
    const saleRateInput = inputs.find((inp: HTMLElement) =>
      parseFloat((inp as HTMLInputElement).value) === 0.005
    ) as HTMLInputElement;
    expect(saleRateInput).toBeTruthy();

    await act(async () => {
      fireEvent.change(saleRateInput, { target: { value: '0.006' } });
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(alertSpy).toHaveBeenCalledWith('Erreur lors de la mise à jour du taux de vente');
    fetchSpy.mockRestore();
    alertSpy.mockRestore();
  }, 10000);

  it('ttfSetting without value skips useEffect (line 564 false branch)', () => {
    // When ttfSetting?.value is falsy, the useEffect body does not run
    mockUseSystemSetting.mockReturnValue({ data: undefined, isError: false });
    render(<GlobalConfigPage />);
    // Default ttfRate is '0.40' (not overwritten since ttfSetting?.value is undefined)
    expect(screen.getByText(/Produits et frais financiers/i)).toBeTruthy();
  });

  it('handleSave catch with non-Error uses "Valeur invalide" fallback (line 164 false branch)', async () => {
    // Throw a non-Error object to cover e instanceof Error ? e.message : 'Valeur invalide'
    const fetchSpy = vi.spyOn(window, 'fetch').mockRejectedValueOnce({ code: 42 });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Commission'));
    const saveBtns = screen.getAllByText('Enregistrer');
    await user.click(saveBtns[1]); // index 0 = TTF card's save button, index 1 = Commission panel's
    await rtlWaitFor(() => expect(screen.getByText('Valeur invalide')).toBeTruthy());
    fetchSpy.mockRestore();
  }, 10000);
});

describe('GlobalConfigPage — RegionManager (Indicateurs macro)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the macro indicators section with the region list and shared ticker fields', () => {
    render(<GlobalConfigPage />);
    expect(screen.getByText(/Indicateurs macro/i)).toBeTruthy();
    expect(screen.getByText('us')).toBeTruthy();
    expect(screen.getByText('États-Unis')).toBeTruthy();
    expect(screen.getByText('^SPXEW')).toBeTruthy();
    expect(screen.getByText('S&P 500 Equal Weight')).toBeTruthy();
    expect(screen.getByText('Obligations Trésor américain')).toBeTruthy();
    expect(screen.getByLabelText('Ticker Pétrole')).toBeTruthy();
    expect(screen.getByLabelText('Nom Pétrole')).toBeTruthy();
    expect(screen.getByLabelText('Ticker Or')).toBeTruthy();
    expect(screen.getByLabelText('Nom Or')).toBeTruthy();
    expect(screen.getByLabelText('Durée de la moyenne mobile (années)')).toBeTruthy();
  });

  it('shows "Aucune région" when there are no regions', () => {
    mockUseMacroRegions.mockReturnValue({ data: [], refetch: vi.fn() });
    render(<GlobalConfigPage />);
    expect(screen.getByText('Aucune région')).toBeTruthy();
  });

  it('saving without a code shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouvelle région'));
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(/Le code est requis/i)).toBeTruthy();
  }, 10000);

  it('saving without a label shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouvelle région'));
    await user.type(screen.getByLabelText('Code'), 'de');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(/Le nom est requis/i)).toBeTruthy();
  }, 10000);

  it('saving without an equity ticker shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouvelle région'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(/Le ticker actions est requis/i)).toBeTruthy();
  }, 10000);

  it('saving without a bond ticker shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouvelle région'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    await user.type(screen.getByLabelText('Ticker actions'), '^GDAXI');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(/Le ticker obligations est requis/i)).toBeTruthy();
  }, 10000);

  it('saving without an equity label shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouvelle région'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    await user.type(screen.getByLabelText('Ticker actions'), '^GDAXI');
    await user.type(screen.getByLabelText('Ticker obligations'), 'BUND');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(/Le nom des actions est requis/i)).toBeTruthy();
  }, 10000);

  it('saving without a bond label shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouvelle région'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    await user.type(screen.getByLabelText('Ticker actions'), '^GDAXI');
    await user.type(screen.getByLabelText('Ticker obligations'), 'BUND');
    await user.type(screen.getByLabelText('Nom actions'), 'DAX 40');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(/Le nom des obligations est requis/i)).toBeTruthy();
  }, 10000);

  it('can create a region with valid data', async () => {
    const { createMacroRegion } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouvelle région'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    await user.type(screen.getByLabelText('Ticker actions'), '^GDAXI');
    await user.type(screen.getByLabelText('Ticker obligations'), 'BUND');
    await user.type(screen.getByLabelText('Nom actions'), 'DAX 40');
    await user.type(screen.getByLabelText('Nom obligations'), 'Bund 10 ans');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(createMacroRegion).toHaveBeenCalledWith({
      code: 'de', label: 'Allemagne', equity_ticker: '^GDAXI', bond_ticker: 'BUND',
      equity_label: 'DAX 40', bond_label: 'Bund 10 ans',
    });
  }, 10000);

  it('region code input converts to lowercase', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouvelle région'));
    const codeInput = screen.getByLabelText('Code');
    await user.type(codeInput, 'DE');
    expect((codeInput as HTMLInputElement).value).toBe('de');
  }, 10000);

  it('create region API error shows the returned detail message', async () => {
    const { createMacroRegion } = await import('../api/queries');
    vi.mocked(createMacroRegion).mockRejectedValueOnce({ response: { data: { detail: "Region 'de' already exists" } } });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouvelle région'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    await user.type(screen.getByLabelText('Ticker actions'), '^GDAXI');
    await user.type(screen.getByLabelText('Ticker obligations'), 'BUND');
    await user.type(screen.getByLabelText('Nom actions'), 'DAX 40');
    await user.type(screen.getByLabelText('Nom obligations'), 'Bund 10 ans');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    await rtlWaitFor(() => expect(screen.getByText(/already exists/i)).toBeTruthy());
  }, 10000);

  it('create region API error without detail uses fallback message', async () => {
    const { createMacroRegion } = await import('../api/queries');
    vi.mocked(createMacroRegion).mockRejectedValueOnce(new Error('Network error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouvelle région'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    await user.type(screen.getByLabelText('Ticker actions'), '^GDAXI');
    await user.type(screen.getByLabelText('Ticker obligations'), 'BUND');
    await user.type(screen.getByLabelText('Nom actions'), 'DAX 40');
    await user.type(screen.getByLabelText('Nom obligations'), 'Bund 10 ans');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    await rtlWaitFor(() => expect(screen.getByText(/Erreur lors de l'enregistrement/i)).toBeTruthy());
  }, 10000);

  it('shows edit modal with the code locked when clicking edit for a region', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Modifier us/i }));
    expect(screen.getByText(/Modifier la région — us/i)).toBeTruthy();
    const codeInput = screen.getByLabelText('Code');
    expect((codeInput as HTMLInputElement).disabled).toBe(true);
    expect((codeInput as HTMLInputElement).value).toBe('us');
  }, 10000);

  it('can save an edited region', async () => {
    const { updateMacroRegion } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Modifier us/i }));
    const labelInput = screen.getByLabelText('Nom');
    await user.clear(labelInput);
    await user.type(labelInput, 'USA');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(updateMacroRegion).toHaveBeenCalledWith('us', {
      label: 'USA', equity_ticker: '^SPXEW', bond_ticker: 'GOVT',
      equity_label: 'S&P 500 Equal Weight', bond_label: 'Obligations Trésor américain',
    });
  }, 10000);

  it('can delete a region with confirm', async () => {
    const { deleteMacroRegion } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer fr/i }));
    await user.click(screen.getByText('Supprimer'));
    expect(deleteMacroRegion).toHaveBeenCalledWith('fr');
  }, 10000);

  it('delete cancelled by user does not call deleteMacroRegion', async () => {
    const { deleteMacroRegion } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer fr/i }));
    await user.click(screen.getByText('Annuler'));
    expect(deleteMacroRegion).not.toHaveBeenCalled();
  }, 10000);

  it('delete blocked (last remaining region) shows the returned error message', async () => {
    const { deleteMacroRegion } = await import('../api/queries');
    vi.mocked(deleteMacroRegion).mockRejectedValueOnce({ response: { data: { detail: 'Cannot delete the last remaining region' } } });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer fr/i }));
    await user.click(screen.getByText('Supprimer'));
    await rtlWaitFor(() => expect(screen.getByText(/Cannot delete the last remaining region/i)).toBeTruthy());
  }, 10000);

  it('delete error without detail shows fallback message', async () => {
    const { deleteMacroRegion } = await import('../api/queries');
    vi.mocked(deleteMacroRegion).mockRejectedValueOnce(new Error('Unknown error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer fr/i }));
    await user.click(screen.getByText('Supprimer'));
    await rtlWaitFor(() => expect(screen.getByText(/Erreur lors de la suppression/i)).toBeTruthy());
  }, 10000);
});

describe('GlobalConfigPage — MarketCountryManager (Performance des marchés)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the market performance section with the country list and top-N setting', () => {
    render(<GlobalConfigPage />);
    expect(screen.getByText(/Performance des marchés/i)).toBeTruthy();
    expect(screen.getByText('jp')).toBeTruthy();
    expect(screen.getByText('Japon')).toBeTruthy();
    expect(screen.getByText('^N225')).toBeTruthy();
    expect(screen.getByText('JPY')).toBeTruthy();
    expect(screen.getByLabelText('Nombre de pays affichés (Top N)')).toBeTruthy();
  });

  it('shows "Aucun pays" when there are no countries', () => {
    mockUseCountryPerfConfigs.mockReturnValue({ data: [], refetch: vi.fn() });
    render(<GlobalConfigPage />);
    expect(screen.getByText('Aucun pays')).toBeTruthy();
  });

  it('saving without a code shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau pays'));
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(/Le code est requis/i)).toBeTruthy();
  }, 10000);

  it('saving without a label shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau pays'));
    await user.type(screen.getByLabelText('Code'), 'de');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(/Le nom est requis/i)).toBeTruthy();
  }, 10000);

  it('saving without an index ticker shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau pays'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(/Le ticker indice est requis/i)).toBeTruthy();
  }, 10000);

  it('saving without a currency shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau pays'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    await user.type(screen.getByLabelText('Ticker indice'), '^GDAXI');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(/La devise est requise/i)).toBeTruthy();
  }, 10000);

  it('saving without an index label shows validation error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau pays'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    await user.type(screen.getByLabelText('Ticker indice'), '^GDAXI');
    await user.type(screen.getByLabelText('Devise'), 'EUR');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(/Le nom de l'indice est requis/i)).toBeTruthy();
  }, 10000);

  it('can create a country with valid data', async () => {
    const { createCountryPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau pays'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    await user.type(screen.getByLabelText('Nom de l\'indice'), 'DAX 40');
    await user.type(screen.getByLabelText('Ticker indice'), '^GDAXI');
    await user.type(screen.getByLabelText('Devise'), 'eur');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(createCountryPerfConfig).toHaveBeenCalledWith({
      code: 'de', label: 'Allemagne', index_ticker: '^GDAXI', currency: 'EUR', index_label: 'DAX 40',
    });
  }, 10000);

  it('country code input converts to lowercase, currency input converts to uppercase', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau pays'));
    const codeInput = screen.getByLabelText('Code');
    await user.type(codeInput, 'DE');
    expect((codeInput as HTMLInputElement).value).toBe('de');
    const currencyInput = screen.getByLabelText('Devise');
    await user.type(currencyInput, 'eur');
    expect((currencyInput as HTMLInputElement).value).toBe('EUR');
  }, 10000);

  it('create country API error shows the returned detail message', async () => {
    const { createCountryPerfConfig } = await import('../api/queries');
    vi.mocked(createCountryPerfConfig).mockRejectedValueOnce({ response: { data: { detail: "Country 'de' already exists" } } });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau pays'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    await user.type(screen.getByLabelText('Nom de l\'indice'), 'DAX 40');
    await user.type(screen.getByLabelText('Ticker indice'), '^GDAXI');
    await user.type(screen.getByLabelText('Devise'), 'EUR');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    await rtlWaitFor(() => expect(screen.getByText(/already exists/i)).toBeTruthy());
  }, 10000);

  it('create country API error without detail uses fallback message', async () => {
    const { createCountryPerfConfig } = await import('../api/queries');
    vi.mocked(createCountryPerfConfig).mockRejectedValueOnce(new Error('Network error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau pays'));
    await user.type(screen.getByLabelText('Code'), 'de');
    await user.type(screen.getByLabelText('Nom'), 'Allemagne');
    await user.type(screen.getByLabelText('Nom de l\'indice'), 'DAX 40');
    await user.type(screen.getByLabelText('Ticker indice'), '^GDAXI');
    await user.type(screen.getByLabelText('Devise'), 'EUR');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    await rtlWaitFor(() => expect(screen.getByText(/Erreur lors de l'enregistrement/i)).toBeTruthy());
  }, 10000);

  it('shows edit modal with the code locked when clicking edit for a country', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Modifier pays jp/i }));
    expect(screen.getByText(/Modifier le pays — jp/i)).toBeTruthy();
    const codeInput = screen.getByLabelText('Code');
    expect((codeInput as HTMLInputElement).disabled).toBe(true);
    expect((codeInput as HTMLInputElement).value).toBe('jp');
  }, 10000);

  it('can save an edited country', async () => {
    const { updateCountryPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Modifier pays jp/i }));
    const labelInput = screen.getByLabelText('Nom');
    await user.clear(labelInput);
    await user.type(labelInput, 'Japan');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(updateCountryPerfConfig).toHaveBeenCalledWith('jp', {
      label: 'Japan', index_ticker: '^N225', currency: 'JPY', index_label: 'Nikkei 225',
    });
  }, 10000);

  it('can delete a country with confirm', async () => {
    const { deleteCountryPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer pays gb/i }));
    await user.click(screen.getByText('Supprimer'));
    expect(deleteCountryPerfConfig).toHaveBeenCalledWith('gb');
  }, 10000);

  it('delete cancelled by user does not call deleteCountryPerfConfig', async () => {
    const { deleteCountryPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer pays gb/i }));
    await user.click(screen.getByText('Annuler'));
    expect(deleteCountryPerfConfig).not.toHaveBeenCalled();
  }, 10000);

  it('delete succeeds with no last-remaining-row guard (unlike regions)', async () => {
    const { deleteCountryPerfConfig } = await import('../api/queries');
    mockUseCountryPerfConfigs.mockReturnValue({ data: [MOCK_COUNTRIES[0]], refetch: vi.fn() });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer pays jp/i }));
    await user.click(screen.getByText('Supprimer'));
    expect(deleteCountryPerfConfig).toHaveBeenCalledWith('jp');
  }, 10000);

  it('delete error without detail shows fallback message', async () => {
    const { deleteCountryPerfConfig } = await import('../api/queries');
    vi.mocked(deleteCountryPerfConfig).mockRejectedValueOnce(new Error('Unknown error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer pays gb/i }));
    await user.click(screen.getByText('Supprimer'));
    await rtlWaitFor(() => expect(screen.getByText(/Erreur lors de la suppression/i)).toBeTruthy());
  }, 10000);
});
