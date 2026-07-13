/**
 * Configuration générale — paramètres globaux indépendants du portefeuille.
 */
import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  Card, CardBody, CardTitle,
  Modal, ModalVariant,
  PageSection, PageSectionVariants,
} from '@patternfly/react-core';
import { PencilAltIcon, PlusCircleIcon, TrashIcon } from '@patternfly/react-icons';
import { useQueryClient } from '@tanstack/react-query';
import { useSystemSetting, useSetSystemSetting, useAllBrokers, usePortfolios,
  createBrokerAPI, updateBrokerAPI, deleteBrokerAPI, updateBrokerPortfoliosAPI,
  useProducts, createProduct, updateProduct, deleteProduct } from '../api/queries';
import { useSortable } from '../hooks/useSortable';
import ConfirmModal from '../components/ConfirmModal';
import type { Broker, CommissionTier, Product } from '../types';
import { computeCommission } from '../utils/commission';

// ── Broker Manager ─────────────────────────────────────────────────────────

// ── Commission Manager (includes broker CRUD) ─────────────────────────────

function formatScheduleSummary(schedule: CommissionTier[] | null): string {
  if (!schedule || schedule.length === 0) return '—';
  if (schedule.length === 1 && schedule[0].type === 'flat') return `Fixe ${schedule[0].value.toFixed(2)} €`;
  const example = computeCommission(700, schedule);
  return `${schedule.length} tranches — ex. 700€ → ${example.toFixed(2)} €`;
}

async function putFXCommission(accountId: number, params: { monthly_free_eur: number | null; above_monthly_rate: number; weekend_rate: number | null }) {
  const res = await fetch(`/api/brokers/${accountId}/fx-commission`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) });
  if (!res.ok) throw new Error(await res.text());
}

async function putCommissionSaleRate(accountId: number, rate: number) {
  const res = await fetch(`/api/brokers/${accountId}/sale-rate`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ commission_sale_rate: rate }) });
  if (!res.ok) throw new Error(await res.text());
}

async function putCommissionSchedule(accountId: number, schedule: CommissionTier[]) {
  const res = await fetch(`/api/brokers/${accountId}/commission`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ commission_schedule: schedule }) });
  if (!res.ok) throw new Error(await res.text());
}

async function putAllowedTickers(accountId: number, tickers: string[] | null) {
  const res = await fetch(`/api/brokers/${accountId}/allowed-tickers`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ allowed_tickers: tickers }) });
  if (!res.ok) throw new Error(await res.text());
}

type EditMode = 'commission' | 'tickers' | 'fx';

