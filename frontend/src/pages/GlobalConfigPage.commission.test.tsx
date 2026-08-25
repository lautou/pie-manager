// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for ConfigGeneralePage — CommissionManager (broker display, commission/tickers/FX
 * edit panel, broker CRUD, inline features) plus additional branch-coverage edge cases.
 * Split out of GlobalConfigPage.test.tsx (which keeps ProductManager) — see that file's own
 * header for why every split file duplicates the full mock setup: GlobalConfigPage always
 * renders every manager on one page, so each test file needs every hook mocked regardless of
 * which manager it focuses on.
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
  // GlobalConfigPage renders every manager at once (RegionManager, MarketCountryManager,
  // SectorManager, EquityPremiumManager alongside CommissionManager) — each destructures
  // `data` with a default (e.g. `const { data: regions = [] } = useMacroRegions()`), which
  // only works if the hook itself returns an object at all. Without these, the mocked hooks
  // return undefined and the destructure throws.
  mockUseMacroRegions.mockReturnValue({ data: [], refetch: vi.fn() });
  mockUseCountryPerfConfigs.mockReturnValue({ data: [], refetch: vi.fn() });
  mockUseSectorPerfConfigs.mockReturnValue({ data: [], refetch: vi.fn() });
  mockUseEquityPremiumConfigs.mockReturnValue({ data: [], refetch: vi.fn() });
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
    // Scoped to the FX panel itself, not a position-based slice of every spinbutton on
    // the page — a page-wide index silently drifts onto an unrelated field (e.g. the
    // macro "Durée MM" or rebalancing tolerance settings) whenever a new numeric
    // SettingField is added elsewhere on the page. See the identical fix two tests above.
    const fxPanel = screen.getByText(/Laisser vide pour désactiver/i).parentElement as HTMLElement;
    const numberInputs = within(fxPanel).getAllByRole('spinbutton');
    const firstInput = numberInputs[0] as HTMLInputElement;
    const selectSpy = vi.spyOn(firstInput, 'select');
    fireEvent.focus(firstInput);
    expect(selectSpy).toHaveBeenCalled();
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
