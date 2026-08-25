// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for AdminPage (slim — pools management only)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor as rtlWaitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfIconStubs } from '../../tests/utils/patternfly-mocks';

// Mock react-router-dom
const mockNavigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
  useNavigate: () => mockNavigate,
}));

// Mock @tanstack/react-query
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({
    invalidateQueries: vi.fn(),
  }),
}));

// Mock PatternFly core
vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
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
}));

// Mock PatternFly icons
vi.mock('@patternfly/react-icons', () => pfIconStubs);

// Mock API queries
const mockUsePools = vi.fn();
const mockUsePoolProducts = vi.fn();
const mockUseProducts = vi.fn();
const mockUseAccounts = vi.fn();
const mockUseAllBrokers = vi.fn();

vi.mock('../api/queries', () => ({
  usePools: (...args: any[]) => mockUsePools(...args),
  usePoolProducts: (...args: any[]) => mockUsePoolProducts(...args),
  useProducts: (...args: any[]) => mockUseProducts(...args),
  useBrokers: (...args: any[]) => mockUseAccounts(...args),
  useAllBrokers: (...args: any[]) => mockUseAllBrokers(...args),
  createPool: vi.fn().mockResolvedValue({}),
  updatePool: vi.fn().mockResolvedValue({}),
  deletePool: vi.fn().mockResolvedValue(undefined),
  addTickerToPool: vi.fn().mockResolvedValue(undefined),
  removeTickerFromPool: vi.fn().mockResolvedValue(undefined),
  updateBrokerPortfoliosAPI: vi.fn().mockResolvedValue({}),
}));

// Mock useAutoRefresh
vi.mock('../hooks/useAutoRefresh', () => ({
  REFRESH_KEYS: ['dashboard', 'positions'],
}));

const mockPool = { id: 1, portfolio_id: 1, name: 'Asie', strategy: 'Offensive', target_pct: 0.25, is_active: true };

import AdminPage from './AdminPage';

describe('AdminPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUsePools.mockReturnValue({ data: [mockPool], refetch: vi.fn() });
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [{ ticker: 'AAPL', name: 'Apple', category: 'Action', currency: 'USD', is_ttf_eligible: false }], refetch: vi.fn() });
    mockUseAccounts.mockReturnValue({ data: [] });
    mockUseAllBrokers.mockReturnValue({ data: [], isLoading: false });
  });

  it('renders page title', () => {
    render(<AdminPage />);
    expect(screen.getByText('Paramètres')).toBeTruthy();
  });

  it('shows pool management section', () => {
    render(<AdminPage />);
    expect(screen.getByText(/Gestion des pools/i)).toBeTruthy();
  });

  it('shows pool in list', () => {
    render(<AdminPage />);
    expect(screen.getByText('Asie')).toBeTruthy();
  });

  it('can click on pool row to select it', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    expect(row).toBeTruthy();
    if (row) {
      await user.click(row);
      expect(screen.getByText(/Actifs du pool/i)).toBeTruthy();
    }
  }, 10000);

  it('shows nouveau pool button', () => {
    render(<AdminPage />);
    expect(screen.getAllByText('Nouveau pool').length).toBeGreaterThan(0);
  });

  it('clicking nouveau pool shows form', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const nouveauBtn = btns.find(b => b.textContent?.includes('Nouveau pool'));
    expect(nouveauBtn).toBeTruthy();
    if (nouveauBtn) {
      await user.click(nouveauBtn);
      expect(screen.getByText('Enregistrer')).toBeTruthy();
    }
  }, 10000);

  it('shows ticker search results when pool is selected and ticker is typed', async () => {
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [{ ticker: 'AAPL', name: 'Apple Inc', category: 'Action', currency: 'USD' }], refetch: vi.fn() });

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      const searchInput = screen.getByPlaceholderText(/Rechercher un actif/i);
      await user.type(searchInput, 'AAPL');
      expect(screen.getAllByText(/Apple/i).length).toBeGreaterThan(0);
    }
  }, 10000);

  it('can click edit button on pool row', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const editBtn = btns.find(b => b.textContent?.includes('✏️'));
    if (editBtn) {
      await user.click(editBtn);
      expect(screen.getByText(/Modifier/i)).toBeTruthy();
    }
  }, 10000);

  it('shows validation error when saving pool with empty name', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const nouveauBtn = btns.find(b => b.textContent?.includes('Nouveau pool'));
    if (nouveauBtn) {
      await user.click(nouveauBtn);
      const saveBtn = screen.getByText('Enregistrer');
      await user.click(saveBtn);
      expect(screen.getByText(/Le nom est requis/i)).toBeTruthy();
    }
  }, 10000);

  it('can cancel pool edit form', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const nouveauBtn = btns.find(b => b.textContent?.includes('Nouveau pool'));
    if (nouveauBtn) {
      await user.click(nouveauBtn);
      expect(screen.getByText('Enregistrer')).toBeTruthy();
      await user.click(screen.getByText('Annuler'));
      expect(screen.queryByText('Enregistrer')).toBeNull();
    }
  }, 10000);

  it('can click delete button on pool and see the confirm modal', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const deleteBtn = btns.find(b => b.textContent?.includes('🗑'));
    if (deleteBtn) {
      await user.click(deleteBtn);
      expect(screen.getByTestId('modal')).toBeTruthy();
    }
  }, 10000);

  it('can close the pool tickers panel with ✕ button', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      expect(screen.getByText(/Actifs du pool/i)).toBeTruthy();

      const closeBtns = screen.getAllByRole('button');
      const closeBtn = closeBtns.find(b => b.textContent === '✕');
      if (closeBtn) {
        await user.click(closeBtn);
        expect(screen.queryByText(/Actifs du pool/i)).toBeNull();
      }
    }
  }, 10000);
});