function CommissionManager() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: accounts = [] } = useAllBrokers();
  const { data: allProducts = [] } = useProducts();
  const { data: portfolios = [] } = usePortfolios();

  const { sorted: sortedAccounts, toggle: toggleAcc, indicator: accInd, thStyle: accTh } =
    /* v8 ignore next -- @preserve */
    useSortable<Broker, keyof Broker>({ data: accounts, defaultCol: 'name', getValue: (a, col) => String(a[col] ?? '') });

  // ── Broker CRUD state ───────────────────────────────────────────────────
  const [brokerModal, setBrokerModal] = useState<'new' | 'edit' | null>(null);
  const [brokerForm, setBrokerForm] = useState({ portfolio_ids: [] as number[], name: '', currency: 'EUR', color: '#1890FF' });
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

  // ── Commission state ────────────────────────────────────────────────────
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editMode, setEditMode] = useState<EditMode>('commission');
  const [selectedTickers, setSelectedTickers] = useState<string[]>([]);
  const [tickerFilterLeft, setTickerFilterLeft] = useState('');
  const [tickerFilterRight, setTickerFilterRight] = useState('');
  const [fxMonthlyFree, setFxMonthlyFree] = useState<string>('');
  const [fxAboveRate, setFxAboveRate] = useState<string>('');
  const [fxWeekendRate, setFxWeekendRate] = useState<string>('');
  interface TierRow { up_to: string; type: 'flat' | 'percent'; value: string; }
  const [tiers, setTiers] = useState<TierRow[]>([]);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  // Transfer list derived state (computed once per render, used in tickers panel)
  const tickersAvailable = allProducts
    .filter(p => !selectedTickers.includes(p.ticker))
    .filter(p => !tickerFilterLeft || p.ticker.includes(tickerFilterLeft.toUpperCase()) || p.name.toLowerCase().includes(tickerFilterLeft.toLowerCase()))
    .sort((a, b) => a.ticker.localeCompare(b.ticker));
  const tickersAllowed = allProducts
    .filter(p => selectedTickers.includes(p.ticker))
    .filter(p => !tickerFilterRight || p.ticker.includes(tickerFilterRight.toUpperCase()) || p.name.toLowerCase().includes(tickerFilterRight.toLowerCase()))
    .sort((a, b) => a.ticker.localeCompare(b.ticker));
  const tickersUnknown = selectedTickers.filter(t => !allProducts.find(p => p.ticker === t));
  const addTicker = (t: string) => setSelectedTickers(s => [...s, t]);
  const removeTicker = (t: string) => setSelectedTickers(s => s.filter(x => x !== t));

  const tiersFromSchedule = (schedule: CommissionTier[] | null): TierRow[] =>
    (schedule ?? []).map(t => ({
      up_to: t.up_to != null ? String(t.up_to) : '',
      type: t.type,
      value: t.type === 'percent' ? String((t.value * 100).toFixed(5)).replace(/\.?0+$/, '') : String(t.value),
    }));

  const tiersToSchedule = (rows: TierRow[]): CommissionTier[] =>
    rows.map(r => ({
      up_to: r.up_to.trim() === '' ? null : parseFloat(r.up_to),
      type: r.type,
      value: r.type === 'percent' ? parseFloat(r.value) / 100 : parseFloat(r.value),
    }));

  const openEditCommission = (id: number, schedule: CommissionTier[] | null) => {
    setEditingId(id); setEditMode('commission'); setTiers(tiersFromSchedule(schedule)); setError('');
  };

  const handleSave = async () => {
    /* v8 ignore next -- @preserve */
    if (editingId === null) return;
    setError(''); setSaving(true);
    try {
      if (editMode === 'commission') {
        await putCommissionSchedule(editingId, tiersToSchedule(tiers));
      } else if (editMode === 'tickers') {
        await putAllowedTickers(editingId, selectedTickers.length ? selectedTickers : null);
      } else {
        /* v8 ignore next -- @preserve */
        const monthly = fxMonthlyFree.trim() === '' ? null : parseFloat(fxMonthlyFree);
        /* v8 ignore next -- @preserve */
        await putFXCommission(editingId, { monthly_free_eur: monthly, above_monthly_rate: parseFloat(fxAboveRate) || 0, weekend_rate: fxWeekendRate.trim() === '' ? null : parseFloat(fxWeekendRate) });
      }
      qc.invalidateQueries({ queryKey: ['brokers'] });
      setEditingId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Valeur invalide');
    } finally { setSaving(false); }
  };

  const thSt = { padding: '6px 8px', textAlign: 'left' as const, borderBottom: '1px solid #ddd' };
  const tdSt = { padding: '6px 8px', borderBottom: '1px solid #f0f0f0', verticalAlign: 'top' as const };

  const btnSm: React.CSSProperties = { padding: '3px 7px', border: '1px solid #ccc', borderRadius: 4, cursor: 'pointer', fontSize: '0.8rem', background: '#f5f5f5' };

  return (
    <div>
      {/* Broker modal (new / edit) */}
      <Modal variant={ModalVariant.medium}
        title={brokerModal === 'new' ? t('brokers.newBroker') : `${t('common.edit')} — ${accounts.find(a => a.id === brokerEditingId)?.name ?? ''}`}
        isOpen={brokerModal !== null} onClose={closeBrokerModal}
        actions={[
          <Button key="save" variant="primary" isLoading={brokerSaving} isDisabled={brokerSaving} onClick={handleSaveBroker}>{t('common.save')}</Button>,
          <Button key="cancel" variant="link" onClick={closeBrokerModal}>{t('common.cancel')}</Button>,
        ]}>
        {brokerError && <Alert variant="danger" title={brokerError} isInline style={{ marginBottom: '0.75rem' }} />}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{t('brokers.fields.name')} <span style={{ color: '#C9190B' }}>*</span></label>
            <input value={brokerForm.name} onChange={e => setBrokerForm(f => ({ ...f, name: e.target.value }))} style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc', fontSize: '0.9rem', width: '100%' }} />
          </div>
          {brokerModal === 'new' && (
            <div>
              <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{t('brokers.fields.currency')}</label>
              <input value={brokerForm.currency} onChange={e => setBrokerForm(f => ({ ...f, currency: e.target.value.toUpperCase() }))} maxLength={3} style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc', fontSize: '0.9rem', width: 80 }} />
            </div>
          )}
          <div>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{t('brokers.fields.color')}</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input type="color" value={brokerForm.color} onChange={e => setBrokerForm(f => ({ ...f, color: e.target.value }))} style={{ width: 36, height: 32, border: 'none', cursor: 'pointer', borderRadius: 4 }} />
              <span style={{ fontFamily: 'monospace', fontSize: '0.82rem', color: '#6A6E73' }}>{brokerForm.color}</span>
            </div>
          </div>
          <div>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{t('common.portfolio')}</label>
            <div style={{ display: 'flex', gap: 12 }}>
              {portfolios.map(p => (
                <label key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: '0.9rem', cursor: 'pointer' }}>
                  <input type="checkbox" checked={brokerForm.portfolio_ids.includes(p.id)} onChange={() => toggleBrokerPortfolio(p.id)} />
                  {p.name}
                </label>
              ))}
            </div>
          </div>
        </div>
      </Modal>

      {/* Top bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
        {error && <Alert variant="danger" title={error} isInline />}
        <div style={{ flex: 1 }} />
        <Button variant="primary" size="sm" onClick={openNewBroker}>+ {t('brokers.newBroker')}</Button>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
        <thead>
          <tr style={{ background: '#f5f5f5' }}>
            <th style={{ ...thSt, width: 14 }}></th>
            <th style={accTh('name')} onClick={() => toggleAcc('name')}>{t('common.broker')}{accInd('name')}</th>
            <th style={{ ...thSt, whiteSpace: 'nowrap', color: '#6A6E73' }}>{t('brokers.fields.currency')}</th>
            <th style={thSt}>Commission achat</th>
            <th style={thSt}>Comm. vente %</th>
            <th style={{ ...thSt, textAlign: 'center' as const }}>
              <span title="Si coché : le courtage payé est inclus dans le coût de revient (CUMP/PRU). Si décoché : le CUMP est calculé sur le prix d'exécution seul, sans frais.">Frais dans CUMP ℹ️</span>
            </th>
            <th style={thSt}>Produits autorisés</th>
            <th style={{ ...thSt, textAlign: 'left' as const }} title="Frais de change avec plafond mensuel gratuit">Change FX ℹ️</th>
            <th style={{ padding: '6px 8px', borderBottom: '1px solid #ddd' }}></th>
          </tr>
        </thead>
        <tbody>
          {sortedAccounts.map((acc) => (
            <tr key={acc.id}>
              <td style={{ ...tdSt, paddingRight: 0 }}>
                <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', backgroundColor: acc.color ?? '#6A6E73' }} />
              </td>
              <td style={{ ...tdSt, fontWeight: 500 }}>{acc.name}</td>
              <td style={{ ...tdSt, fontFamily: 'monospace', fontSize: '0.85rem' }}>{acc.currency}</td>
              <td style={{ ...tdSt, color: '#6A6E73', fontSize: '0.85rem' }}>{formatScheduleSummary(acc.commission_schedule)}</td>
              <td style={{ ...tdSt, fontSize: '0.85rem' }}>
                {acc.commission_sale_rate > 0 ? (
                  <input type="number" min={0} step={0.001} value={acc.commission_sale_rate}
                    onFocus={(e) => e.target.select()}
                    onChange={async (e) => { await putCommissionSaleRate(acc.id, parseFloat(e.target.value) || 0); qc.invalidateQueries({ queryKey: ['brokers'] }); }}
                    style={{ width: '70px', padding: '2px 6px', border: '1px solid #ccc', borderRadius: 4, fontSize: '0.85rem' }}
                    title={`${(acc.commission_sale_rate * 100).toFixed(1)}% sur les ventes`} />
                ) : acc.commission_schedule ? (
                  <span style={{ color: '#6A6E73', fontSize: '0.82rem', fontStyle: 'italic' }} title="Même tarif qu'à l'achat">= achat</span>
                ) : <span style={{ color: '#aaa' }}>—</span>}
                {acc.commission_sale_rate > 0 && (
                  <span style={{ marginLeft: 4, fontSize: '0.78rem', color: '#6A6E73' }}>({(acc.commission_sale_rate * 100).toFixed(1)}%)</span>
                )}
              </td>
              <td style={{ ...tdSt, textAlign: 'center' as const }}>
                <input type="checkbox" checked={acc.include_fees_in_cump}
                  title={acc.include_fees_in_cump ? 'Courtage inclus dans le CUMP' : 'Courtage exclu du CUMP'}
                  onChange={async () => {
                    await fetch(`/api/brokers/${acc.id}/include-fees`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ include_fees_in_cump: !acc.include_fees_in_cump }) });
                    qc.invalidateQueries({ queryKey: ['brokers'] });
                  }}
                  style={{ width: 16, height: 16, cursor: 'pointer' }} />
              </td>
              <td style={{ ...tdSt, color: '#6A6E73', fontSize: '0.85rem' }}>
                {acc.allowed_tickers ? <span title={acc.allowed_tickers.join(', ')}>{acc.allowed_tickers.length} produit{acc.allowed_tickers.length > 1 ? 's' : ''}</span> : <em>Tous</em>}
              </td>
              <td style={{ ...tdSt, fontSize: '0.82rem' }}>
                {acc.monthly_free_eur !== null ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span>{acc.monthly_free_eur}€/mois gratuits</span>
                    <span style={{ color: '#6A6E73' }}>au-delà: {(acc.above_monthly_rate * 100).toFixed(2)}%</span>
                    {acc.weekend_rate !== null && <span style={{ color: '#6A6E73' }}>week-end: {(acc.weekend_rate * 100).toFixed(2)}%</span>}
                  </div>
                ) : <span style={{ color: '#aaa' }}>—</span>}
              </td>
              <td style={tdSt}>
                {editingId === acc.id ? (
                  <div style={{ minWidth: 260 }}>
                    <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                      <Button size="sm" variant={editMode === 'commission' ? 'primary' : 'tertiary'} onClick={() => { setEditMode('commission'); setTiers(tiersFromSchedule(acc.commission_schedule)); }}>Commission</Button>
                      <Button size="sm" variant={editMode === 'tickers' ? 'primary' : 'tertiary'} onClick={() => { setEditMode('tickers'); setSelectedTickers(acc.allowed_tickers ?? []); setTickerFilterLeft(''); setTickerFilterRight(''); }}>Produits</Button>
                      <Button size="sm" variant={editMode === 'fx' ? 'primary' : 'tertiary'} onClick={() => { setEditMode('fx'); setFxMonthlyFree(acc.monthly_free_eur != null ? String(acc.monthly_free_eur) : ''); setFxAboveRate(acc.above_monthly_rate > 0 ? String((acc.above_monthly_rate * 100).toFixed(2)) : ''); setFxWeekendRate(acc.weekend_rate != null ? String((acc.weekend_rate * 100).toFixed(2)) : ''); }}>Change FX</Button>
                    </div>
                    {editMode === 'commission' ? (
                      <div style={{ marginBottom: 6 }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem', marginBottom: 4 }}>
                          <thead>
                            <tr style={{ background: '#f5f5f5' }}>
                              <th style={{ padding: '4px 6px', textAlign: 'left', borderBottom: '1px solid #ddd', color: '#6A6E73' }}>Jusqu'à (€)</th>
                              <th style={{ padding: '4px 6px', textAlign: 'left', borderBottom: '1px solid #ddd', color: '#6A6E73' }}>Type</th>
                              <th style={{ padding: '4px 6px', textAlign: 'left', borderBottom: '1px solid #ddd', color: '#6A6E73' }}>Montant / Taux</th>
                              <th style={{ padding: '4px 6px', borderBottom: '1px solid #ddd' }}></th>
                            </tr>
                          </thead>
                          <tbody>
                            {tiers.map((tier, i) => (
                              <tr key={i} style={{ borderBottom: '1px solid #f0f0f0' }}>
                                <td style={{ padding: '3px 4px' }}>
                                  <input type="number" min={0} step={1} value={tier.up_to} placeholder="Illimité" onFocus={(e) => e.target.select()} onChange={(e) => { const u = [...tiers]; u[i] = { ...u[i], up_to: e.target.value }; setTiers(u); }} style={{ width: '90px', padding: '2px 4px', border: '1px solid #ccc', borderRadius: 3, fontSize: '0.82rem' }} />
                                </td>
                                <td style={{ padding: '3px 4px' }}>
                                  <select value={tier.type} onChange={(e) => { const u = [...tiers]; u[i] = { ...u[i], type: e.target.value as 'flat' | 'percent' }; setTiers(u); }} style={{ padding: '2px 4px', border: '1px solid #ccc', borderRadius: 3, fontSize: '0.82rem' }}>
                                    <option value="flat">Fixe (€)</option>
                                    <option value="percent">% du montant</option>
                                  </select>
                                </td>
                                <td style={{ padding: '3px 4px' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                                    <input type="number" min={0} step={tier.type === 'percent' ? 0.001 : 0.01} value={tier.value} onFocus={(e) => e.target.select()} onChange={(e) => { const u = [...tiers]; u[i] = { ...u[i], value: e.target.value }; setTiers(u); }} style={{ width: '80px', padding: '2px 4px', border: '1px solid #ccc', borderRadius: 3, fontSize: '0.82rem' }} />
                                    <span style={{ fontSize: '0.75rem', color: '#6A6E73' }}>{tier.type === 'flat' ? '€' : '%'}</span>
                                  </div>
                                </td>
                                <td style={{ padding: '3px 4px' }}>
                                  <button type="button" onClick={() => setTiers(tiers.filter((_, j) => j !== i))} style={{ background: '#FAEAE8', border: '1px solid #C9190B', color: '#C9190B', borderRadius: 3, padding: '2px 6px', cursor: 'pointer', fontSize: '0.75rem' }}>×</button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <button type="button" onClick={() => setTiers([...tiers, { up_to: '', type: 'flat', value: '' }])} style={{ background: '#f0f8ff', border: '1px solid #0066CC', color: '#0066CC', borderRadius: 4, padding: '3px 10px', cursor: 'pointer', fontSize: '0.78rem' }}>+ Ajouter une tranche</button>
                        {tiers.length === 0 && <p style={{ fontSize: '0.78rem', color: '#6A6E73', marginTop: 4 }}>Grille vide → commission = 0€ pour tous les montants.</p>}
                      </div>
                    ) : editMode === 'tickers' ? (
                      <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                        {/* Gauche : produits disponibles */}
                        <div style={{ flex: 1, minWidth: 180, display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <div style={{ fontSize: '0.75rem', color: '#6A6E73', fontWeight: 600 }}>Disponibles</div>
                          <input value={tickerFilterLeft} onChange={e => setTickerFilterLeft(e.target.value)} placeholder="Filtrer…"
                            style={{ width: '100%', padding: '3px 6px', border: '1px solid #ddd', borderRadius: 4, fontSize: '0.82rem', boxSizing: 'border-box' }} />
                          <div style={{ border: '1px solid #ccc', borderRadius: 4, overflowY: 'auto', maxHeight: 220, minHeight: 120, background: '#fafafa' }}>
                            {tickersAvailable.map(p => (
                              <div key={p.ticker} onClick={() => addTicker(p.ticker)} title={`Clic pour autoriser`}
                                style={{ padding: '3px 8px', cursor: 'pointer', fontSize: '0.82rem', fontFamily: 'monospace', borderBottom: '1px solid #f0f0f0', userSelect: 'none' }}>
                                {p.ticker} <span style={{ color: '#6A6E73', fontFamily: 'sans-serif', fontSize: '0.75rem' }}>{p.name}</span>
                              </div>
                            ))}
                            {tickersAvailable.length === 0 && (
                              <div style={{ padding: '6px 8px', color: '#aaa', fontSize: '0.8rem' }}>{tickerFilterLeft ? 'Aucun résultat' : 'Tous autorisés'}</div>
                            )}
                          </div>
                          <button type="button" onClick={() => setSelectedTickers(prev => [...prev, ...allProducts.filter(p => !prev.includes(p.ticker)).map(p => p.ticker)])}
                            style={{ fontSize: '0.75rem', padding: '2px 8px', border: '1px solid #ccc', borderRadius: 4, cursor: 'pointer', background: '#f5f5f5', alignSelf: 'flex-start' }}>
                            Tout autoriser →
                          </button>
                        </div>
                        {/* Droite : produits autorisés */}
                        <div style={{ flex: 1, minWidth: 180, display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <div style={{ fontSize: '0.75rem', color: '#0066CC', fontWeight: 600 }}>Autorisés ({selectedTickers.length})</div>
                          <input value={tickerFilterRight} onChange={e => setTickerFilterRight(e.target.value)} placeholder="Filtrer…"
                            style={{ width: '100%', padding: '3px 6px', border: '1px solid #ddd', borderRadius: 4, fontSize: '0.82rem', boxSizing: 'border-box' }} />
                          <div style={{ border: '1px solid #ccc', borderRadius: 4, overflowY: 'auto', maxHeight: 220, minHeight: 120, background: '#fafafa' }}>
                            {tickersAllowed.map(p => (
                              <div key={p.ticker} onClick={() => removeTicker(p.ticker)} title={`Clic pour retirer`}
                                style={{ padding: '3px 8px', cursor: 'pointer', fontSize: '0.82rem', fontFamily: 'monospace', background: '#E7F3FF', borderBottom: '1px solid #f0f0f0', userSelect: 'none' }}>
                                {p.ticker} <span style={{ color: '#6A6E73', fontFamily: 'sans-serif', fontSize: '0.75rem' }}>{p.name}</span>
                              </div>
                            ))}
                            {tickersUnknown.filter(t => !tickerFilterRight || t.includes(tickerFilterRight.toUpperCase())).map(t => (
                              <div key={t} onClick={() => removeTicker(t)} title={`Ticker inconnu — clic pour retirer`}
                                style={{ padding: '3px 8px', cursor: 'pointer', fontSize: '0.82rem', fontFamily: 'monospace', background: '#FAEAE8', borderBottom: '1px solid #f0f0f0', userSelect: 'none' }}>
                                {t} <span style={{ color: '#C9190B', fontFamily: 'sans-serif', fontSize: '0.75rem' }}>inconnu</span>
                              </div>
                            ))}
                            {selectedTickers.length === 0 && (
                              <div style={{ padding: '6px 8px', color: '#aaa', fontSize: '0.8rem' }}>Aucun — tous autorisés</div>
                            )}
                          </div>
                          <button type="button" onClick={() => setSelectedTickers([])}
                            style={{ fontSize: '0.75rem', padding: '2px 8px', border: '1px solid #ccc', borderRadius: 4, cursor: 'pointer', background: '#f5f5f5', alignSelf: 'flex-start' }}>
                            ← Tout retirer
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div style={{ fontSize: '0.85rem' }}>
                        <div style={{ fontSize: '0.78rem', color: '#6A6E73', marginBottom: 8 }}>Laisser vide pour désactiver. Les taux sont en %.</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 6 }}>
                          <label>Plafond mensuel gratuit (€)<input type="number" min={0} step={1} value={fxMonthlyFree} placeholder="ex: 1000" onFocus={(e) => e.target.select()} onChange={(e) => setFxMonthlyFree(e.target.value)} style={{ display: 'block', width: '100%', padding: '4px 6px', border: '1px solid #ccc', borderRadius: 4, marginTop: 2 }} /></label>
                          <label>Taux au-delà du plafond (%)<input type="number" min={0} step={0.01} value={fxAboveRate} placeholder="ex: 1.00" onFocus={(e) => e.target.select()} onChange={(e) => setFxAboveRate(e.target.value)} style={{ display: 'block', width: '100%', padding: '4px 6px', border: '1px solid #ccc', borderRadius: 4, marginTop: 2 }} /></label>
                          <label>Taux week-end NY (% — vide = idem taux au-delà)<input type="number" min={0} step={0.01} value={fxWeekendRate} placeholder="ex: 1.00" onFocus={(e) => e.target.select()} onChange={(e) => setFxWeekendRate(e.target.value)} style={{ display: 'block', width: '100%', padding: '4px 6px', border: '1px solid #ccc', borderRadius: 4, marginTop: 2 }} /></label>
                        </div>
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 6 }}>
                      <Button variant="primary" size="sm" isLoading={saving} isDisabled={saving} onClick={handleSave}>{t('common.save')}</Button>
                      <Button variant="link" size="sm" isDisabled={saving} onClick={() => setEditingId(null)}>{t('common.cancel')}</Button>
                    </div>
                  </div>
                ) : (
                  <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
                    <button onClick={() => openEditBroker(acc)} style={{ ...btnSm }} title="Modifier nom/couleur/portfolios">✏️</button>
                    <button onClick={() => handleDeleteBroker(acc)} style={{ ...btnSm, background: '#FAEAE8', border: '1px solid #C9190B', color: '#C9190B' }} title="Supprimer le broker">🗑</button>
                    <Button variant="tertiary" size="sm" onClick={() => openEditCommission(acc.id, acc.commission_schedule)}>Commission</Button>
                    <Button variant="tertiary" size="sm" onClick={() => { setEditingId(acc.id); setEditMode('tickers'); setSelectedTickers(acc.allowed_tickers ?? []); setTickerFilterLeft(''); setTickerFilterRight(''); }}>Produits</Button>
                    <Button variant="tertiary" size="sm" onClick={() => { setEditingId(acc.id); setEditMode('fx'); setFxMonthlyFree(acc.monthly_free_eur != null ? String(acc.monthly_free_eur) : ''); setFxAboveRate(acc.above_monthly_rate > 0 ? String((acc.above_monthly_rate * 100).toFixed(2)) : ''); setFxWeekendRate(acc.weekend_rate != null ? String((acc.weekend_rate * 100).toFixed(2)) : ''); }}>Change FX</Button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <ConfirmModal
        isOpen={!!brokerDeleteTarget}
        title={t('common.confirmDeleteTitle')}
        message={brokerDeleteTarget ? t('brokers.deleteConfirm', { name: brokerDeleteTarget.name }) : ''}
        isLoading={isDeletingBroker}
        onConfirm={handleConfirmDeleteBroker}
        onCancel={() => setBrokerDeleteTarget(null)}
      />
    </div>
  );
}

