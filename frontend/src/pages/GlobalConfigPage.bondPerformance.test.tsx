// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for ConfigGeneralePage — BondCountryManager (Performance obligataire).
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

const MOCK_COUNTRIES = [
  { code: 'jp', label: 'Japon', index_ticker: '^N225', currency: 'JPY', index_label: 'Nikkei 225' },
  { code: 'gb', label: 'Royaume-Uni', index_ticker: '^FTSE', currency: 'GBP', index_label: 'FTSE 100' },
];

const MOCK_SECTORS = [
  { code: 'or', label: 'Or', index_ticker: 'GC=F', currency: 'USD', index_label: 'Or (COMEX)' },
  { code: 'petrole', label: 'Pétrole', index_ticker: 'CL=F', currency: 'USD', index_label: 'Pétrole (WTI)' },
];

const MOCK_EQUITY_PREMIUM_COUNTRIES = [
  { code: 'de', label: 'Allemagne', equity_ticker: 'EWG', bond_ticker: 'EXX6.DE', equity_label: 'Actions allemandes (EWG)', bond_label: 'Bund (EXX6.DE)' },
  { code: 'ch', label: 'Suisse', equity_ticker: 'EWL', bond_ticker: 'CSBGC0.SW', equity_label: 'Actions suisses (EWL)', bond_label: 'Obligations suisses (CSBGC0.SW)' },
];

// Deliberately different codes from every other manager's mock data on this page (us/fr/jp/gb/
// or/petrole/de/ch) — all five managers render on the same page, so a shared code would
// collide on aria-label queries (this is exactly the pitfall "obligation {code}" disambiguates
// against in the real component).
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

// Same 5-field shape (code/label/index_ticker/currency/index_label) as SectorManager/
// MarketCountryManager — see GlobalConfigPage.sectorPerformance.test.tsx's own comment on why
// this isn't shared across files (each split file is self-contained).
type ValidationStep = readonly [missing: string, labels: string[], values: string[], errorPattern: RegExp];

