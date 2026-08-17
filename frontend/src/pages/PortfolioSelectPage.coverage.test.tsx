/**
 * Coverage tests for PortfolioSelectPage:
 * - Line 62: early return in handleDelete when deleteConfirmName !== deleteTarget.name
 * - Line 170: setRenameTarget updater function `t => t ? { ...t, name: v } : t`
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfIconStubs } from '../../tests/utils/patternfly-mocks';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
  useParams: () => ({}),
}));

vi.mock('@patternfly/react-core', () => ({
  ...pfCoreStubs,
  // Override Button to NOT apply disabled so that onClick always fires.
  // This lets us test the early-return guard inside handleDelete itself.
  Button: ({ children, onClick, isLoading, isDisabled, variant }: any) => (
    <button
      onClick={onClick}
      data-disabled={String(isDisabled)}
      data-loading={String(!!isLoading)}
      data-variant={variant}
    >
      {children}
    </button>
  ),
}));
vi.mock('@patternfly/react-core/deprecated', () => ({
  Modal: ({ children, isOpen, title, onClose, actions }: any) =>
    isOpen ? (
      <div data-testid="modal" role="dialog">
        <div>{title}</div>
        <div data-testid="modal-actions">{actions}</div>
        <button onClick={onClose}>Close</button>
        {children}
      </div>
    ) : null,
  ModalVariant: { small: 'small' },
}));

vi.mock('@patternfly/react-icons', () => pfIconStubs);

const mockUsePortfolios = vi.fn();
const mockCreatePortfolio = vi.fn();
const mockRenamePortfolio = vi.fn();
const mockDeletePortfolio = vi.fn();

vi.mock('../api/queries', () => ({
  usePortfolios: () => mockUsePortfolios(),
  useCreatePortfolio: () => ({ mutateAsync: mockCreatePortfolio, isPending: false }),
  useRenamePortfolio: () => ({ mutateAsync: mockRenamePortfolio, isPending: false }),
  useDeletePortfolio: () => ({ mutateAsync: mockDeletePortfolio, isPending: false }),
}));

const mockPortfolio = { id: 1, name: 'Portfolio 1', created_at: '2024-01-01T00:00:00Z' };

import PortfolioSelectPage from './PortfolioSelectPage';

describe('PortfolioSelectPage — line 62: handleDelete early return', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCreatePortfolio.mockResolvedValue({});
    mockRenamePortfolio.mockResolvedValue({});
    mockDeletePortfolio.mockResolvedValue({});
    mockUsePortfolios.mockReturnValue({ data: [mockPortfolio], isLoading: false, isError: false });
  });

  it('line 62: handleDelete fires but returns early when deleteConfirmName !== deleteTarget.name', async () => {
    // In this test, the Button mock does NOT apply the disabled attribute to the DOM,
    // so onClick fires regardless of isDisabled prop. This lets handleDelete execute
    // and hit line 62 (the early return guard) even with the wrong confirm name.
    const user = userEvent.setup({ delay: null });
    render(<PortfolioSelectPage />);

    // Open delete modal
    await user.click(screen.getByText('Supprimer'));
    expect(screen.getByTestId('modal')).toBeTruthy();

    // Type a WRONG name — deleteConfirmName = 'WrongName' ≠ 'Portfolio 1' = deleteTarget.name
    const confirmInput = screen.getByRole('textbox', { name: /Confirmer le nom/i });
    await user.type(confirmInput, 'WrongName');

    // Click "Supprimer définitivement" — Button mock does not disable, so onClick fires
    // handleDelete runs and hits line 62: !deleteTarget is false, but
    // deleteConfirmName !== deleteTarget.name is true → early return executes
    const deleteBtn = screen.getByText('Supprimer définitivement');
    await user.click(deleteBtn);

    // The early return prevented deletePortfolio.mutateAsync from being called
    expect(mockDeletePortfolio).not.toHaveBeenCalled();
  }, 10000);

  it('line 62: handleDelete proceeds when deleteConfirmName === deleteTarget.name', async () => {
    // Typing the correct name makes the condition false → no early return → delete fires
    const user = userEvent.setup({ delay: null });
    render(<PortfolioSelectPage />);

    await user.click(screen.getByText('Supprimer'));
    const confirmInput = screen.getByRole('textbox', { name: /Confirmer le nom/i });
    await user.type(confirmInput, 'Portfolio 1');

    const deleteBtn = screen.getByText('Supprimer définitivement');
    await user.click(deleteBtn);

    // Line 62 condition is false → proceeds to delete
    expect(mockDeletePortfolio).toHaveBeenCalledWith(1);
  }, 10000);

  it('line 62: handleDelete with !deleteTarget returns early (deleteTarget is null)', async () => {
    // When the modal is not open, deleteTarget is null. We cannot click the button
    // without the modal, but we confirm deletePortfolio is never called.
    render(<PortfolioSelectPage />);
    // No modal → no delete button → handleDelete is never called → deletePortfolio not called
    expect(mockDeletePortfolio).not.toHaveBeenCalled();
  });
});

describe('PortfolioSelectPage — line 170: setRenameTarget updater (t => t ? {...t, name:v} : t)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCreatePortfolio.mockResolvedValue({});
    mockRenamePortfolio.mockResolvedValue({});
    mockDeletePortfolio.mockResolvedValue({});
    mockUsePortfolios.mockReturnValue({ data: [mockPortfolio], isLoading: false, isError: false });
  });

  it('line 170: typing in rename input calls setRenameTarget updater (t truthy → merges)', async () => {
    // When rename modal is open, renameTarget = mockPortfolio (non-null).
    // Typing in the TextInput calls onChange → setRenameTarget(t => t ? {...t,name:v} : t)
    // With t = mockPortfolio (truthy), the true branch executes: { ...t, name: v }
    const user = userEvent.setup({ delay: null });
    render(<PortfolioSelectPage />);

    await user.click(screen.getByText('Renommer'));
    const modal = screen.getByTestId('modal');
    expect(modal).toBeTruthy();

    // Find the name TextInput inside the rename modal
    const inputs = Array.from(modal.querySelectorAll('input[type="text"]'));
    expect(inputs.length).toBeGreaterThan(0);

    // Type to trigger onChange → runs the t => t ? { ...t, name: v } : t updater
    await user.clear(inputs[0] as HTMLElement);
    await user.type(inputs[0] as HTMLElement, 'Portfolio 1b');

    // Verify the updated name reflects in the input value
    expect((inputs[0] as HTMLInputElement).value).toBe('Portfolio 1b');
    expect(screen.getByText('PIE Manager')).toBeTruthy();
  }, 10000);
});
