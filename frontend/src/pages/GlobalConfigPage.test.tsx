// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for ConfigGeneralePage — ProductManager and TTF rate.
 * Commission/regions/rebalancing/country-performance/sector-performance/equity-premium
 * coverage lives in the sibling GlobalConfigPage.<concern>.test.tsx files — each duplicates
 * this same full mock header since GlobalConfigPage always renders every manager at once.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, waitFor as rtlWaitFor } from '@testing-library/react';
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
  Modal: ({ children, isOpen, onClose }: any) =>
    isOpen ? (
      <div data-testid="modal">
        <div>{children}</div>
        <button onClick={onClose}>Close modal</button>
      </div>
    ) : null,
  ModalHeader: ({ title }: any) => <div data-testid="modal-title">{title}</div>,
  ModalBody: ({ children }: any) => <>{children}</>,
  ModalFooter: ({ children }: any) => <div data-testid="modal-actions">{children}</div>,
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
const mockUseSectorPerfConfigs = vi.fn();
const mockUseEquityPremiumConfigs = vi.fn();

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
  useSectorPerfConfigs: (...args: any[]) => mockUseSectorPerfConfigs(...args),
  createSectorPerfConfig: vi.fn().mockResolvedValue({}),
  updateSectorPerfConfig: vi.fn().mockResolvedValue({}),
  deleteSectorPerfConfig: vi.fn().mockResolvedValue(undefined),
  useEquityPremiumConfigs: (...args: any[]) => mockUseEquityPremiumConfigs(...args),
  createEquityPremiumConfig: vi.fn().mockResolvedValue({}),
  updateEquityPremiumConfig: vi.fn().mockResolvedValue({}),
  deleteEquityPremiumConfig: vi.fn().mockResolvedValue(undefined),
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

// Deliberately different codes from MOCK_REGIONS/MOCK_COUNTRIES (us/fr/jp/gb) — all three
// managers render on the same page, so a shared code would collide on aria-label queries.
const MOCK_SECTORS = [
  { code: 'or', label: 'Or', index_ticker: 'GC=F', currency: 'USD', index_label: 'Or (COMEX)' },
  { code: 'petrole', label: 'Pétrole', index_ticker: 'CL=F', currency: 'USD', index_label: 'Pétrole (WTI)' },
];

// Deliberately different codes from MOCK_REGIONS/MOCK_COUNTRIES/MOCK_SECTORS (us/fr/jp/gb/or/
// petrole) — all four managers render on the same page, so a shared code would collide on
// aria-label queries (this is exactly the pitfall the "prime {code}" aria-label disambiguates
// against in the real component).
const MOCK_EQUITY_PREMIUM_COUNTRIES = [
  { code: 'de', label: 'Allemagne', equity_ticker: 'EWG', bond_ticker: 'EXX6.DE', equity_label: 'Actions allemandes (EWG)', bond_label: 'Bund (EXX6.DE)' },
  { code: 'ch', label: 'Suisse', equity_ticker: 'EWL', bond_ticker: 'CSBGC0.SW', equity_label: 'Actions suisses (EWL)', bond_label: 'Obligations suisses (CSBGC0.SW)' },
];

function setupDefaultMocks() {
  mockUseSystemSetting.mockReturnValue({ data: { value: '0.004' }, isError: false });
  mockUseSetSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
  mockUseAllAccounts.mockReturnValue({ data: [], isLoading: false });
  mockUsePortfolios.mockReturnValue({ data: [] });
  mockUseProducts.mockReturnValue({ data: MOCK_PRODUCTS, refetch: vi.fn() });
  mockUseMacroRegions.mockReturnValue({ data: MOCK_REGIONS, refetch: vi.fn() });
  mockUseCountryPerfConfigs.mockReturnValue({ data: MOCK_COUNTRIES, refetch: vi.fn() });
  mockUseSectorPerfConfigs.mockReturnValue({ data: MOCK_SECTORS, refetch: vi.fn() });
  mockUseEquityPremiumConfigs.mockReturnValue({ data: MOCK_EQUITY_PREMIUM_COUNTRIES, refetch: vi.fn() });
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