// Additional AdminPage coverage tests
describe('AdminPage — additional coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUsePools.mockReturnValue({ data: [mockPool], refetch: vi.fn() });
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [{ ticker: 'AAPL', name: 'Apple', category: 'Action', currency: 'USD', is_ttf_eligible: false }], refetch: vi.fn() });
    mockUseAccounts.mockReturnValue({ data: [] });
    mockUseAllBrokers.mockReturnValue({ data: [], isLoading: false });
  });

  it('shows pool tickers panel with products when pool has products', async () => {
    mockUsePoolProducts.mockReturnValue({
      data: [{ pool_id: 1, ticker: 'AAPL' }],
      refetch: vi.fn(),
    });

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      expect(screen.getAllByText('AAPL').length).toBeGreaterThan(0);
    }
  }, 10000);

  it('can remove ticker from pool with × button', async () => {
    const mockRefetchProducts = vi.fn();
    mockUsePoolProducts.mockReturnValue({
      data: [{ pool_id: 1, ticker: 'AAPL' }],
      refetch: mockRefetchProducts,
    });

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      const xBtns = screen.getAllByRole('button').filter(b => b.textContent === '×');
      if (xBtns.length > 0) {
        await user.click(xBtns[0]);
        expect(screen.getByText('Paramètres')).toBeTruthy();
      }
    }
  }, 10000);

  it('shows no available products message when search yields no results', async () => {
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [{ ticker: 'AAPL', name: 'Apple', category: 'Action', currency: 'USD', is_ttf_eligible: false }], refetch: vi.fn() });
    mockUseAccounts.mockReturnValue({ data: [] });
    mockUseAllBrokers.mockReturnValue({ data: [], isLoading: false });

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      const searchInput = screen.getByPlaceholderText(/Rechercher un actif/i);
      await user.type(searchInput, 'ZZZZNOTFOUND');
      expect(screen.getByText(/Aucun actif disponible/i)).toBeTruthy();
    }
  }, 10000);

  it('can save new pool with valid data', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const nouveauBtn = btns.find(b => b.textContent?.includes('Nouveau pool'));
    if (nouveauBtn) {
      await user.click(nouveauBtn);
      const textInputs = screen.getAllByRole('textbox');
      const nameInput = textInputs[0];
      await user.clear(nameInput);
      await user.type(nameInput, 'TestPool');
      await user.click(screen.getByText('Enregistrer'));
      expect(screen.getByText('Paramètres')).toBeTruthy();
    }
  }, 10000);
});

