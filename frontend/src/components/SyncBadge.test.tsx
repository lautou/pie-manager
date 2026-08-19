/**
 * Tests for SyncBadge component.
 *
 * SyncBadge renders null when useSyncStatus returns no data, and otherwise
 * shows a status icon + label derived from the SyncStatus object.
 *
 * Strategy:
 * - Mock useSyncStatus so no HTTP call is made.
 * - Mock PatternFly Tooltip to render its children directly (avoids jsdom issues).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import '../../src/i18n';
import type { SyncStatus } from '../hooks/useSyncStatus';
import SyncBadge from './SyncBadge';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('@patternfly/react-core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@patternfly/react-core')>();
  return {
    ...actual,
    // Render children directly, plus the tooltip content in a queryable node — real PatternFly
    // only shows content on hover, but tests need to inspect it without simulating that.
    Tooltip: ({ children, content }: { children: React.ReactNode; content?: React.ReactNode }) => (
      <>
        {children}
        <div data-testid="tooltip-content">{content}</div>
      </>
    ),
  };
});

const mockUseSyncStatus = vi.fn();

vi.mock('../hooks/useSyncStatus', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../hooks/useSyncStatus')>();
  return {
    ...actual,
    useSyncStatus: () => mockUseSyncStatus(),
  };
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeSync(overrides: Partial<SyncStatus> = {}): SyncStatus {
  return {
    status: 'success',
    started_at: null,
    finished_at: null,
    total_tickers: 10,
    succeeded: 10,
    failed_tickers: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SyncBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when data is undefined (loading / error)', () => {
    mockUseSyncStatus.mockReturnValue({ data: undefined });
    const { container } = render(<SyncBadge />);
    expect(container.firstChild).toBeNull();
  });

  it('shows the running icon and message when status is "running"', () => {
    mockUseSyncStatus.mockReturnValue({ data: makeSync({ status: 'running' }) });
    render(<SyncBadge />);
    const badge = within(screen.getByTestId('sync-badge'));
    expect(badge.getByText(/Synchronisation en cours/i)).toBeDefined();
    expect(badge.getByText(/🔄/)).toBeDefined();
  });

  it('shows "Jamais synchronisé" when status is "never"', () => {
    mockUseSyncStatus.mockReturnValue({ data: makeSync({ status: 'never' }) });
    render(<SyncBadge />);
    const badge = within(screen.getByTestId('sync-badge'));
    expect(badge.getByText(/Jamais synchronisé/i)).toBeDefined();
    expect(badge.getByText(/⚪/)).toBeDefined();
  });

  it('shows green icon and synchro label when status is "success"', () => {
    mockUseSyncStatus.mockReturnValue({
      data: makeSync({ status: 'success', finished_at: new Date().toISOString() }),
    });
    render(<SyncBadge />);
    const badge = within(screen.getByTestId('sync-badge'));
    expect(badge.getByText(/Synchro/i)).toBeDefined();
    expect(badge.getByText(/🟢/)).toBeDefined();
  });

  it('shows yellow/orange icon when status is "partial"', () => {
    mockUseSyncStatus.mockReturnValue({
      data: makeSync({
        status: 'partial',
        finished_at: new Date().toISOString(),
        failed_tickers: ['AAPL'],
      }),
    });
    render(<SyncBadge />);
    expect(screen.getByText(/🟡/)).toBeDefined();
  });

  it('shows red icon when status is "failed"', () => {
    mockUseSyncStatus.mockReturnValue({
      data: makeSync({ status: 'failed', finished_at: new Date().toISOString() }),
    });
    render(<SyncBadge />);
    expect(screen.getByText(/🔴/)).toBeDefined();
  });

  it('span has a non-default color when status is "success"', () => {
    mockUseSyncStatus.mockReturnValue({
      data: makeSync({ status: 'success', finished_at: new Date().toISOString() }),
    });
    render(<SyncBadge />);
    // The span containing the badge should have an inline color style
    const span = screen.getByText(/🟢/).closest('span');
    expect(span).not.toBeNull();
    expect(span!.style.color).toBeTruthy();
  });

  it('span has cursor: default', () => {
    mockUseSyncStatus.mockReturnValue({
      data: makeSync({ status: 'success', finished_at: new Date().toISOString() }),
    });
    render(<SyncBadge />);
    const span = screen.getByText(/🟢/).closest('span');
    expect(span!.style.cursor).toBe('default');
  });

  it('includes the background-sync note in the tooltip when status is "success" (issue #83)', () => {
    mockUseSyncStatus.mockReturnValue({
      data: makeSync({ status: 'success', finished_at: new Date().toISOString() }),
    });
    render(<SyncBadge />);
    expect(screen.getByTestId('tooltip-content').textContent).toContain(
      "la synchronisation ne s'exécute que lorsque l'application est ouverte",
    );
  });

  it('does NOT include the background-sync note when status is "failed"', () => {
    mockUseSyncStatus.mockReturnValue({
      data: makeSync({ status: 'failed', finished_at: new Date().toISOString() }),
    });
    render(<SyncBadge />);
    expect(screen.getByTestId('tooltip-content').textContent).not.toContain(
      "la synchronisation ne s'exécute que lorsque l'application est ouverte",
    );
  });

  it('does NOT include the background-sync note when status is "partial"', () => {
    mockUseSyncStatus.mockReturnValue({
      data: makeSync({
        status: 'partial',
        finished_at: new Date().toISOString(),
        failed_tickers: ['AAPL'],
      }),
    });
    render(<SyncBadge />);
    expect(screen.getByTestId('tooltip-content').textContent).not.toContain(
      "la synchronisation ne s'exécute que lorsque l'application est ouverte",
    );
  });

  it('uses fallback color #6A6E73 and fallback icon ⚪ for unknown status (lines 25-26)', () => {
    // An unknown status value triggers STATUS_COLOR[sync.status] ?? '#6A6E73'
    // and STATUS_ICON[sync.status] ?? '⚪'
    const unknownSync = makeSync({ status: 'unknown' as any });
    mockUseSyncStatus.mockReturnValue({ data: unknownSync });
    render(<SyncBadge />);
    // Should render with the fallback icon ⚪
    expect(screen.getByText(/⚪/)).toBeTruthy();
    // The span should have the fallback color
    const span = screen.getByText(/⚪/).closest('span');
    expect(span!.style.color).toBe('rgb(106, 110, 115)'); // #6A6E73 parsed by jsdom
  });
});
