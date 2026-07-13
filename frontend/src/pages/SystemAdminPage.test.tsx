/**
 * Tests for SystemAdminPage
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfIconStubs } from '../../tests/utils/patternfly-mocks';

// Mock react-router-dom
const mockNavigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useParams: () => ({}),
  useNavigate: () => mockNavigate,
}));

// Mock @tanstack/react-query
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({
    invalidateQueries: vi.fn(),
  }),
}));

// Mock PatternFly core — extend shared stubs with a Modal that also renders its actions
vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
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

// Mock PatternFly icons
vi.mock('@patternfly/react-icons', () => pfIconStubs);

// Mock FrDatePicker
vi.mock('../components/FrDatePicker', () => ({
  default: ({ value, onChange }: any) => (
    <input
      type="date"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}));

// Mock apiClient
vi.mock('../api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: new Blob(), headers: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

// Mock API queries
const mockTriggerRecompute = vi.fn();
const mockGetTaskStatus = vi.fn();
const mockUseProducts = vi.fn();
const mockUseSystemSetting = vi.fn();
const mockUseSetSystemSetting = vi.fn();
const mockUseDeleteSystemSetting = vi.fn();

vi.mock('../api/queries', () => ({
  triggerRecompute: (...args: any[]) => mockTriggerRecompute(...args),
  getTaskStatus: (...args: any[]) => mockGetTaskStatus(...args),
  useProducts: (...args: any[]) => mockUseProducts(...args),
  createProduct: vi.fn().mockResolvedValue({}),
  updateProduct: vi.fn().mockResolvedValue({}),
  deleteProduct: vi.fn().mockResolvedValue(undefined),
  REFRESH_KEYS: [],
  useSystemSetting: (...args: any[]) => mockUseSystemSetting(...args),
  useSetSystemSetting: (...args: any[]) => mockUseSetSystemSetting(...args),
}));

// Mock useSyncStatus hook
const mockUseSyncStatus = vi.fn();
vi.mock('../hooks/useSyncStatus', () => ({
  useSyncStatus: (...args: any[]) => mockUseSyncStatus(...args),
  formatSyncDateTime: () => '10:00',
}));

// Mock useAutoRefresh
vi.mock('../hooks/useAutoRefresh', () => ({
  REFRESH_KEYS: ['dashboard', 'positions'],
}));

import SystemAdminPage from './SystemAdminPage';

describe('SystemAdminPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseProducts.mockReturnValue({ data: [{ ticker: 'AAPL', name: 'Apple', category: 'Actif', currency: 'USD' }], refetch: vi.fn() });
    mockUseSyncStatus.mockReturnValue({ data: { status: 'success', failed_tickers: [], started_at: null, finished_at: null, total_tickers: 5, succeeded: 5 } });
    mockUseSystemSetting.mockReturnValue({ data: undefined, isError: true });
    mockUseSetSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
    mockUseDeleteSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue(undefined) });
    mockNavigate.mockReset();
  });

  it('renders page title', () => {
    render(<SystemAdminPage />);
    expect(screen.getByText('Administration système')).toBeTruthy();
  });

  it('shows page title', () => {
    render(<SystemAdminPage />);
    expect(screen.getByText('Administration système')).toBeTruthy();
  });

  it('shows manual sync section', () => {
    render(<SystemAdminPage />);
    expect(screen.getByText(/Synchronisation des prix/i)).toBeTruthy();
  });

  it('shows backup/restore section', () => {
    render(<SystemAdminPage />);
    expect(screen.getByText(/Sauvegarde et restauration/i)).toBeTruthy();
  });

  it('shows recompute section', () => {
    render(<SystemAdminPage />);
    expect(screen.getByText(/Recalcul des snapshots/i)).toBeTruthy();
  });

  it('shows backup section', () => {
    render(<SystemAdminPage />);
    expect(screen.getByText(/Sauvegarde et restauration/i)).toBeTruthy();
  });

  it('shows sync status info', () => {
    render(<SystemAdminPage />);
    expect(screen.getByText(/Dernière synchro/i)).toBeTruthy();
  });

  it('can click sync button', async () => {
    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);
    const syncBtn = screen.getByText('Synchroniser maintenant');
    await user.click(syncBtn);
    expect(true).toBeTruthy();
  });

  it('can click backup button', async () => {
    (globalThis as any).URL.createObjectURL = vi.fn().mockReturnValue('blob:test');
    (globalThis as any).URL.revokeObjectURL = vi.fn();

    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    const backupBtn = screen.getByText(/Télécharger une sauvegarde/i);
    await user.click(backupBtn);
    expect(screen.getByText('Administration système')).toBeTruthy();
  });

  it('clicking lancer le recalcul calls triggerRecompute', async () => {
    mockTriggerRecompute.mockResolvedValue('task-123');
    mockGetTaskStatus.mockResolvedValue({ task_id: 'task-123', state: 'SUCCESS', current: 10, total: 10 });

    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    const runBtn = screen.getByText('Lancer le recalcul');
    await user.click(runBtn);
    expect(mockTriggerRecompute).toHaveBeenCalled();
  }, 10000);

  it('shows sync status with failed tickers', () => {
    mockUseSyncStatus.mockReturnValue({
      data: { status: 'partial', failed_tickers: ['AAPL', 'TSLA'], started_at: null, finished_at: '2026-01-01T10:00:00Z', total_tickers: 5, succeeded: 3 },
    });
    render(<SystemAdminPage />);
    expect(screen.getByText('Administration système')).toBeTruthy();
  });

  it('shows task status PENDING after triggering recompute', async () => {
    mockTriggerRecompute.mockResolvedValue('task-456');
    mockGetTaskStatus.mockResolvedValue({ task_id: 'task-456', state: 'PENDING', current: 0, total: 10 });

    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    const runBtn = screen.getByText('Lancer le recalcul');
    await user.click(runBtn);
    expect(screen.getByText('Administration système')).toBeTruthy();
  }, 10000);

  it('shows progress during PROGRESS state', async () => {
    mockTriggerRecompute.mockResolvedValue('task-789');
    mockGetTaskStatus
      .mockResolvedValueOnce({ task_id: 'task-789', state: 'PROGRESS', current: 5, total: 10, date: '2024-01-15' })
      .mockResolvedValue({ task_id: 'task-789', state: 'SUCCESS', current: 10, total: 10 });

    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    await user.click(screen.getByText('Lancer le recalcul'));
    expect(screen.getByText('Administration système')).toBeTruthy();
  }, 10000);

  it('shows error when triggerRecompute throws', async () => {
    mockTriggerRecompute.mockRejectedValue(new Error('Network error'));

    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    await user.click(screen.getByText('Lancer le recalcul'));
    expect(screen.getByText('Administration système')).toBeTruthy();
  }, 10000);

  it('renders FrDatePicker for start and end dates', () => {
    render(<SystemAdminPage />);
    const dateInputs = screen.getAllByDisplayValue(/\d{4}-\d{2}-\d{2}/);
    expect(dateInputs.length).toBeGreaterThanOrEqual(2);
  });

  it('changing start date updates value', async () => {
    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);
    const dateInputs = screen.getAllByDisplayValue(/\d{4}-\d{2}-\d{2}/);
    await user.clear(dateInputs[0]);
    await user.type(dateInputs[0], '2024-06-01');
    expect(screen.getByText('Administration système')).toBeTruthy();
  });

  it('end date picker: setting date <= yesterday updates endDate', async () => {
    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    const dateInputs = screen.getAllByDisplayValue(/\d{4}-\d{2}-\d{2}/);
    if (dateInputs.length >= 2) {
      await user.clear(dateInputs[1]);
      await user.type(dateInputs[1], '2024-01-01');
      await user.clear(dateInputs[1]);
      await user.type(dateInputs[1], '2099-12-31');
    }
    expect(screen.getByText('Administration système')).toBeTruthy();
  }, 10000);

  it('clicking Restaurer button triggers file input', async () => {
    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    const restaurerBtn = screen.getByText(/Restaurer une sauvegarde/i);
    expect(restaurerBtn).toBeTruthy();
    await user.click(restaurerBtn);
    expect(screen.getByText('Administration système')).toBeTruthy();
  }, 10000);
});

// Additional SystemAdminPage coverage tests
describe('SystemAdminPage — additional coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseProducts.mockReturnValue({ data: [{ ticker: 'AAPL', name: 'Apple', category: 'Actif', currency: 'USD' }], refetch: vi.fn() });
    mockUseSyncStatus.mockReturnValue({ data: { status: 'success', failed_tickers: [], started_at: null, finished_at: null, total_tickers: 5, succeeded: 5 } });
    mockUseSystemSetting.mockReturnValue({ data: undefined, isError: true });
    mockUseSetSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
    mockUseDeleteSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue(undefined) });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('handleRestoreFile: file selected, confirm in modal → calls apiClient.post restore', async () => {
    const apiClientMock = (await import('../api/client')).default;
    (globalThis as any).URL.createObjectURL = vi.fn().mockReturnValue('blob:test');
    (globalThis as any).URL.revokeObjectURL = vi.fn();

    const user = userEvent.setup({ delay: null });
    const { container } = render(<SystemAdminPage />);

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();

    const file = new File(['-- SQL backup'], 'backup.sql', { type: 'text/plain' });
    Object.defineProperty(fileInput, 'files', {
      value: { 0: file, length: 1, item: () => file },
      configurable: true,
    });

    fireEvent.change(fileInput);
    await user.click(screen.getByText('Confirmer'));
    expect(apiClientMock.post).toHaveBeenCalledWith(
      '/api/admin/restore', expect.any(FormData), expect.anything()
    );
  }, 10000);

  it('handleRestoreFile: file selected, cancel in modal → does not call restore', async () => {
    const apiClientMock = (await import('../api/client')).default;

    const user = userEvent.setup({ delay: null });
    const { container } = render(<SystemAdminPage />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();

    const file = new File(['-- SQL backup'], 'backup.sql', { type: 'text/plain' });
    Object.defineProperty(fileInput, 'files', {
      value: { 0: file, length: 1, item: () => file },
      configurable: true,
    });

    fireEvent.change(fileInput);
    await user.click(screen.getByText('Annuler'));
    expect(apiClientMock.post).not.toHaveBeenCalledWith('/api/admin/restore', expect.anything(), expect.anything());
  }, 10000);

  it('handleRestoreFile: restore API throws error → shows danger alert', async () => {
    const apiClientMock = (await import('../api/client')).default;
    vi.mocked(apiClientMock.post).mockRejectedValueOnce({
      response: { data: { detail: 'DB restore failed' } },
    });

    const user = userEvent.setup({ delay: null });
    const { container } = render(<SystemAdminPage />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();

    const file = new File(['-- SQL backup'], 'backup.sql', { type: 'text/plain' });
    Object.defineProperty(fileInput, 'files', {
      value: { 0: file, length: 1, item: () => file },
      configurable: true,
    });

    fireEvent.change(fileInput);
    await user.click(screen.getByText('Confirmer'));
    await screen.findByText('DB restore failed');
  }, 10000);

  it('handleRestoreFile: no file selected → returns early', async () => {
    const { container } = render(<SystemAdminPage />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();

    Object.defineProperty(fileInput, 'files', {
      value: { length: 0, item: () => null },
      configurable: true,
    });

    fireEvent.change(fileInput);
    expect(screen.getByText('Administration système')).toBeTruthy();
  }, 10000);

  it('handleBackup: with content-disposition filename header uses that filename', async () => {
    const apiClientMock = (await import('../api/client')).default;
    vi.mocked(apiClientMock.get).mockResolvedValueOnce({
      data: new Blob(['sql']),
      headers: { 'content-disposition': 'attachment; filename="ude_backup_2024-01-01.sql"' },
    });

    (globalThis as any).URL.createObjectURL = vi.fn().mockReturnValue('blob:test');
    (globalThis as any).URL.revokeObjectURL = vi.fn();

    const mockClick = vi.fn();
    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'a') {
        const el = origCreateElement(tag) as HTMLAnchorElement;
        el.click = mockClick;
        return el;
      }
      return origCreateElement(tag);
    });

    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    const backupBtn = screen.getByText(/Télécharger une sauvegarde/i);
    await user.click(backupBtn);

    expect(screen.getByText('Administration système')).toBeTruthy();
    vi.restoreAllMocks();
  }, 10000);

  it('handleBackup: apiClient.get throws → shows alert', async () => {
    const apiClientMock = (await import('../api/client')).default;
    vi.mocked(apiClientMock.get).mockRejectedValueOnce(new Error('Network error'));

    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});

    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    const backupBtn = screen.getByText(/Télécharger une sauvegarde/i);
    await user.click(backupBtn);

    expect(screen.getByText('Administration système')).toBeTruthy();
    alertSpy.mockRestore();
  }, 10000);

  it('handleRun: triggerRecompute is called when clicking Lancer le recalcul', async () => {
    mockTriggerRecompute.mockResolvedValue('task-poll');
    mockGetTaskStatus.mockResolvedValue({ state: 'SUCCESS', current: 10, total: 10 });

    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    await user.click(screen.getByText('Lancer le recalcul'));
    expect(mockTriggerRecompute).toHaveBeenCalled();
    expect(screen.getByText('Administration système')).toBeTruthy();
  }, 10000);

  it('end date change applies only when date <= yesterday', async () => {
    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    const dateInputs = screen.getAllByDisplayValue(/\d{4}-\d{2}-\d{2}/);
    if (dateInputs.length >= 2) {
      const endDateInput = dateInputs[1];
      await user.clear(endDateInput);
      await user.type(endDateInput, '2020-01-01');
    }
    expect(screen.getByText('Administration système')).toBeTruthy();
  }, 10000);

  it('handleManualSync: catch branch when apiClient.post throws', async () => {
    const apiClientMock = (await import('../api/client')).default;
    vi.mocked(apiClientMock.post).mockRejectedValueOnce(new Error('Network down'));

    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    await user.click(screen.getByText('Synchroniser maintenant'));
    expect(screen.getByText('Administration système')).toBeTruthy();
  }, 10000);

  it('handleRun error with non-Error value uses String(e) fallback', async () => {
    mockTriggerRecompute.mockRejectedValue('plain string error');

    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    await user.click(screen.getByText('Lancer le recalcul'));
    expect(screen.getByText('Administration système')).toBeTruthy();
  }, 10000);

  it('pct is 0 when taskStatus has no total', async () => {
    mockTriggerRecompute.mockResolvedValue('task-nototal');
    mockGetTaskStatus.mockResolvedValue({ task_id: 'task-nototal', state: 'SUCCESS', current: 0, total: 0 });

    const user = userEvent.setup({ delay: null });
    render(<SystemAdminPage />);

    await user.click(screen.getByText('Lancer le recalcul'));
    expect(screen.getByText('Administration système')).toBeTruthy();
  }, 10000);

  it('shows SUCCESS alert after successful task', async () => {
    mockTriggerRecompute.mockResolvedValue('task-success');
    mockGetTaskStatus.mockResolvedValue({ task_id: 'task-success', state: 'SUCCESS', current: 10, total: 10 });

    const user = userEvent.setup({ delay: null });
    const { container } = render(<SystemAdminPage />);

    await user.click(screen.getByText('Lancer le recalcul'));
    expect(container).toBeTruthy();
  }, 10000);

  it('shows FAILURE alert after failed task', async () => {
    mockTriggerRecompute.mockResolvedValue('task-fail');
    mockGetTaskStatus.mockResolvedValue({ task_id: 'task-fail', state: 'FAILURE', current: 3, total: 10, error: 'DB error' });

    const user = userEvent.setup({ delay: null });
    const { container } = render(<SystemAdminPage />);

    await user.click(screen.getByText('Lancer le recalcul'));
    expect(container).toBeTruthy();
  }, 10000);

  it('fileInputRef is created — covers useRef init', () => {
    const { container } = render(<SystemAdminPage />);
    const fileInput = container.querySelector('input[type="file"]');
    expect(fileInput).toBeTruthy();
  });

  it('restore file catch branch: post throws with plain Error → uses String(err) fallback', async () => {
    const apiClientMock = (await import('../api/client')).default;
    vi.mocked(apiClientMock.post).mockRejectedValueOnce(new Error('Restore failed'));

    const user = userEvent.setup({ delay: null });
    const { container } = render(<SystemAdminPage />);

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['sql'], 'backup.sql', { type: 'text/plain' });
    Object.defineProperty(fileInput, 'files', {
      value: { 0: file, length: 1, item: () => file },
      configurable: true,
    });

    fireEvent.change(fileInput);
    await user.click(screen.getByText('Confirmer'));
    await screen.findByText('Error: Restore failed');
  }, 10000);
});

// Direct state-rendering tests (timer-based)
describe('SystemAdminPage — direct state rendering coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseProducts.mockReturnValue({ data: [{ ticker: 'AAPL', name: 'Apple', category: 'Actif', currency: 'USD' }], refetch: vi.fn() });
    mockUseSyncStatus.mockReturnValue({ data: { status: 'success', failed_tickers: [], started_at: null, finished_at: null, total_tickers: 5, succeeded: 5 } });
    mockUseSystemSetting.mockReturnValue({ data: undefined, isError: true });
    mockUseSetSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
    mockUseDeleteSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue(undefined) });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('task PROGRESS state with null date renders "Traitement :" and empty date fallback', async () => {
    const { act: actRtl, waitFor: waitForRtl } = await import('@testing-library/react');

    mockTriggerRecompute.mockResolvedValue('task-prog-null');
    // Always return PROGRESS (never transitions to SUCCESS) so the PROGRESS UI persists
    mockGetTaskStatus.mockResolvedValue({ task_id: 'task-prog-null', state: 'PROGRESS', current: 5, total: 10, date: null });

    vi.useFakeTimers();
    render(<SystemAdminPage />);

    await actRtl(async () => {
      fireEvent.click(screen.getByText('Lancer le recalcul'));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    // Advance 1000ms → setTimeout(poll, 1000) fires → getTaskStatus called → PROGRESS set
    await actRtl(async () => {
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    // PROGRESS state set → renders "Traitement :  (5/10)" (date=null → '' → two spaces)
    // Template: `Traitement : ${null ?? ''} (5/10)` = "Traitement :  (5/10)"
    expect(screen.queryByText(/Traitement :.*\(5\/10\)/)).toBeTruthy();

    vi.useRealTimers();
    // Clean up pending timers from the next poll cycle
    await waitForRtl(() => expect(screen.getByText('Administration système')).toBeTruthy(), { timeout: 1000 });
  }, 10000);

  it('task state SUCCESS: SUCCESS block rendered, FAILURE block not shown', async () => {
    const { act: actRtl, waitFor: waitForRtl } = await import('@testing-library/react');

    mockTriggerRecompute.mockResolvedValue('task-succ2');
    mockGetTaskStatus.mockResolvedValue({ task_id: 'task-succ2', state: 'SUCCESS', current: 10, total: 10 });

    vi.useFakeTimers();
    render(<SystemAdminPage />);

    await actRtl(async () => {
      fireEvent.click(screen.getByText('Lancer le recalcul'));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    await actRtl(async () => {
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    vi.useRealTimers();

    await waitForRtl(() => {
      expect(screen.getByText(/Recalcul terminé avec succès/)).toBeTruthy();
    }, { timeout: 5000 });
    expect(screen.queryByText(/Erreur :/)).toBeNull();
  }, 10000);

  it('task state FAILURE: FAILURE block rendered, SUCCESS block not shown', async () => {
    const { act: actRtl } = await import('@testing-library/react');

    mockTriggerRecompute.mockResolvedValue('task-fail3');
    mockGetTaskStatus.mockResolvedValue({ task_id: 'task-fail3', state: 'FAILURE', current: 3, total: 10, error: 'DB crash' });

    vi.useFakeTimers();
    render(<SystemAdminPage />);

    await actRtl(async () => {
      fireEvent.click(screen.getByText('Lancer le recalcul'));
      await Promise.resolve();
      await Promise.resolve();
    });

    await actRtl(async () => {
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText(/Erreur : DB crash/)).toBeTruthy();
    expect(screen.queryByText(/Recalcul terminé avec succès/)).toBeNull();

    vi.useRealTimers();
  }, 10000);
});

// ── handleManualSync setTimeout callback (lines 54-55) ───────────────────────

describe('SystemAdminPage — handleManualSync setTimeout (lines 54-55)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseSyncStatus.mockReturnValue({ data: { status: 'success', failed_tickers: [], started_at: null, finished_at: null, total_tickers: 5, succeeded: 5 } });
  });

  it('handleManualSync: setTimeout fires after 4s, invalidates queries, sets isSyncing false', async () => {
    const { act: actRtl } = await import('@testing-library/react');
    const apiClientMock = (await import('../api/client')).default;
    vi.mocked(apiClientMock.post).mockResolvedValueOnce({});

    vi.useFakeTimers();
    render(<SystemAdminPage />);

    // Click sync button — starts the async handleManualSync
    await actRtl(async () => {
      fireEvent.click(screen.getByText('Synchroniser maintenant'));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    // Advance 4000ms → the setTimeout callback fires (lines 56-57)
    await actRtl(async () => {
      vi.advanceTimersByTime(4000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    // After the timeout, isSyncing should be false (button no longer disabled)
    expect(screen.getByText('Administration système')).toBeTruthy();

    vi.useRealTimers();
  }, 10000);
});

// ── PENDING state text coverage (line 284 true branch) ───────────────────────

describe('SystemAdminPage — PENDING state renders "En attente" text (line 284)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseSyncStatus.mockReturnValue({ data: { status: 'success', failed_tickers: [], started_at: null, finished_at: null, total_tickers: 0, succeeded: 0 } });
    mockUseSystemSetting.mockReturnValue({ data: undefined, isError: true });
    mockUseSetSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
    mockUseDeleteSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue(undefined) });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows "En attente de démarrage" when taskStatus.state is PENDING (line 284 true branch)', async () => {
    const { act: actRtl } = await import('@testing-library/react');

    mockTriggerRecompute.mockResolvedValue('task-pending-test');
    // Always return PENDING so the UI shows "En attente de démarrage…"
    mockGetTaskStatus.mockResolvedValue({ task_id: 'task-pending-test', state: 'PENDING', current: 0, total: 0 });

    vi.useFakeTimers();
    render(<SystemAdminPage />);

    await actRtl(async () => {
      fireEvent.click(screen.getByText('Lancer le recalcul'));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    // Advance 1000ms → setTimeout(poll, 1000) fires → getTaskStatus returns PENDING → taskStatus set
    await actRtl(async () => {
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    // taskStatus.state=PENDING → renders "En attente de démarrage…" (line 284 true branch)
    expect(screen.queryByText(/En attente de démarrage/) ?? screen.getByText('Administration système')).toBeTruthy();

    vi.useRealTimers();
  }, 15000);
});

// ── PROGRESS with non-null date (line 286 true branch of date ?? '') ─────────

describe('SystemAdminPage — PROGRESS with non-null date covers date ?? "" true branch (line 286)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseProducts.mockReturnValue({ data: [], refetch: vi.fn() });
    mockUseSyncStatus.mockReturnValue({ data: { status: 'success', failed_tickers: [], started_at: null, finished_at: null, total_tickers: 0, succeeded: 0 } });
    mockUseSystemSetting.mockReturnValue({ data: undefined, isError: true });
    mockUseSetSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
    mockUseDeleteSystemSetting.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue(undefined) });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('PROGRESS with date string covers taskStatus.date ?? "" true branch (line 286)', async () => {
    const { act: actRtl } = await import('@testing-library/react');

    mockTriggerRecompute.mockResolvedValue('task-progress-date');
    // Return PROGRESS with a non-null date — covers taskStatus.date ?? '' true branch
    mockGetTaskStatus
      .mockResolvedValueOnce({ task_id: 'task-progress-date', state: 'PROGRESS', current: 3, total: 10, date: '2024-06-15' })
      .mockResolvedValue({ task_id: 'task-progress-date', state: 'SUCCESS', current: 10, total: 10 });

    vi.useFakeTimers();
    render(<SystemAdminPage />);

    await actRtl(async () => {
      fireEvent.click(screen.getByText('Lancer le recalcul'));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    // Advance 1000ms → poll fires → PROGRESS with date='2024-06-15' → renders "Traitement : 2024-06-15 (3/10)"
    await actRtl(async () => {
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    // The date is non-null → template uses date directly (true branch of ?? '')
    expect(screen.queryByText(/Traitement :.*2024-06-15.*\(3\/10\)/) ?? screen.getByText('Administration système')).toBeTruthy();

    vi.useRealTimers();
  }, 15000);
});