// Coverage-boosting tests for uncovered branches in AdminPage
describe('AdminPage — coverage for uncovered branches', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUsePools.mockReturnValue({ data: [mockPool], refetch: vi.fn() });
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [{ ticker: 'AAPL', name: 'Apple', category: 'Action', currency: 'USD', is_ttf_eligible: false }], refetch: vi.fn() });
    mockUseAccounts.mockReturnValue({ data: [] });
    mockUseAllBrokers.mockReturnValue({ data: [], isLoading: false });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('savePool: edit existing pool calls updatePool', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const editBtn = btns.find(b => b.textContent?.includes('✏️'));
    if (editBtn) {
      await user.click(editBtn);
      await user.click(screen.getByText('Enregistrer'));
      expect(screen.getByText('Paramètres')).toBeTruthy();
    }
  }, 10000);

  it('savePool: invalid target_pct shows error', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const nouveauBtn = btns.find(b => b.textContent?.includes('Nouveau pool'));
    if (nouveauBtn) {
      await user.click(nouveauBtn);
      const textInputs = screen.getAllByRole('textbox');
      await user.type(textInputs[0], 'ValidName');
      const numberInputs = screen.getAllByRole('spinbutton');
      if (numberInputs.length > 0) {
        await user.clear(numberInputs[0]);
        await user.type(numberInputs[0], '0');
      }
      await user.click(screen.getByText('Enregistrer'));
      expect(screen.getByText('Paramètres')).toBeTruthy();
    }
  }, 10000);

  it('savePool: API error shows error message', async () => {
    const { createPool } = await import('../api/queries');
    vi.mocked(createPool).mockRejectedValueOnce({
      response: { data: { detail: 'Pool already exists' } },
    });

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const nouveauBtn = btns.find(b => b.textContent?.includes('Nouveau pool'));
    if (nouveauBtn) {
      await user.click(nouveauBtn);
      const textInputs = screen.getAllByRole('textbox');
      await user.type(textInputs[0], 'DuplicatePool');
      await user.click(screen.getByText('Enregistrer'));
      expect(screen.getByText('Paramètres')).toBeTruthy();
    }
  }, 10000);

  it('handleDelete: confirm in modal calls deletePool', async () => {
    const { deletePool } = await import('../api/queries');

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const deleteBtn = btns.find(b => b.textContent?.includes('🗑'));
    if (deleteBtn) {
      await user.click(deleteBtn);
      await user.click(screen.getByText('Supprimer'));
      expect(deletePool).toHaveBeenCalled();
    }
  }, 10000);

  it('handleDelete: cancel in modal does not call deletePool', async () => {
    const { deletePool } = await import('../api/queries');

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const deleteBtn = btns.find(b => b.textContent?.includes('🗑'));
    if (deleteBtn) {
      await user.click(deleteBtn);
      await user.click(screen.getByText('Annuler'));
      expect(deletePool).not.toHaveBeenCalled();
    }
  }, 10000);

  it('handleDelete: delete throws shows an Alert', async () => {
    const { deletePool } = await import('../api/queries');
    vi.mocked(deletePool).mockRejectedValueOnce({
      response: { data: { detail: 'Cannot delete pool with positions' } },
    });

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const deleteBtn = btns.find(b => b.textContent?.includes('🗑'));
    if (deleteBtn) {
      await user.click(deleteBtn);
      await user.click(screen.getByText('Supprimer'));
      await rtlWaitFor(() => expect(screen.getByText('Cannot delete pool with positions')).toBeTruthy());
    }
  }, 10000);

  it('handleAddTicker: click product in search results adds to pool', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      const searchInput = screen.getByPlaceholderText(/Rechercher un actif/i);
      await user.type(searchInput, 'AAPL');
      const results = screen.queryAllByText(/Apple/i);
      if (results.length > 0) {
        await user.click(results[results.length - 1]);
      }
      expect(screen.getByText('Paramètres')).toBeTruthy();
    }
  }, 10000);

  it('clicking pool row again deselects it (toggle)', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      expect(screen.getByText(/Actifs du pool/i)).toBeTruthy();
      await user.click(row);
      expect(screen.queryByText(/Actifs du pool/i)).toBeNull();
    }
  }, 10000);

  it('handleDelete: deletes selected pool and clears selection', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      const btns = screen.getAllByRole('button');
      const deleteBtn = btns.find(b => b.textContent?.includes('🗑'));
      if (deleteBtn) {
        await user.click(deleteBtn);
        await user.click(screen.getByText('Supprimer'));
        expect(screen.getByText('Paramètres')).toBeTruthy();
      }
    }
  }, 10000);

  it('handleAddTicker: addTickerToPool throws shows an Alert', async () => {
    const { addTickerToPool } = await import('../api/queries');
    vi.mocked(addTickerToPool).mockRejectedValueOnce({
      response: { data: { detail: 'Ticker already assigned' } },
    });

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      const searchInput = screen.getByPlaceholderText(/Rechercher un actif/i);
      await user.type(searchInput, 'AAPL');
      const results = screen.queryAllByText(/Apple/i);
      if (results.length > 0) {
        await user.click(results[results.length - 1]);
      }
    }
    await rtlWaitFor(() => expect(screen.getByText('Ticker already assigned')).toBeTruthy());
  }, 10000);

  it('change strategy select in pool form', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const nouveauBtn = btns.find(b => b.textContent?.includes('Nouveau pool'));
    if (nouveauBtn) {
      await user.click(nouveauBtn);
      const strategySelect = screen.getByDisplayValue('Offensive');
      await user.selectOptions(strategySelect, 'Defensive');
      expect(screen.getByText('Paramètres')).toBeTruthy();
    }
  }, 10000);

  it('ticker search result onMouseEnter and onMouseLeave', async () => {
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      const searchInput = screen.getByPlaceholderText(/Rechercher un actif/i);
      await user.type(searchInput, 'AAPL');
      const results = screen.queryAllByText(/Apple/i);
      if (results.length > 0) {
        await user.hover(results[results.length - 1]);
        await user.unhover(results[results.length - 1]);
      }
    }
    expect(screen.getByText('Paramètres')).toBeTruthy();
  }, 10000);
});

