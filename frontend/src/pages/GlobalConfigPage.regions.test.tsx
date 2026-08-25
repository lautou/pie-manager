// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for ConfigGeneralePage — RegionManager (Indicateurs macro).
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