function countryLikeValidationSteps(label: string, code: string, ticker: string, currency: string): ValidationStep[] {
  return [
    ['a code', ['Nom'], [label], /Le code est requis/i],
    ['a label', ['Code'], [code], /Le nom est requis/i],
    ['an index ticker', ['Code', 'Nom'], [code, label], /Le ticker obligation est requis/i],
    ['a currency', ['Code', 'Nom', 'Ticker obligation'], [code, label, ticker], /La devise est requise/i],
    ['an index label', ['Code', 'Nom', 'Ticker obligation', 'Devise'], [code, label, ticker, currency], /Le nom de l'obligation est requis/i],
  ];
}

const BOND_VALIDATION_STEPS = countryLikeValidationSteps('Suède', 'se', 'XACT-OBLIGATION.ST', 'SEK');

describe('GlobalConfigPage — BondCountryManager (Performance obligataire)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the bond performance section with the country list', () => {
    render(<GlobalConfigPage />);
    expect(screen.getByText(/Performance obligataire/i)).toBeInTheDocument();
    expect(screen.getByText('nz')).toBeInTheDocument();
    expect(screen.getByText('Nouvelle-Zélande')).toBeInTheDocument();
    expect(screen.getByText('NZGB.AX')).toBeInTheDocument();
  });

  it('shows "Aucun pays" when there are no bond countries', () => {
    mockUseBondPerfConfigs.mockReturnValue({ data: [], refetch: vi.fn() });
    render(<GlobalConfigPage />);
    expect(screen.getByText('Aucun pays')).toBeInTheDocument();
  });

  it.each(BOND_VALIDATION_STEPS)('saving without %s shows validation error', async (_missing, labels, values, errorPattern) => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newButtons = screen.getAllByText('Nouvelle obligation');
    await user.click(newButtons[newButtons.length - 1]);
    for (let i = 0; i < labels.length; i++) {
      await user.type(screen.getByLabelText(labels[i]), values[i]);
    }
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(screen.getByText(errorPattern)).toBeInTheDocument();
  }, 10000);

  it('can create a bond country with valid data', async () => {
    const { createBondPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newButtons = screen.getAllByText('Nouvelle obligation');
    await user.click(newButtons[newButtons.length - 1]);
    await user.type(screen.getByLabelText('Code'), 'se');
    await user.type(screen.getByLabelText('Nom'), 'Suède');
    await user.type(screen.getByLabelText("Nom de l'obligation"), 'Obligations suédoises mixtes');
    await user.type(screen.getByLabelText('Ticker obligation'), 'XACT-OBLIGATION.ST');
    await user.type(screen.getByLabelText('Devise'), 'sek');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(createBondPerfConfig).toHaveBeenCalledWith({
      code: 'se', label: 'Suède', index_ticker: 'XACT-OBLIGATION.ST', currency: 'SEK',
      index_label: 'Obligations suédoises mixtes',
    });
  }, 10000);

  it('bond country code input converts to lowercase, currency input converts to uppercase', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newButtons = screen.getAllByText('Nouvelle obligation');
    await user.click(newButtons[newButtons.length - 1]);
    const codeInput = screen.getByLabelText('Code');
    await user.type(codeInput, 'SE');
    expect((codeInput as HTMLInputElement).value).toBe('se');
    const currencyInput = screen.getByLabelText('Devise');
    await user.type(currencyInput, 'sek');
    expect((currencyInput as HTMLInputElement).value).toBe('SEK');
  }, 10000);

  it('create bond country API error shows the returned detail message', async () => {
    const { createBondPerfConfig } = await import('../api/queries');
    vi.mocked(createBondPerfConfig).mockRejectedValueOnce({ response: { data: { detail: "Country 'nz' already exists" } } });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newButtons = screen.getAllByText('Nouvelle obligation');
    await user.click(newButtons[newButtons.length - 1]);
    await user.type(screen.getByLabelText('Code'), 'nz');
    await user.type(screen.getByLabelText('Nom'), 'Nouvelle-Zélande');
    await user.type(screen.getByLabelText("Nom de l'obligation"), "Obligations d'État néo-zélandaises");
    await user.type(screen.getByLabelText('Ticker obligation'), 'NZGB.AX');
    await user.type(screen.getByLabelText('Devise'), 'NZD');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    await rtlWaitFor(() => expect(screen.getByText(/already exists/i)).toBeInTheDocument());
  }, 10000);

  it('create bond country API error without detail uses fallback message', async () => {
    const { createBondPerfConfig } = await import('../api/queries');
    vi.mocked(createBondPerfConfig).mockRejectedValueOnce(new Error('Network error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    const newButtons = screen.getAllByText('Nouvelle obligation');
    await user.click(newButtons[newButtons.length - 1]);
    await user.type(screen.getByLabelText('Code'), 'se');
    await user.type(screen.getByLabelText('Nom'), 'Suède');
    await user.type(screen.getByLabelText("Nom de l'obligation"), 'Obligations suédoises mixtes');
    await user.type(screen.getByLabelText('Ticker obligation'), 'XACT-OBLIGATION.ST');
    await user.type(screen.getByLabelText('Devise'), 'SEK');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    await rtlWaitFor(() => expect(screen.getByText(/Erreur lors de l'enregistrement/i)).toBeInTheDocument());
  }, 10000);

  it('shows edit modal with the code locked when clicking edit for a bond country', async () => {
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Modifier obligation nz/i }));
    expect(screen.getByText(/Modifier le pays — nz/i)).toBeInTheDocument();
    const codeInput = screen.getByLabelText('Code');
    expect((codeInput as HTMLInputElement).disabled).toBe(true);
    expect((codeInput as HTMLInputElement).value).toBe('nz');
  }, 10000);

  it('can save an edited bond country', async () => {
    const { updateBondPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Modifier obligation nz/i }));
    const labelInput = screen.getByLabelText('Nom');
    await user.clear(labelInput);
    await user.type(labelInput, 'NZ');
    const modal = screen.getByTestId('modal');
    await user.click(within(modal).getByText('Enregistrer'));
    expect(updateBondPerfConfig).toHaveBeenCalledWith('nz', {
      label: 'NZ', index_ticker: 'NZGB.AX', currency: 'NZD', index_label: "Obligations d'État néo-zélandaises",
    });
  }, 10000);

  it('can delete a bond country with confirm', async () => {
    const { deleteBondPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer obligation kr/i }));
    await user.click(screen.getByText('Supprimer'));
    expect(deleteBondPerfConfig).toHaveBeenCalledWith('kr');
  }, 10000);

  it('delete cancelled by user does not call deleteBondPerfConfig', async () => {
    const { deleteBondPerfConfig } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer obligation kr/i }));
    await user.click(screen.getByText('Annuler'));
    expect(deleteBondPerfConfig).not.toHaveBeenCalled();
  }, 10000);

  it('delete succeeds with no last-remaining-row guard', async () => {
    const { deleteBondPerfConfig } = await import('../api/queries');
    mockUseBondPerfConfigs.mockReturnValue({ data: [MOCK_BOND_COUNTRIES[0]], refetch: vi.fn() });
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer obligation nz/i }));
    await user.click(screen.getByText('Supprimer'));
    expect(deleteBondPerfConfig).toHaveBeenCalledWith('nz');
  }, 10000);

  it('delete error without detail shows fallback message', async () => {
    const { deleteBondPerfConfig } = await import('../api/queries');
    vi.mocked(deleteBondPerfConfig).mockRejectedValueOnce(new Error('Unknown error'));
    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);
    await user.click(screen.getByRole('button', { name: /Supprimer obligation kr/i }));
    await user.click(screen.getByText('Supprimer'));
    await rtlWaitFor(() => expect(screen.getByText(/Erreur lors de la suppression/i)).toBeInTheDocument());
  }, 10000);
});
