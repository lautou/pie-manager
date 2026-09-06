// SPDX-License-Identifier: AGPL-3.0-or-later
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
	Button,
	Content,
	ContentVariants,
	Modal,
	ModalBody,
	ModalFooter,
	ModalHeader,
	ModalVariant
} from '@patternfly/react-core';

interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  message?: string | string[];
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'primary';
  isLoading?: boolean;
  isConfirmDisabled?: boolean;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
  /** Custom content rendered below the message (e.g. a form field) — the
   * modal is still a single confirm/cancel action, just with richer body
   * content than a plain text message. */
  children?: ReactNode;
}

export default function ConfirmModal({
  isOpen,
  title,
  message,
  confirmLabel,
  cancelLabel,
  variant = 'danger',
  isLoading = false,
  isConfirmDisabled = false,
  onConfirm,
  onCancel,
  children,
}: ConfirmModalProps) {
  const { t } = useTranslation();
  const paragraphs = message ? (Array.isArray(message) ? message : [message]) : [];
  // The warning icon/red title only fits a destructive ("danger") action —
  // a plain create/rename-style confirmation shouldn't look like a warning.
  const headerTitle = variant === 'danger'
    ? <span style={{ color: 'var(--pf-t--global--text--color--status--danger--default)' }}>⚠ {title}</span>
    : title;

  return (
    <Modal
      variant={ModalVariant.small}
      isOpen={isOpen}
      onClose={onCancel}
    >
      <ModalHeader title={headerTitle} />
      <ModalBody>
        {paragraphs.length > 0 && (
          <Content>
            {paragraphs.map((p, i) => (
              <Content key={i} component={ContentVariants.p}>{p}</Content>
            ))}
          </Content>
        )}
        {children}
      </ModalBody>
      <ModalFooter>
        <Button key="confirm" variant={variant} onClick={onConfirm} isLoading={isLoading} isDisabled={isLoading || isConfirmDisabled}>
          {confirmLabel ?? t('common.delete')}
        </Button>
        <Button key="cancel" variant="link" onClick={onCancel} isDisabled={isLoading}>
          {cancelLabel ?? t('common.cancel')}
        </Button>
      </ModalFooter>
    </Modal>
  );
}
