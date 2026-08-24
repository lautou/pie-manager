// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert, Button,
  Modal, ModalBody, ModalFooter, ModalHeader, ModalVariant,
} from '@patternfly/react-core';
import { PencilAltIcon, PlusCircleIcon, TrashIcon } from '@patternfly/react-icons';
import ConfirmModal from './ConfirmModal';

const inputSt: React.CSSProperties = { padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc', fontSize: '0.9rem', width: '100%' };
const tdSt: React.CSSProperties = { padding: '6px 8px', fontSize: '0.9rem', borderBottom: '1px solid #eee' };
const thSt: React.CSSProperties = { padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #ddd', fontSize: '0.85rem', color: '#6A6E73' };
const btnSm = (extra?: React.CSSProperties): React.CSSProperties => ({ padding: '3px 8px', borderRadius: 4, cursor: 'pointer', fontSize: '0.8rem', border: 'none', ...extra });

export interface CrudFieldDef<T> {
  key: keyof T & string;
  label: string;
  placeholder: string;
  monospace?: boolean;
  transform?: (raw: string) => string;
  validationMessage: string;
}

interface CrudManagerProps<T extends { code: string; label: string }> {
  items: T[];
  emptyForm: T;
  codeLabel: string;
  codePlaceholder: string;
  codeValidationMessage: string;
  /** All non-code fields, in table-column order. */
  fields: CrudFieldDef<T>[];
  /** Field-key order for the add/edit modal, if different from `fields`' table order. */
  modalOrder?: string[];
  /** Field-key order `handleSave` validates in, if different from `fields`' table order. */
  validationOrder?: string[];
  /** Disambiguates aria-labels from other CRUD managers sharing this page whose codes can
   * overlap (e.g. "fr" exists in both macro_regions and country_perf_configs) — '' for the
   * one manager that owns the bare "{action} {code}" label. */
  ariaNoun: string;
  countLabel: string;
  newLabel: string;
  editLabel: string;
  emptyLabel: string;
  deleteConfirmMessage: (item: T) => string;
  onCreate: (body: T) => Promise<T>;
  onUpdate: (code: string, body: Omit<T, 'code'>) => Promise<T>;
  onDelete: (code: string) => Promise<void>;
  onMutated: () => void;
}

/**
 * Generic code-keyed CRUD table + add/edit modal + delete confirmation, shared by every
 * "{code, label, ...tickers}" universe manager on the Configuration générale page
 * (regions, country/sector-performance universes, equity-premium countries) — these were
 * hand-copied from each other across several features before being collapsed into this one
 * parameterized implementation. `modalOrder`/`validationOrder` exist because the 4 original
 * components didn't all display and validate fields in the same order as their table columns
 * (a pre-existing inconsistency, preserved here rather than silently "fixed" by this refactor).
 */
export default function CrudManager<T extends { code: string; label: string }>({
  items, emptyForm, codeLabel, codePlaceholder, codeValidationMessage, fields,
  modalOrder, validationOrder, ariaNoun, countLabel, newLabel, editLabel, emptyLabel,
  deleteConfirmMessage, onCreate, onUpdate, onDelete, onMutated,
}: CrudManagerProps<T>) {
  const { t } = useTranslation();
  const [modalMode, setModalMode] = useState<'add' | 'edit' | null>(null);
  const [editingItem, setEditingItem] = useState<T | null>(null);
  const [form, setForm] = useState<T>(emptyForm);
  const [formError, setFormError] = useState('');
  const [deleteError, setDeleteError] = useState<{ code: string; message: string } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<T | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const fieldByKey = new Map(fields.map((f) => [f.key, f] as const));
  const resolveOrder = (order: string[] | undefined) =>
    (order ?? fields.map((f) => f.key)).map((k) => fieldByKey.get(k as keyof T & string)!);
  const modalFields = resolveOrder(modalOrder);
  const validationFields = resolveOrder(validationOrder);

  const setFieldValue = (key: keyof T & string, value: string) =>
    setForm((f) => ({ ...f, [key]: value }) as T);

  const openAdd = () => { setForm(emptyForm); setFormError(''); setEditingItem(null); setModalMode('add'); };
  const openEdit = (item: T) => { setForm(item); setFormError(''); setEditingItem(item); setModalMode('edit'); };
  const closeModal = () => { setModalMode(null); setEditingItem(null); setFormError(''); };

  const handleSave = async () => {
    if (!form.code.trim()) { setFormError(codeValidationMessage); return; }
    for (const field of validationFields) {
      if (!(form[field.key] as unknown as string).trim()) { setFormError(field.validationMessage); return; }
    }
    const buildValue = (field: CrudFieldDef<T>) => {
      const trimmed = (form[field.key] as unknown as string).trim();
      return field.transform ? field.transform(trimmed) : trimmed;
    };
    try {
      if (modalMode === 'add') {
        const body = { code: form.code.trim().toLowerCase() } as T;
        for (const field of fields) (body as any)[field.key] = buildValue(field);
        await onCreate(body);
      } else {
        /* v8 ignore next -- @preserve */
        if (editingItem) {
          const body = {} as Omit<T, 'code'>;
          for (const field of fields) (body as any)[field.key] = buildValue(field);
          await onUpdate(editingItem.code, body);
        }
      }
      closeModal(); onMutated();
    } catch (e: any) {
      setFormError(e?.response?.data?.detail ?? 'Erreur lors de l\'enregistrement');
    }
  };

  const handleDelete = (item: T) => { setDeleteError(null); setDeleteTarget(item); };

  const handleConfirmDelete = async () => {
    /* v8 ignore next -- @preserve */
    if (!deleteTarget) return;
    setIsDeleting(true);
    try {
      await onDelete(deleteTarget.code);
      onMutated();
      setDeleteTarget(null);
    } catch (e: any) {
      setDeleteError({ code: deleteTarget.code, message: e?.response?.data?.detail ?? 'Erreur lors de la suppression' });
    } finally { setIsDeleting(false); }
  };

  const editAriaLabel = (action: string, code: string) => ariaNoun ? `${action} ${ariaNoun} ${code}` : `${action} ${code}`;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
        <span style={{ fontSize: '0.85rem', color: '#6A6E73' }}>{countLabel}</span>
        <Button variant="primary" icon={<PlusCircleIcon />} size="sm" onClick={openAdd}>{newLabel}</Button>
      </div>
      {deleteError && <Alert variant="danger" isInline title={t('error.deleteFailed')} style={{ marginBottom: '0.75rem' }}>{deleteError.message}</Alert>}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
          <thead>
            <tr style={{ background: '#f5f5f5' }}>
              <th style={thSt}>{codeLabel}</th>
              {fields.map((f) => <th key={f.key} style={thSt}>{f.label}</th>)}
              <th style={thSt}>{t('common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.code}>
                <td style={{ ...tdSt, fontFamily: 'monospace', fontWeight: 600 }}>{item.code}</td>
                {fields.map((f) => (
                  <td key={f.key} style={f.monospace ? { ...tdSt, fontFamily: 'monospace' } : tdSt}>
                    {item[f.key] as unknown as string}
                  </td>
                ))}
                <td style={{ ...tdSt, whiteSpace: 'nowrap' }}>
                  <button aria-label={editAriaLabel(t('common.edit'), item.code)} style={btnSm({ marginRight: 4, background: '#f5f5f5', border: '1px solid #ccc' })} onClick={() => openEdit(item)}><PencilAltIcon /></button>
                  <button aria-label={editAriaLabel(t('common.delete'), item.code)} style={btnSm({ background: '#FAEAE8', border: '1px solid #C9190B', color: '#C9190B' })} onClick={() => handleDelete(item)}><TrashIcon /></button>
                </td>
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={fields.length + 2} style={{ ...tdSt, color: '#6A6E73', textAlign: 'center' }}>{emptyLabel}</td></tr>}
          </tbody>
        </table>
      </div>
      <Modal variant={ModalVariant.medium} isOpen={modalMode !== null} onClose={closeModal}>
        <ModalHeader title={modalMode === 'add' ? newLabel : `${editLabel} — ${editingItem?.code}`} />
        <ModalBody>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div>
              <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{codeLabel} {modalMode === 'add' && <span style={{ color: '#C9190B' }}>*</span>}</label>
              {modalMode === 'add' ? (
                <input aria-label={codeLabel} value={form.code} onChange={(e) => setFieldValue('code', e.target.value.toLowerCase())} placeholder={codePlaceholder} style={inputSt} />
              ) : (
                <input aria-label={codeLabel} value={form.code} disabled style={{ ...inputSt, background: '#f5f5f5', color: '#6A6E73' }} />
              )}
            </div>
            {modalFields.map((f) => (
              <div key={f.key}>
                <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{f.label} <span style={{ color: '#C9190B' }}>*</span></label>
                <input
                  aria-label={f.label}
                  value={form[f.key] as unknown as string}
                  onChange={(e) => setFieldValue(f.key, f.transform ? f.transform(e.target.value) : e.target.value)}
                  placeholder={f.placeholder}
                  style={inputSt}
                />
              </div>
            ))}
            {formError && <div style={{ color: '#C9190B', fontSize: '0.85rem' }}>{formError}</div>}
          </div>
        </ModalBody>
        <ModalFooter>
          <Button key="save" variant="primary" onClick={handleSave}>{t('common.save')}</Button>
          <Button key="cancel" variant="link" onClick={closeModal}>{t('common.cancel')}</Button>
        </ModalFooter>
      </Modal>

      <ConfirmModal
        isOpen={!!deleteTarget}
        title={t('common.confirmDeleteTitle')}
        message={deleteTarget ? deleteConfirmMessage(deleteTarget) : ''}
        isLoading={isDeleting}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