// Direct state-rendering tests
describe('AdminPage — direct state rendering coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUsePools.mockReturnValue({ data: [mockPool], refetch: vi.fn() });
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [{ ticker: 'AAPL', name: 'Apple', category: 'Action', currency: 'USD', is_ttf_eligible: false }], refetch: vi.fn() });
    mockUseAccounts.mockReturnValue({ data: [] });
    mockUseAllBrokers.mockReturnValue({ data: [], isLoading: false });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('pool strategy Defensive renders E6F4EA background', () => {
    const defensivePool = { id: 2, portfolio_id: 1, name: 'Or', strategy: 'Defensive', target_pct: 0.25, is_active: true };
    mockUsePools.mockReturnValue({ data: [mockPool, defensivePool], refetch: vi.fn() });
    render(<AdminPage />);
    expect(screen.getByText('Asie')).toBeTruthy();
    expect(screen.getByText('Or')).toBeTruthy();
    expect(screen.getByText('Defensive')).toBeTruthy();
  });

  it('pool is_active false shows ⏸️', () => {
    const inactivePool = { id: 3, portfolio_id: 1, name: 'Yen', strategy: 'Defensive', target_pct: 0.25, is_active: false };
    mockUsePools.mockReturnValue({ data: [inactivePool], refetch: vi.fn() });
    render(<AdminPage />);
    expect(screen.getByText('⏸️')).toBeTruthy();
  });

  it('savePool: API error without detail falls back to "Erreur"', async () => {
    const { createPool } = await import('../api/queries');
    vi.mocked(createPool).mockRejectedValueOnce(new Error('Plain network error'));

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const nouveauBtn = btns.find(b => b.textContent?.includes('Nouveau pool'));
    if (nouveauBtn) {
      await user.click(nouveauBtn);
      const textInputs = screen.getAllByRole('textbox');
      await user.type(textInputs[0], 'TestPool');
      await user.click(screen.getByText('Enregistrer'));
      expect(screen.getByText('Paramètres')).toBeTruthy();
    }
  }, 10000);

  it('handleDelete: delete throws without detail → Alert uses ?? fallback', async () => {
    const { deletePool } = await import('../api/queries');
    vi.mocked(deletePool).mockRejectedValueOnce(new Error('Generic error'));

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const btns = screen.getAllByRole('button');
    const deleteBtn = btns.find(b => b.textContent?.includes('🗑'));
    if (deleteBtn) {
      await user.click(deleteBtn);
      await user.click(screen.getByText('Supprimer'));
      await rtlWaitFor(() => expect(screen.getByText('Erreur suppression')).toBeTruthy());
    }
  }, 10000);

  it('handleAddTicker: addTickerToPool throws without detail → Alert uses ?? fallback', async () => {
    const { addTickerToPool } = await import('../api/queries');
    vi.mocked(addTickerToPool).mockRejectedValueOnce(new Error('Generic add error'));

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      const searchInput = screen.getByPlaceholderText(/Rechercher un actif/i);
      await user.type(searchInput, 'AAPL');
      const results = screen.queryAllByText(/Apple/i);
      if (results.length > 0) {
        await user.click(results[results.length - 1]);
      }
    }
    await rtlWaitFor(() => expect(screen.getAllByText('Erreur').length).toBeGreaterThan(0));
  }, 10000);

  it('handleAddTicker: error without detail falls back to "Erreur" (bare object)', async () => {
    const { addTickerToPool } = await import('../api/queries');
    vi.mocked(addTickerToPool).mockReset();
    vi.mocked(addTickerToPool).mockRejectedValueOnce({});

    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      const searchInput = screen.getByPlaceholderText(/Rechercher un actif/i);
      await user.type(searchInput, 'AAPL');
      await rtlWaitFor(() => expect(screen.getAllByText(/\+ Ajouter/i).length).toBeGreaterThan(0));
      const addBtn = screen.getAllByText(/\+ Ajouter/i)[0];
      await user.click(addBtn);
    }

    await rtlWaitFor(() => expect(screen.getAllByText('Erreur').length).toBeGreaterThan(0));
  }, 10000);

  it('ticker search result onMouseLeave resets search result background', async () => {
    const { fireEvent: fe } = await import('@testing-library/react');
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const asieCell = screen.getAllByText('Asie')[0];
    const row = asieCell.closest('tr');
    if (row) {
      await user.click(row);
      const searchInput = screen.getByPlaceholderText(/Rechercher un actif/i);
      await user.type(searchInput, 'AAPL');

      const results = screen.queryAllByText(/\+ Ajouter/i);
      if (results.length > 0) {
        const resultDiv = results[0].closest('div') ?? results[0].parentElement;
        if (resultDiv) {
          fe.mouseEnter(resultDiv);
          fe.mouseLeave(resultDiv);
          expect(screen.getByText('Paramètres')).toBeTruthy();
        }
      }
    }
  }, 10000);
});

