// SPDX-License-Identifier: AGPL-3.0-or-later
// Extracted from GlobalConfigPage.tsx's CommissionManager (~408-line function mixing broker
// CRUD, commission-tier editing, FX editing, and a ticker allow-list widget) — this hook owns
// just the "new/edit/delete broker" modal state and handlers. See useCommissionEditor.ts for
// the sibling per-row commission/tickers/FX editing state. Zero JSX changes: the component
// still renders the exact same markup, driven by this hook's return value (mirrors
// useTransactionForm.ts's own extraction of TransactionsPage.tsx's TransactionModal).
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { createBrokerAPI, updateBrokerAPI, deleteBrokerAPI, updateBrokerPortfoliosAPI } from '../api/queries';
import type { Broker, User } from '../types';

interface BrokerForm {
  portfolio_ids: number[];
  name: string;
  currency: string;
  color: string;
}

export function useBrokerCrud(portfolios: User[]) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const [brokerModal, setBrokerModal] = useState<'new' | 'edit' | null>(null);
  const [brokerForm, setBrokerForm] = useState<BrokerForm>({ portfolio_ids: [], name: '', currency: 'EUR', color: '#1890FF' });
  const [brokerSaving, setBrokerSaving] = useState(false);
  const [brokerError, setBrokerError] = useState('');
  const [brokerEditingId, setBrokerEditingId] = useState<number | null>(null);
  const [brokerDeleteTarget, setBrokerDeleteTarget] = useState<Broker | null>(null);
  const [isDeletingBroker, setIsDeletingBroker] = useState(false);

  const openNewBroker = () => {
    setBrokerForm({ portfolio_ids: portfolios.map(p => p.id), name: '', currency: 'EUR', color: '#1890FF' });
    setBrokerError(''); setBrokerModal('new');
  };
  const openEditBroker = (acc: Broker) => {
    setBrokerForm({ portfolio_ids: acc.portfolio_ids, name: acc.name, currency: acc.currency ?? 'EUR', color: acc.color ?? '#1890FF' });
    setBrokerError(''); setBrokerEditingId(acc.id); setBrokerModal('edit');
  };
  const closeBrokerModal = () => { setBrokerModal(null); setBrokerEditingId(null); setBrokerError(''); };
  const toggleBrokerPortfolio = (pid: number) => setBrokerForm(f => ({
    ...f, portfolio_ids: f.portfolio_ids.includes(pid) ? f.portfolio_ids.filter(x => x !== pid) : [...f.portfolio_ids, pid],
  }));
  const handleSaveBroker = async () => {
    if (!brokerForm.name.trim()) { setBrokerError(t('pools.nameRequired')); return; }
    setBrokerSaving(true); setBrokerError('');
    try {
      if (brokerModal === 'new') {
        await createBrokerAPI({ name: brokerForm.name.trim(), currency: brokerForm.currency.toUpperCase(), color: brokerForm.color, portfolio_ids: brokerForm.portfolio_ids });
      } else {
        /* v8 ignore next -- @preserve */
        if (brokerEditingId !== null) {
          await updateBrokerAPI(brokerEditingId, { name: brokerForm.name.trim(), color: brokerForm.color });
          await updateBrokerPortfoliosAPI(brokerEditingId, brokerForm.portfolio_ids);
        }
      }
      qc.invalidateQueries({ queryKey: ['brokers'] }); closeBrokerModal();
    } catch (e: any) { setBrokerError(e?.response?.data?.detail ?? 'Erreur'); }
    finally { setBrokerSaving(false); }
  };
  const handleDeleteBroker = (acc: Broker) => {
    setBrokerDeleteTarget(acc);
  };
  const handleConfirmDeleteBroker = async () => {
    /* v8 ignore next -- @preserve */
    if (!brokerDeleteTarget) return;
    setIsDeletingBroker(true);
    try {
      await deleteBrokerAPI(brokerDeleteTarget.id);
      qc.invalidateQueries({ queryKey: ['brokers'] });
      setBrokerDeleteTarget(null);
    } catch (e: any) { alert(e?.response?.data?.detail ?? 'Impossible de supprimer'); }
    finally { setIsDeletingBroker(false); }
  };

  return {
    brokerModal, brokerForm, setBrokerForm, brokerSaving, brokerError,
    brokerEditingId, brokerDeleteTarget, setBrokerDeleteTarget, isDeletingBroker,
    openNewBroker, openEditBroker, closeBrokerModal, toggleBrokerPortfolio,
    handleSaveBroker, handleDeleteBroker, handleConfirmDeleteBroker,
  };
}
