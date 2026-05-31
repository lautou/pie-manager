/**
 * Tests for RefreshBanner component.
 *
 * RefreshBanner is visible while any React Query fetch is in flight
 * (useIsFetching() > 0) and hidden otherwise.
 *
 * Strategy:
 * - Mock @tanstack/react-query's useIsFetching to control the fetching state.
 * - Mock @patternfly/react-core Spinner to avoid DOM/CSS issues in jsdom.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import '../../src/i18n';
import RefreshBanner from './RefreshBanner';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock PatternFly Spinner — avoids ResizeObserver / CSS variable issues in jsdom
vi.mock('@patternfly/react-core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@patternfly/react-core')>();
  return {
    ...actual,
    Spinner: () => null,
  };
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mockUseIsFetching = vi.fn() as ReturnType<typeof vi.fn> & (() => number);

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-query')>();
  return {
    ...actual,
    useIsFetching: () => mockUseIsFetching(),
  };
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('RefreshBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when no fetch is in flight (isFetching === 0)', () => {
    mockUseIsFetching.mockReturnValue(0);
    const { container } = render(<RefreshBanner />);
    expect(container.firstChild).toBeNull();
  });

  it('renders the banner when at least one fetch is in flight (isFetching === 1)', () => {
    mockUseIsFetching.mockReturnValue(1);
    render(<RefreshBanner />);
    expect(screen.getByText(/Actualisation des données en cours/i)).toBeDefined();
  });

  it('renders the banner when multiple fetches are in flight (isFetching === 3)', () => {
    mockUseIsFetching.mockReturnValue(3);
    render(<RefreshBanner />);
    expect(screen.getByText(/Actualisation des données en cours/i)).toBeDefined();
  });

  it('is fixed at top of viewport (position: fixed, top: 0)', () => {
    mockUseIsFetching.mockReturnValue(1);
    const { container } = render(<RefreshBanner />);
    const div = container.firstElementChild as HTMLElement;
    expect(div).not.toBeNull();
    expect(div.style.position).toBe('fixed');
    // jsdom normalises numeric 0 to '0px'
    expect(div.style.top).toMatch(/^0/);
  });

  it('has a high z-index so it overlays other content', () => {
    mockUseIsFetching.mockReturnValue(1);
    const { container } = render(<RefreshBanner />);
    const div = container.firstElementChild as HTMLElement;
    expect(Number(div.style.zIndex)).toBeGreaterThanOrEqual(9000);
  });
});
