// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for ConfigGeneralePage — SectorManager (Performance des classes d'actifs).
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
const mockUseBondPerfConfigs = vi.fn();

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
  useBondPerfConfigs: (...args: any[]) => mockUseBondPerfConfigs(...args),
  createBondPerfConfig: vi.fn().mockResolvedValue({}),
  updateBondPerfConfig: vi.fn().mockResolvedValue({}),
  deleteBondPerfConfig: vi.fn().mockResolvedValue(undefined),
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

// Deliberately different codes from MOCK_REGIONS/MOCK_COUNTRIES/MOCK_SECTORS/
// MOCK_EQUITY_PREMIUM_COUNTRIES (us/fr/jp/gb/or/petrole/de/ch) — all five managers render on
// the same page, so a shared code would collide on aria-label queries.
const MOCK_BOND_COUNTRIES = [
  { code: 'nz', label: 'Nouvelle-Zélande', index_ticker: 'NZGB.AX', currency: 'NZD', index_label: "Obligations d'État néo-zélandaises" },
  { code: 'kr', label: 'Corée du Sud', index_ticker: '148070.KS', currency: 'KRW', index_label: "Obligations d'État coréennes 10 ans" },
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
  mockUseBondPerfConfigs.mockReturnValue({ data: MOCK_BOND_COUNTRIES, refetch: vi.fn() });
}

// Shared by SectorManager (this file) and MarketCountryManager (GlobalConfigPage.countryPerformance.test.tsx)
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

const SECTOR_VALIDATION_STEPS = countryLikeValidationSteps('Métaux industriels', 'metaux', 'DBB', 'USD');

