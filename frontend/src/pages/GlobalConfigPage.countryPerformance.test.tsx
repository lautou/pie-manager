// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for ConfigGeneralePage — MarketCountryManager (Performance des actions).
 * Split out of GlobalConfigPage.test.tsx (which keeps ProductManager) — see that file's own
 * header for why every split file duplicates the full mock setup: GlobalConfigPage always
 * renders every manager on one page, so each test file needs every hook mocked regardless of
 * which manager it focuses on.
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

// Shared by MarketCountryManager (this file) and SectorManager (GlobalConfigPage.sectorPerformance.test.tsx)
// — both validate the same 5-field shape (code/label/index_ticker/currency/index_label) in the
// same order, differing only in button text and typed values. EquityPremiumManager validates a
// genuinely different 6-field shape (no currency, has separate equity/bond tickers+labels) so it
// is NOT parameterized with these — its validation tests stay written out individually.
type ValidationStep = readonly [missing: string, labels: string[], values: string[], errorPattern: RegExp];

function countryLikeValidationSteps(label: string, code: string, ticker: string, currency: string): ValidationStep[] {
  return [
    ['a code', ['Nom'], [label], /Le code est requis/i],
    ['a label', ['Code'], [code], /Le nom est requis/i],
    ['an index ticker', ['Code', 'Nom'], [code, label], /Le ticker indice est requis/i],
    ['a currency', ['Code', 'Nom', 'Ticker indice'], [code, label, ticker], /La devise est requise/i],
    ['an index label', ['Code', 'Nom', 'Ticker indice', 'Devise'], [code, label, ticker, currency], /Le nom de l'indice est requis/i],
  ];
}

const COUNTRY_LIKE_VALIDATION_STEPS = countryLikeValidationSteps('Allemagne', 'de', '^GDAXI', 'EUR');

describe('GlobalConfigPage — MarketCountryManager (Performance des actions)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the market performance section with the country list and top-N setting', () => {
    render(<GlobalConfigPage />);
    expect(screen.getByText(/Performance des actions/i)).toBeTruthy();
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

  it.each(COUNTRY_LIKE_VALIDATION_STEPS)('saving without %s shows validation error', async (_missing, labels, values, errorPattern) => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau pays'));
    for (let i = 0; i < labels.length; i++) {
      await user.type(screen.getByLabelText(labels[i]), values[i]);
    }
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(errorPattern)).toBeTruthy();
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