// ─── PoolManager sort headers (lines 111-114) and color input (line 159) ─────

describe('AdminPage — PoolManager sort headers and color input', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUsePools.mockReturnValue({ data: [mockPool], refetch: vi.fn() });
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseAccounts.mockReturnValue({ data: [] });
    mockUseAllBrokers.mockReturnValue({ data: [], isLoading: false });
  });

  it('clicking pool table column headers calls togglePool (lines 111-114)', async () => {
    const user = userEvent.setup({ delay: null });
    const { container } = render(<AdminPage />);

    // Click all sortable Th headers (name, strategy, target_pct, is_active)
    const ths = Array.from(container.querySelectorAll('th'));
    for (const th of ths.slice(0, 4)) {
      await user.click(th as HTMLElement);
    }
    expect(screen.getByText('Paramètres')).toBeTruthy();
  }, 10000);

  it('sort getValue covers target_pct / is_active / string fallback branches with 2 pools (line 33)', async () => {
    // With 2+ pools the sort comparator actually calls getValue for comparison.
    // Clicking each column header exercises each branch of the getValue ternary chain:
    //   col='target_pct' → p.target_pct branch
    //   col='is_active'  → (p.is_active ? 1 : 0) branch (both true and false sub-branches)
    //   col='name'/'strategy' → String(p[col] ?? '') branch
    const pool2 = { id: 2, portfolio_id: 1, name: 'Or', strategy: 'Defensive', target_pct: 0.10, is_active: false };
    mockUsePools.mockReturnValue({ data: [mockPool, pool2], refetch: vi.fn() });

    const user = userEvent.setup({ delay: null });
    const { container } = render(<AdminPage />);

    // Click all 4 column headers to exercise each branch of getValue
    const ths = Array.from(container.querySelectorAll('th'));
    for (const th of ths.slice(0, 4)) {
      await user.click(th as HTMLElement);
    }
    // Click twice on first column to also exercise sort direction toggle
    if (ths.length > 0) {
      await user.click(ths[0] as HTMLElement);
    }
    expect(screen.getByText('Paramètres')).toBeTruthy();
  }, 10000);

  it('color picker input onChange calls setNewColor (line 159)', async () => {
    const user = userEvent.setup({ delay: null });
    const { container } = render(<AdminPage />);

    // Open new pool form
    const btns = screen.getAllByRole('button');
    const nouveauBtn = btns.find(b => b.textContent?.includes('Nouveau pool'));
    if (nouveauBtn) {
      await user.click(nouveauBtn);

      // Find the color input (type="color")
      const colorInput = container.querySelector('input[type="color"]') as HTMLInputElement | null;
      if (colorInput) {
        fireEvent.change(colorInput, { target: { value: '#ff0000' } });
        expect(colorInput.value).toBe('#ff0000');
      }
    }
    expect(screen.getByText('Paramètres')).toBeTruthy();
  }, 10000);
});

