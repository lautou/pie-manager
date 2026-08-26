// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for ConfigGeneralePage — Rééquilibrage (tolerance thresholds).
 * Split out of GlobalConfigPage.test.tsx (which keeps ProductManager) — see that file's own
 * header for why every split file duplicates the full mock setup: GlobalConfigPage always
 * renders every manager on one page, so each test file needs every hook mocked regardless of
 * which manager it focuses on.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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

describe('GlobalConfigPage — Rééquilibrage (tolerance thresholds)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the tolerance section with both threshold fields', () => {
    render(<GlobalConfigPage />);
    expect(screen.getByText(/Rééquilibrage — seuils de tolérance/i)).toBeInTheDocument();
    expect(screen.getByLabelText('Seuil OK (%)')).toBeInTheDocument();
    expect(screen.getByLabelText('Seuil alerte (%)')).toBeInTheDocument();
  });

  it('saving the OK threshold calls mutateAsync with the correct key', async () => {
    const mockMutateAsync = vi.fn().mockResolvedValue({});
    mockUseSetSystemSetting.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });

    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);

    const okInput = screen.getByLabelText('Seuil OK (%)');
    await user.clear(okInput);
    await user.type(okInput, '1.5');
    // Each SettingField wraps its own <label>/<input>/<button> in one flex div —
    // find the "Enregistrer" button that's a sibling of this specific input.
    const saveBtn = screen.getAllByText('Enregistrer').find((b) => b.closest('div')?.contains(okInput))!;
    await user.click(saveBtn);

    expect(mockMutateAsync).toHaveBeenCalledWith({ key: 'rebalancing.tolerance_ok_pct', value: '1.5' });
  }, 10000);

  it('saving the warning threshold calls mutateAsync with the correct key', async () => {
    const mockMutateAsync = vi.fn().mockResolvedValue({});
    mockUseSetSystemSetting.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });

    const user = userEvent.setup({ delay: null });
    render(<GlobalConfigPage />);

    const warningInput = screen.getByLabelText('Seuil alerte (%)');
    await user.clear(warningInput);
    await user.type(warningInput, '3');
    const saveBtn = screen.getAllByText('Enregistrer').find((b) => b.closest('div')?.contains(warningInput))!;
    await user.click(saveBtn);

    expect(mockMutateAsync).toHaveBeenCalledWith({ key: 'rebalancing.tolerance_warning_pct', value: '3' });
  }, 10000);
});