// ── Product Manager ───────────────────────────────────────────────────────

const PRODUCT_CATEGORIES = ['Actif', 'Cash', 'Frais', 'Manuel', 'Revenu'] as const;
type ProductForm = { ticker: string; name: string; category: string; currency: string };
const EMPTY_FORM: ProductForm = { ticker: '', name: '', category: 'Actif', currency: 'EUR' };
type ProductSortCol = 'ticker' | 'name' | 'category' | 'currency';

function ProductManager() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: products = [], refetch } = useProducts();

  const [modalMode, setModalMode] = useState<'add' | 'edit' | null>(null);
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [form, setForm] = useState<ProductForm>(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [deleteError, setDeleteError] = useState<{ ticker: string; message: string } | null>(null);
  const [productDeleteTarget, setProductDeleteTarget] = useState<Product | null>(null);
  const [isDeletingProduct, setIsDeletingProduct] = useState(false);
  const [sortCol, setSortCol] = useState<ProductSortCol>('ticker');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const toggleSort = (col: ProductSortCol) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('asc'); }
  };

  const sortedProducts = [...products].sort((a, b) => {
    const dir = sortDir === 'asc' ? 1 : -1;
    return (a[sortCol] as string).localeCompare(b[sortCol] as string) * dir;
  });

  const openAdd = () => { setForm(EMPTY_FORM); setFormError(''); setEditingProduct(null); setModalMode('add'); };
  const openEdit = (p: Product) => { setForm({ ticker: p.ticker, name: p.name, category: p.category, currency: p.currency }); setFormError(''); setEditingProduct(p); setModalMode('edit'); };
  const closeModal = () => { setModalMode(null); setEditingProduct(null); setFormError(''); };

  const handleSave = async () => {
    if (!form.ticker.trim()) { setFormError(t('configGenerale.validation.tickerRequired')); return; }
    if (!form.name.trim()) { setFormError(t('configGenerale.validation.nameRequired')); return; }
    if (!form.currency.trim()) { setFormError(t('configGenerale.validation.currencyRequired')); return; }
    try {
      if (modalMode === 'add') {
        await createProduct({ ...form, ticker: form.ticker.trim().toUpperCase(), name: form.name.trim(), currency: form.currency.trim().toUpperCase() });
      } else {
        /* v8 ignore next -- @preserve */
        if (editingProduct) {
          await updateProduct(editingProduct.ticker, { name: form.name.trim(), category: form.category, currency: form.currency.trim().toUpperCase() });
        }
      }
      closeModal(); refetch(); qc.invalidateQueries({ queryKey: ['products'] });
    } catch (e: any) {
      setFormError(e?.response?.data?.detail ?? 'Erreur lors de l\'enregistrement');
    }
  };

  const handleDelete = (p: Product) => {
    setDeleteError(null);
    setProductDeleteTarget(p);
  };

  const handleConfirmDeleteProduct = async () => {
    /* v8 ignore next -- @preserve */
    if (!productDeleteTarget) return;
    setIsDeletingProduct(true);
    try {
      await deleteProduct(productDeleteTarget.ticker);
      refetch();
      qc.invalidateQueries({ queryKey: ['products'] });
      setProductDeleteTarget(null);
    } catch (e: any) {
      setDeleteError({ ticker: productDeleteTarget.ticker, message: e?.response?.data?.detail ?? 'Erreur lors de la suppression' });
    } finally { setIsDeletingProduct(false); }
  };

  const inputSt: React.CSSProperties = { padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc', fontSize: '0.9rem', width: '100%' };
  const tdSt: React.CSSProperties = { padding: '6px 8px', fontSize: '0.9rem', borderBottom: '1px solid #eee' };
  const btnSm = (extra?: React.CSSProperties): React.CSSProperties => ({ padding: '3px 8px', borderRadius: 4, cursor: 'pointer', fontSize: '0.8rem', border: 'none', ...extra });
  const thSt = (_col: ProductSortCol): React.CSSProperties => ({ padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #ddd', fontSize: '0.85rem', color: '#6A6E73', cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' });
  const ind = (col: ProductSortCol) => sortCol === col ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ' ⇅';

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
        <span style={{ fontSize: '0.85rem', color: '#6A6E73' }}>{products.length} produit(s)</span>
        <Button variant="primary" icon={<PlusCircleIcon />} size="sm" onClick={openAdd}>{t('configGenerale.newProduct')}</Button>
      </div>
      {deleteError && <Alert variant="danger" isInline title={t('error.deleteFailed')} style={{ marginBottom: '0.75rem' }}>{deleteError.message}</Alert>}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
          <thead>
            <tr style={{ background: '#f5f5f5' }}>
              <th style={thSt('ticker')} onClick={() => toggleSort('ticker')}>{t('configGenerale.fields.ticker')}{ind('ticker')}</th>
              <th style={thSt('name')} onClick={() => toggleSort('name')}>{t('configGenerale.fields.name')}{ind('name')}</th>
              <th style={thSt('category')} onClick={() => toggleSort('category')}>{t('configGenerale.fields.category')}{ind('category')}</th>
              <th style={thSt('currency')} onClick={() => toggleSort('currency')}>{t('configGenerale.fields.currency')}{ind('currency')}</th>
              <th style={{ padding: '6px 8px', textAlign: 'center', borderBottom: '1px solid #ddd', fontSize: '0.85rem', color: '#6A6E73' }}>
                <span title="Taxe sur les Transactions Financières — 0,4% à l'achat pour les grandes caps françaises.">TTF ℹ️</span>
              </th>
              <th style={{ padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #ddd', fontSize: '0.85rem', color: '#6A6E73' }}>{t('common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {sortedProducts.map(p => (
              <tr key={p.ticker}>
                <td style={{ ...tdSt, fontFamily: 'monospace', fontWeight: 600 }}>{p.ticker}</td>
                <td style={tdSt}>{p.name}</td>
                <td style={tdSt}><span style={{ padding: '2px 8px', borderRadius: 12, fontSize: '0.78rem', background: '#f0f0f0', border: '1px solid #ddd' }}>{p.category}</span></td>
                <td style={tdSt}>{p.currency}</td>
                <td style={{ ...tdSt, textAlign: 'center' }}>
                  <input type="checkbox" aria-label={`TTF éligible ${p.ticker}`} checked={p.is_ttf_eligible}
                    onChange={async () => { await updateProduct(p.ticker, { is_ttf_eligible: !p.is_ttf_eligible }); qc.invalidateQueries({ queryKey: ['products'] }); }}
                    style={{ width: 16, height: 16, cursor: 'pointer' }} />
                </td>
                <td style={{ ...tdSt, whiteSpace: 'nowrap' }}>
                  <button aria-label={`${t('common.edit')} ${p.ticker}`} style={btnSm({ marginRight: 4, background: '#f5f5f5', border: '1px solid #ccc' })} onClick={() => openEdit(p)}><PencilAltIcon /></button>
                  <button aria-label={`${t('common.delete')} ${p.ticker}`} style={btnSm({ background: '#FAEAE8', border: '1px solid #C9190B', color: '#C9190B' })} onClick={() => handleDelete(p)}><TrashIcon /></button>
                </td>
              </tr>
            ))}
            {products.length === 0 && <tr><td colSpan={5} style={{ ...tdSt, color: '#6A6E73', textAlign: 'center' }}>Aucun produit</td></tr>}
          </tbody>
        </table>
      </div>
      <Modal variant={ModalVariant.medium} title={modalMode === 'add' ? t('configGenerale.newProduct') : `${t('configGenerale.editProduct')} — ${editingProduct?.ticker}`}
        isOpen={modalMode !== null} onClose={closeModal}
        actions={[<Button key="save" variant="primary" onClick={handleSave}>{t('common.save')}</Button>, <Button key="cancel" variant="link" onClick={closeModal}>{t('common.cancel')}</Button>]}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <div>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{t('configGenerale.fields.ticker')} {modalMode === 'add' && <span style={{ color: '#C9190B' }}>*</span>}</label>
            {modalMode === 'add' ? (
              <input aria-label={t('configGenerale.fields.ticker')} value={form.ticker} onChange={e => setForm(f => ({ ...f, ticker: e.target.value.toUpperCase() }))} placeholder="Ex: AAPL" style={inputSt} />
            ) : (
              <input aria-label={t('configGenerale.fields.ticker')} value={form.ticker} disabled style={{ ...inputSt, background: '#f5f5f5', color: '#6A6E73' }} />
            )}
          </div>
          <div>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{t('configGenerale.fields.name')} <span style={{ color: '#C9190B' }}>*</span></label>
            <input aria-label={t('configGenerale.fields.name')} value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Ex: Apple Inc." style={inputSt} />
          </div>
          <div>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{t('configGenerale.fields.category')} <span style={{ color: '#C9190B' }}>*</span></label>
            <select aria-label={t('configGenerale.fields.category')} value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))} style={inputSt}>
              {PRODUCT_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{t('configGenerale.fields.currency')} <span style={{ color: '#C9190B' }}>*</span></label>
            <input aria-label={t('configGenerale.fields.currency')} value={form.currency} onChange={e => setForm(f => ({ ...f, currency: e.target.value.toUpperCase() }))} placeholder="Ex: EUR" style={inputSt} />
          </div>
          {formError && <div style={{ color: '#C9190B', fontSize: '0.85rem' }}>{formError}</div>}
        </div>
      </Modal>

      <ConfirmModal
        isOpen={!!productDeleteTarget}
        title={t('common.confirmDeleteTitle')}
        message={productDeleteTarget
          ? t('configGenerale.deleteProductConfirm', { name: `${productDeleteTarget.ticker} — ${productDeleteTarget.name}` })
          : ''}
        isLoading={isDeletingProduct}
        onConfirm={handleConfirmDeleteProduct}
        onCancel={() => setProductDeleteTarget(null)}
      />
    </div>
  );
}