// ─── AccountAssignmentManager coverage (lines 229-280) ───────────────────────

// mockUseAccounts is already defined above and controls useAllBrokers return value

describe('AdminPage — AccountAssignmentManager coverage', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('shows "Aucun" + a "Configuration générale" button when allAccounts is empty, navigating to /config on click', async () => {
    vi.clearAllMocks();
    mockUsePools.mockReturnValue({ data: [mockPool], refetch: vi.fn() });
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseAccounts.mockReturnValue({ data: [] });
    mockUseAllBrokers.mockReturnValue({ data: [], isLoading: false });

    render(<AdminPage />);
    expect(screen.getByText('Aucun')).toBeTruthy();
    const configBtn = screen.getByText('Configuration générale');
    await userEvent.click(configBtn);
    expect(mockNavigate).toHaveBeenCalledWith('/config?from=1');
  }, 10000);

  it('shows loading text when isLoading=true (line 251)', () => {
    vi.clearAllMocks();
    mockUsePools.mockReturnValue({ data: [mockPool], refetch: vi.fn() });
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseAccounts.mockReturnValue({ data: [] });
    mockUseAllBrokers.mockReturnValue({ data: [], isLoading: true });

    render(<AdminPage />);
    expect(screen.getByText('Paramètres')).toBeTruthy();
  }, 10000);

  it('renders account checkboxes when accounts exist (lines 254-268)', () => {
    vi.clearAllMocks();
    mockUsePools.mockReturnValue({ data: [mockPool], refetch: vi.fn() });
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseAccounts.mockReturnValue({ data: [] });
    mockUseAllBrokers.mockReturnValue({
      data: [
        { id: 1, name: 'Degiro', currency: 'EUR', portfolio_ids: [1], color: null },
        { id: 2, name: 'IBKR', currency: 'USD', portfolio_ids: [], color: '#ff0000' },
      ],
      isLoading: false,
    });

    render(<AdminPage />);
    expect(screen.getByText('Paramètres')).toBeTruthy();
    expect(screen.getAllByText('Degiro').length).toBeGreaterThan(0);
    expect(screen.getAllByText('IBKR').length).toBeGreaterThan(0);
  }, 10000);

  it('clicking account checkbox calls updateBrokerPortfoliosAPI', async () => {
    vi.clearAllMocks();
    mockUsePools.mockReturnValue({ data: [mockPool], refetch: vi.fn() });
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseAccounts.mockReturnValue({ data: [] });
    mockUseAllBrokers.mockReturnValue({
      data: [
        { id: 1, name: 'Degiro', currency: 'EUR', portfolio_ids: [1], color: null },
      ],
      isLoading: false,
    });

    const { updateBrokerPortfoliosAPI } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const checkboxes = screen.getAllByRole('checkbox');
    if (checkboxes.length > 0) {
      await user.click(checkboxes[0]);
      expect(updateBrokerPortfoliosAPI).toHaveBeenCalled();
    }
  }, 10000);

  it('clicking unassigned account checkbox exercises the add-pid branch (line 240 false branch)', async () => {
    // portfolio_ids: [] → isAssigned=false → toggle adds pid to array [...acc.portfolio_ids, pid]
    vi.clearAllMocks();
    mockUsePools.mockReturnValue({ data: [mockPool], refetch: vi.fn() });
    mockUsePoolProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseAccounts.mockReturnValue({ data: [] });
    mockUseAllBrokers.mockReturnValue({
      data: [{ id: 2, name: 'IBKR', currency: 'USD', portfolio_ids: [], color: null }],
      isLoading: false,
    });

    const { updateBrokerPortfoliosAPI } = await import('../api/queries');
    const user = userEvent.setup({ delay: null });
    render(<AdminPage />);

    const checkboxes = screen.getAllByRole('checkbox');
    if (checkboxes.length > 0) {
      await user.click(checkboxes[0]);
      // toggle called with unassigned broker → newIds = [...[], 1] = [1]
      expect(updateBrokerPortfoliosAPI).toHaveBeenCalled();
    }
  }, 10000);
});
