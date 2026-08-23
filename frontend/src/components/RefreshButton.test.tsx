// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for RefreshButton component.
 *
 * RefreshButton:
 * - Is disabled + shows loading while a fetch is in flight.
 * - On click: calls apiClient.post then invalidates all REFRESH_KEYS.
 *
 * Strategy:
 * - Mock @tanstack/react-query (useIsFetching, useQueryClient).
 * - Mock apiClient.
 * - Mock PatternFly Button + SyncAltIcon to keep the render surface minimal.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import RefreshButton from './RefreshButton';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('@patternfly/react-core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@patternfly/react-core')>();
  return {
    ...actual,
    // Render a simple <button> so we can detect disabled state and click events
    Button: ({ children, onClick, isDisabled }: {
      children: React.ReactNode;
      onClick?: () => void;
      isDisabled?: boolean;
      isLoading?: boolean;
      variant?: string;
      icon?: React.ReactNode;
      size?: string;
    }) => (
      <button onClick={onClick} disabled={isDisabled}>
        {children}
      </button>
    ),
  };
});

vi.mock('@patternfly/react-icons', () => ({
  SyncAltIcon: () => null,
}));

const mockInvalidateQueries = vi.fn();
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mockUseIsFetching = vi.fn() as ReturnType<typeof vi.fn> & (() => number);

vi.mock('@tanstack/react-query', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-query')>();
  return {
    ...actual,
    useIsFetching: () => mockUseIsFetching(),
    useQueryClient: () => ({ invalidateQueries: mockInvalidateQueries }),
  };
});

const mockApiPost = vi.fn();
vi.mock('../api/client', () => ({
  default: {
    post: () => mockApiPost(),
    get: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('RefreshButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApiPost.mockResolvedValue({});
  });

  it('renders the "Actualiser" label', () => {
    mockUseIsFetching.mockReturnValue(0);
    render(<RefreshButton />);
    expect(screen.getByText('Actualiser')).toBeDefined();
  });

  it('is enabled when no fetch is in flight', () => {
    mockUseIsFetching.mockReturnValue(0);
    render(<RefreshButton />);
    const btn = screen.getByRole('button');
    expect(btn.hasAttribute('disabled')).toBe(false);
  });

  it('is disabled while a fetch is in flight', () => {
    mockUseIsFetching.mockReturnValue(1);
    render(<RefreshButton />);
    const btn = screen.getByRole('button');
    expect(btn.hasAttribute('disabled')).toBe(true);
  });

  it('calls apiClient.post and then invalidateQueries on click', async () => {
    mockUseIsFetching.mockReturnValue(0);
    render(<RefreshButton />);

    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledTimes(1);
      expect(mockInvalidateQueries).toHaveBeenCalled();
    });
  });

  it('invalidates all REFRESH_KEYS on click', async () => {
    const { REFRESH_KEYS } = await import('../hooks/useAutoRefresh');
    mockUseIsFetching.mockReturnValue(0);
    render(<RefreshButton />);

    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => {
      expect(mockInvalidateQueries).toHaveBeenCalledTimes(REFRESH_KEYS.length);
      for (const key of REFRESH_KEYS) {
        expect(mockInvalidateQueries).toHaveBeenCalledWith({ queryKey: [key] });
      }
    });
  });

  it('still invalidates queries even when apiClient.post rejects', async () => {
    mockApiPost.mockRejectedValue(new Error('network error'));
    mockUseIsFetching.mockReturnValue(0);
    render(<RefreshButton />);

    fireEvent.click(screen.getByRole('button'));

    await waitFor(() => {
      expect(mockInvalidateQueries).toHaveBeenCalled();
    });
  });
});
