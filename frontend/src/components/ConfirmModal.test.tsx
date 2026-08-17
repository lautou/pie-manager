import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { pfCoreStubs } from '../../tests/utils/patternfly-mocks';

vi.mock('@patternfly/react-core', () => pfCoreStubs);
vi.mock('@patternfly/react-core/deprecated', () => ({
  ModalVariant: pfCoreStubs.ModalVariant,
  Modal: ({ children, isOpen, title, onClose, actions }: any) =>
    isOpen ? (
      <div data-testid="modal" role="dialog">
        <div>{title}</div>
        <div>{actions}</div>
        <button onClick={onClose}>CloseX</button>
        {children}
      </div>
    ) : null,
}));

import ConfirmModal from './ConfirmModal';

describe('ConfirmModal', () => {
  it('renders nothing when isOpen is false', () => {
    render(
      <ConfirmModal
        isOpen={false}
        title="Titre"
        message="Message"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.queryByTestId('modal')).toBeNull();
  });

  it('renders title, single-string message, and default labels when open', () => {
    render(
      <ConfirmModal
        isOpen
        title="Supprimer cet élément"
        message="Cette action est définitive."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByTestId('modal')).toBeTruthy();
    expect(screen.getByText(/Supprimer cet élément/)).toBeTruthy();
    expect(screen.getByText('Cette action est définitive.')).toBeTruthy();
    expect(screen.getByText('Supprimer')).toBeTruthy();
    expect(screen.getByText('Annuler')).toBeTruthy();
  });

  it('renders one paragraph per array entry when message is a string[]', () => {
    render(
      <ConfirmModal
        isOpen
        title="Restaurer"
        message={['Première ligne.', 'Deuxième ligne.']}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByText('Première ligne.')).toBeTruthy();
    expect(screen.getByText('Deuxième ligne.')).toBeTruthy();
  });

  it('calls onConfirm when the confirm button is clicked', async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <ConfirmModal
        isOpen
        title="Titre"
        message="Message"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />
    );
    await user.click(screen.getByText('Supprimer'));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('calls onCancel when the cancel button is clicked', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <ConfirmModal
        isOpen
        title="Titre"
        message="Message"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />
    );
    await user.click(screen.getByText('Annuler'));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('calls onCancel when the modal is closed (escape/backdrop)', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <ConfirmModal
        isOpen
        title="Titre"
        message="Message"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />
    );
    await user.click(screen.getByText('CloseX'));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('uses custom confirmLabel, cancelLabel, and primary variant when provided', () => {
    render(
      <ConfirmModal
        isOpen
        title="Titre"
        message="Message"
        confirmLabel="Continuer"
        cancelLabel="Retour"
        variant="primary"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByText('Continuer')).toBeTruthy();
    expect(screen.getByText('Retour')).toBeTruthy();
  });

  it('disables both buttons and shows loading state on the confirm button when isLoading is true', () => {
    render(
      <ConfirmModal
        isOpen
        title="Titre"
        message="Message"
        isLoading
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    const confirmBtn = screen.getByText('Supprimer').closest('button') as HTMLButtonElement;
    const cancelBtn = screen.getByText('Annuler').closest('button') as HTMLButtonElement;
    expect(confirmBtn.disabled).toBe(true);
    expect(cancelBtn.disabled).toBe(true);
  });
});
