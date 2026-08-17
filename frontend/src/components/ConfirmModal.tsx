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
  message: string | string[];
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'primary';
  isLoading?: boolean;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}

export default function ConfirmModal({
  isOpen,
  title,
  message,
  confirmLabel,
  cancelLabel,
  variant = 'danger',
  isLoading = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const { t } = useTranslation();
  const paragraphs = Array.isArray(message) ? message : [message];

  return (
    <Modal
      variant={ModalVariant.small}
      isOpen={isOpen}
      onClose={onCancel}
    >
      <ModalHeader title={<span style={{ color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--danger-color--100 */ }}>⚠ {title}</span>} />
      <ModalBody>
        <Content>
          {paragraphs.map((p, i) => (
            <Content key={i} component={ContentVariants.p}>{p}</Content>
          ))}
        </Content>
      </ModalBody>
      <ModalFooter>
        <Button key="confirm" variant={variant} onClick={onConfirm} isLoading={isLoading} isDisabled={isLoading}>
          {confirmLabel ?? t('common.delete')}
        </Button>
        <Button key="cancel" variant="link" onClick={onCancel} isDisabled={isLoading}>
          {cancelLabel ?? t('common.cancel')}
        </Button>
      </ModalFooter>
    </Modal>
  );
}