describe("GlobalConfigPage — SectorManager (Performance des classes d'actifs)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the sector performance section with the sector list (no Top-N setting)', () => {
    render(<GlobalConfigPage />);
    expect(screen.getByText(/Performance des classes d'actifs/i)).toBeInTheDocument();
    expect(screen.getByText('or')).toBeInTheDocument();
    expect(screen.getByText('Or')).toBeInTheDocument();
    expect(screen.getByText('GC=F')).toBeInTheDocument();
    expect(screen.getAllByText('USD').length).toBeGreaterThan(0);
    expect(screen.queryByLabelText(/Nombre de secteurs/i)).toBeNull();
  });

  it('shows "Aucun secteur" when there are no sectors', () => {
    mockUseSectorPerfConfigs.mockReturnValue({ data: [], refetch: vi.fn() });
    render(<GlobalConfigPage />);
    expect(screen.getByText('Aucun secteur')).toBeInTheDocument();
  });

  it.each(SECTOR_VALIDATION_STEPS)('saving without %s shows validation error', async (_missing, labels, values, errorPattern) => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau secteur'));
    for (let i = 0; i < labels.length; i++) {
      await user.type(screen.getByLabelText(labels[i]), values[i]);
    }
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(errorPattern)).toBeInTheDocument();
  }, 10000);

  it('can create a sector with valid data', async () => {
    const { createSectorPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau secteur'));
    await user.type(screen.getByLabelText('Code'), 'metaux');
    await user.type(screen.getByLabelText('Nom'), 'Métaux industriels');
    await user.type(screen.getByLabelText('Nom de l\'indice'), 'Invesco DB Base Metals Fund');
    await user.type(screen.getByLabelText('Ticker indice'), 'DBB');
    await user.type(screen.getByLabelText('Devise'), 'usd');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(createSectorPerfConfig).toHaveBeenCalledWith({
      code: 'metaux', label: 'Métaux industriels', index_ticker: 'DBB', currency: 'USD',
      index_label: 'Invesco DB Base Metals Fund',
    });
  }, 10000);

  it('sector code input converts to lowercase, currency input converts to uppercase', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau secteur'));
    const codeInput = screen.getByLabelText('Code');
    await user.type(codeInput, 'METAUX');
    expect((codeInput as HTMLInputElement).value).toBe('metaux');
    const currencyInput = screen.getByLabelText('Devise');
    await user.type(currencyInput, 'usd');
    expect((currencyInput as HTMLInputElement).value).toBe('USD');
  }, 10000);

  it('create sector API error shows the returned detail message', async () => {
    const { createSectorPerfConfig } = await import('../api/queries');
    vi.mocked(createSectorPerfConfig).mockRejectedValueOnce({ response: { data: { detail: "Sector 'or' already exists" } } });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau secteur'));
    await user.type(screen.getByLabelText('Code'), 'or');
    await user.type(screen.getByLabelText('Nom'), 'Or');
    await user.type(screen.getByLabelText('Nom de l\'indice'), 'Or (COMEX)');
    await user.type(screen.getByLabelText('Ticker indice'), 'GC=F');
    await user.type(screen.getByLabelText('Devise'), 'USD');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    await rtlWaitFor(() => expect(screen.getByText(/already exists/i)).toBeInTheDocument());
  }, 10000);

  it('create sector API error without detail uses fallback message', async () => {
    const { createSectorPerfConfig } = await import('../api/queries');
    vi.mocked(createSectorPerfConfig).mockRejectedValueOnce(new Error('Network error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByText('Nouveau secteur'));
    await user.type(screen.getByLabelText('Code'), 'metaux');
    await user.type(screen.getByLabelText('Nom'), 'Métaux industriels');
    await user.type(screen.getByLabelText('Nom de l\'indice'), 'Invesco DB Base Metals Fund');
    await user.type(screen.getByLabelText('Ticker indice'), 'DBB');
    await user.type(screen.getByLabelText('Devise'), 'USD');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    await rtlWaitFor(() => expect(screen.getByText(/Erreur lors de l'enregistrement/i)).toBeInTheDocument());
  }, 10000);

  it('shows edit modal with the code locked when clicking edit for a sector', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Modifier secteur or/i }));
    expect(screen.getByText(/Modifier le secteur — or/i)).toBeInTheDocument();
    const codeInput = screen.getByLabelText('Code');
    expect((codeInput as HTMLInputElement).disabled).toBe(true);
    expect((codeInput as HTMLInputElement).value).toBe('or');
  }, 10000);

  it('can save an edited sector', async () => {
    const { updateSectorPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Modifier secteur or/i }));
    const labelInput = screen.getByLabelText('Nom');
    await user.clear(labelInput);
    await user.type(labelInput, 'Or physique');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(updateSectorPerfConfig).toHaveBeenCalledWith('or', {
      label: 'Or physique', index_ticker: 'GC=F', currency: 'USD', index_label: 'Or (COMEX)',
    });
  }, 10000);

  it('can delete a sector with confirm', async () => {
    const { deleteSectorPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer secteur petrole/i }));
    await user.click(screen.getByText('Supprimer'));
    expect(deleteSectorPerfConfig).toHaveBeenCalledWith('petrole');
  }, 10000);

  it('delete cancelled by user does not call deleteSectorPerfConfig', async () => {
    const { deleteSectorPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer secteur petrole/i }));
    await user.click(screen.getByText('Annuler'));
    expect(deleteSectorPerfConfig).not.toHaveBeenCalled();
  }, 10000);

  it('delete succeeds with no last-remaining-row guard', async () => {
    const { deleteSectorPerfConfig } = await import('../api/queries');
    mockUseSectorPerfConfigs.mockReturnValue({ data: [MOCK_SECTORS[0]], refetch: vi.fn() });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer secteur or/i }));
    await user.click(screen.getByText('Supprimer'));
    expect(deleteSectorPerfConfig).toHaveBeenCalledWith('or');
  }, 10000);

  it('delete error without detail shows fallback message', async () => {
    const { deleteSectorPerfConfig } = await import('../api/queries');
    vi.mocked(deleteSectorPerfConfig).mockRejectedValueOnce(new Error('Unknown error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer secteur petrole/i }));
    await user.click(screen.getByText('Supprimer'));
    await rtlWaitFor(() => expect(screen.getByText(/Erreur lors de la suppression/i)).toBeInTheDocument());
  }, 10000);
});