export default function GlobalConfigPage() {
  const { t } = useTranslation();
  const { data: ttfSetting } = useSystemSetting('ttf_rate');
  const setSettingMutation = useSetSystemSetting();
  const [ttfRate, setTtfRate] = useState<string>('0.40');
  const [ttfSaved, setTtfSaved] = useState(false);

  useEffect(() => {
    if (ttfSetting?.value) {
      setTtfRate((parseFloat(ttfSetting.value) * 100).toFixed(2));
    }
  }, [ttfSetting]);

  const saveTTF = async () => {
    await setSettingMutation.mutateAsync({ key: 'ttf_rate', value: String(parseFloat(ttfRate) / 100) });
    setTtfSaved(true);
    setTimeout(() => setTtfSaved(false), 2000);
  };

  return (
    <PageSection variant={PageSectionVariants.default}>


      {/* ── TTF Rate ── */}
      <Card style={{ maxWidth: 600, marginBottom: '1.5rem' }}>
        <CardTitle>📊 Taux TTF (Taxe sur les Transactions Financières)</CardTitle>
        <CardBody>
          <p style={{ fontSize: '0.85rem', color: '#6A6E73', marginBottom: '1rem' }}>
            Taux appliqué automatiquement à l'achat des valeurs françaises éligibles (grande cap &gt; 1 Md€).
            Modifiable si la législation change.
          </p>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input
                type="number" min={0} max={5} step={0.01}
                value={ttfRate}
                onFocus={(e) => e.target.select()}
                onChange={(e) => setTtfRate(e.target.value)}
                style={{ width: 80, padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '1rem' }}
              />
              <span style={{ fontSize: '0.9rem', color: '#6A6E73' }}>%</span>
            </div>
            <button
              onClick={saveTTF}
              disabled={setSettingMutation.isPending}
              style={{ padding: '6px 16px', background: '#0066CC', color: 'white', border: 'none',
                borderRadius: 4, cursor: 'pointer', fontSize: '0.9rem' }}
            >
              {setSettingMutation.isPending ? `${t('common.save')}…` : ttfSaved ? `✓ ${t('common.save')}` : t('common.save')}
            </button>
          </div>
          <p style={{ fontSize: '0.75rem', color: '#6A6E73', marginTop: '0.5rem' }}>
            Taux actuel en vigueur depuis mars 2025 : 0.4% (anciennement 0.3%)
          </p>
        </CardBody>
      </Card>

      {/* ── Brokers + Commissions (tableau unifié) ── */}
      <Card style={{ marginBottom: '1.5rem' }}>
        <CardTitle>🏦 Brokers</CardTitle>
        <CardBody>
          <p style={{ fontSize: '0.85rem', color: '#6A6E73', marginBottom: '1rem' }}>
            Gérer les brokers et leur configuration : nom, couleur, portfolios associés, grilles de commissions, produits autorisés et frais de change (FX).
          </p>
          <CommissionManager />
        </CardBody>
      </Card>

      {/* ── Produits financiers ── */}
      <Card style={{ marginBottom: '1.5rem' }}>
        <CardTitle>📦 Produits financiers</CardTitle>
        <CardBody>
          <p style={{ fontSize: '0.85rem', color: '#6A6E73', marginBottom: '1rem' }}>
            Catalogue des instruments financiers (ETF, actions, cash, or…). Le ticker est la clé primaire et ne peut pas être modifié. La suppression est bloquée si des transactions y font référence.
          </p>
          <ProductManager />
        </CardBody>
      </Card>
    </PageSection>
  );
}
