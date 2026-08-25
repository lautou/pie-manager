// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Configuration générale — paramètres globaux indépendants du portefeuille.
 */
import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
	Alert,
	Button,
	Card,
	CardBody,
	CardTitle,
	Modal,
	ModalBody,
	ModalFooter,
	ModalHeader,
	ModalVariant,
	PageSection,
	PageSectionVariants
} from '@patternfly/react-core';
import { PencilAltIcon, PlusCircleIcon, TrashIcon } from '@patternfly/react-icons';
import { useQueryClient } from '@tanstack/react-query';
import { useSystemSetting, useSetSystemSetting, useAllBrokers, usePortfolios,
  useProducts, createProduct, updateProduct, deleteProduct,
  useMacroRegions, createMacroRegion, updateMacroRegion, deleteMacroRegion,
  useCountryPerfConfigs, createCountryPerfConfig, updateCountryPerfConfig, deleteCountryPerfConfig,
  useSectorPerfConfigs, createSectorPerfConfig, updateSectorPerfConfig, deleteSectorPerfConfig,
  useEquityPremiumConfigs, createEquityPremiumConfig, updateEquityPremiumConfig, deleteEquityPremiumConfig,
} from '../api/queries';
import { useSortable } from '../hooks/useSortable';
import ConfirmModal from '../components/ConfirmModal';
import CrudManager from '../components/CrudManager';
import TickerLink from '../components/TickerLink';
import EtfCompositionModal from '../components/EtfCompositionModal';
import SettingField from '../components/SettingField';
import type { Broker, CommissionTier, CountryPerfConfig, EquityPremiumConfig, MacroRegionConfig, Product, SectorPerfConfig } from '../types';
import { computeCommission } from '../utils/commission';
import { INSTRUMENT_TYPE_GOLD } from '../utils/productConstants';
import { useBrokerCrud } from '../hooks/useBrokerCrud';
import { useCommissionEditor, putCommissionSaleRate } from '../hooks/useCommissionEditor';

// ── Broker Manager ─────────────────────────────────────────────────────────

// ── Commission Manager (includes broker CRUD) ─────────────────────────────

function formatScheduleSummary(schedule: CommissionTier[] | null): string {
  if (!schedule || schedule.length === 0) return '—';
  if (schedule.length === 1 && schedule[0].type === 'flat') return `Fixe ${schedule[0].value.toFixed(2)} €`;
  const example = computeCommission(700, schedule);
  return `${schedule.length} tranches — ex. 700€ → ${example.toFixed(2)} €`;
}

function CommissionManager() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: accounts = [] } = useAllBrokers();
  const { data: allProducts = [] } = useProducts();
  const { data: portfolios = [] } = usePortfolios();

  const { sorted: sortedAccounts, toggle: toggleAcc, indicator: accInd, thStyle: accTh } =
    useSortable<Broker, keyof Broker>({
      data: accounts, defaultCol: 'name',
      /* v8 ignore next -- @preserve */
      getValue: (a, col) => String(a[col] ?? ''),
    });

  const brokerCrud = useBrokerCrud(portfolios);
  const {
    brokerModal, brokerForm, setBrokerForm, brokerSaving, brokerError,
    brokerEditingId, brokerDeleteTarget, setBrokerDeleteTarget, isDeletingBroker,
    openNewBroker, openEditBroker, closeBrokerModal, toggleBrokerPortfolio,
    handleSaveBroker, handleDeleteBroker, handleConfirmDeleteBroker,
  } = brokerCrud;

  const commissionEditor = useCommissionEditor(allProducts);
  const {
    editingId, setEditingId, editMode, setEditMode,
    selectedTickers, setSelectedTickers, tickerFilterLeft, setTickerFilterLeft,
    tickerFilterRight, setTickerFilterRight,
    fxMonthlyFree, setFxMonthlyFree, fxAboveRate, setFxAboveRate, fxWeekendRate, setFxWeekendRate,
    tiers, setTiers, error, saving,
    tickersAvailable, tickersAllowed, tickersUnknown, addTicker, removeTicker,
    tiersFromSchedule, openEditCommission, handleSave,
  } = commissionEditor;

  const thSt = { padding: '6px 8px', textAlign: 'left' as const, borderBottom: '1px solid #ddd' };
  const tdSt = { padding: '6px 8px', borderBottom: '1px solid #f0f0f0', verticalAlign: 'top' as const };

  const btnSm: React.CSSProperties = { padding: '3px 7px', border: '1px solid #ccc', borderRadius: 4, cursor: 'pointer', fontSize: '0.8rem', background: '#f5f5f5' };

  return (
    <div>
      {/* Broker modal (new / edit) */}
      <Modal variant={ModalVariant.medium}
        isOpen={brokerModal !== null} onClose={closeBrokerModal}>
        <ModalHeader title={brokerModal === 'new' ? t('brokers.newBroker') : `${t('common.edit')} — ${accounts.find(a => a.id === brokerEditingId)?.name ?? ''}`} />
        <ModalBody>
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
        </ModalBody>
        <ModalFooter>
          <Button key="save" variant="primary" isLoading={brokerSaving} isDisabled={brokerSaving} onClick={handleSaveBroker}>{t('common.save')}</Button>
          <Button key="cancel" variant="link" onClick={closeBrokerModal}>{t('common.cancel')}</Button>
        </ModalFooter>
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
                    onChange={async (e) => {
                      try {
                        await putCommissionSaleRate(acc.id, parseFloat(e.target.value) || 0);
                        qc.invalidateQueries({ queryKey: ['brokers'] });
                      } catch (err) {
                        alert(err instanceof Error ? err.message : 'Erreur lors de la mise à jour du taux de vente');
                      }
                    }}
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

const PRODUCT_CATEGORIES = ['Actif', 'Frais'] as const;
const INSTRUMENT_TYPES = ['ETF', 'SICAV/FCP', 'Action', 'Obligation', INSTRUMENT_TYPE_GOLD, 'Cash'] as const;
const FEE_TYPES = ['Courtage', 'Tenue de compte', 'Intérêts négatifs', 'Bourse', 'TTF', 'Impôts', 'Conversion'] as const;
type ProductForm = { ticker: string; name: string; category: string; instrument_type: string; fee_type: string; currency: string };
const EMPTY_FORM: ProductForm = { ticker: '', name: '', category: 'Actif', instrument_type: '', fee_type: '', currency: 'EUR' };
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
  const [compositionTicker, setCompositionTicker] = useState<string | null>(null);

  const toggleSort = (col: ProductSortCol) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('asc'); }
  };

  const sortedProducts = [...products].sort((a, b) => {
    const dir = sortDir === 'asc' ? 1 : -1;
    return (a[sortCol] as string).localeCompare(b[sortCol] as string) * dir;
  });

  const openAdd = () => { setForm(EMPTY_FORM); setFormError(''); setEditingProduct(null); setModalMode('add'); };
  const openEdit = (p: Product) => { setForm({ ticker: p.ticker, name: p.name, category: p.category, instrument_type: p.instrument_type ?? '', fee_type: p.fee_type ?? '', currency: p.currency }); setFormError(''); setEditingProduct(p); setModalMode('edit'); };
  const closeModal = () => { setModalMode(null); setEditingProduct(null); setFormError(''); };

  const handleSave = async () => {
    if (!form.ticker.trim()) { setFormError(t('configGenerale.validation.tickerRequired')); return; }
    if (!form.name.trim()) { setFormError(t('configGenerale.validation.nameRequired')); return; }
    if (!form.currency.trim()) { setFormError(t('configGenerale.validation.currencyRequired')); return; }
    // Only the sub-classification matching the chosen category is kept
    const instrument_type = form.category === 'Actif' ? (form.instrument_type || null) : null;
    const fee_type = form.category === 'Frais' ? (form.fee_type || null) : null;
    try {
      if (modalMode === 'add') {
        await createProduct({ ...form, instrument_type, fee_type, ticker: form.ticker.trim().toUpperCase(), name: form.name.trim(), currency: form.currency.trim().toUpperCase() });
      } else {
        /* v8 ignore next -- @preserve */
        if (editingProduct) {
          await updateProduct(editingProduct.ticker, { name: form.name.trim(), category: form.category, instrument_type, fee_type, currency: form.currency.trim().toUpperCase() });
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
              <th style={{ padding: '6px 8px', textAlign: 'left', borderBottom: '1px solid #ddd', fontSize: '0.85rem', color: '#6A6E73' }}>{t('configGenerale.fields.type')}</th>
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
                <td style={{ ...tdSt, fontFamily: 'monospace', fontWeight: 600 }}>
                  <TickerLink ticker={p.ticker} instrumentType={p.instrument_type} onClick={setCompositionTicker} />
                </td>
                <td style={tdSt}>{p.name}</td>
                <td style={tdSt}><span style={{ padding: '2px 8px', borderRadius: 12, fontSize: '0.78rem', background: '#f0f0f0', border: '1px solid #ddd' }}>{p.category}</span></td>
                <td style={tdSt}>{p.instrument_type || p.fee_type || '—'}</td>
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
            {products.length === 0 && <tr><td colSpan={7} style={{ ...tdSt, color: '#6A6E73', textAlign: 'center' }}>Aucun produit</td></tr>}
          </tbody>
        </table>
      </div>
      <Modal variant={ModalVariant.medium}
        isOpen={modalMode !== null} onClose={closeModal}>
        <ModalHeader title={modalMode === 'add' ? t('configGenerale.newProduct') : `${t('configGenerale.editProduct')} — ${editingProduct?.ticker}`} />
        <ModalBody>
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
            <select aria-label={t('configGenerale.fields.category')} value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value, instrument_type: '', fee_type: '' }))} style={inputSt}>
              {PRODUCT_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          {form.category === 'Actif' && (
            <div>
              <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{t('configGenerale.fields.instrumentType')}</label>
              <select aria-label={t('configGenerale.fields.instrumentType')} value={form.instrument_type} onChange={e => setForm(f => ({ ...f, instrument_type: e.target.value }))} style={inputSt}>
                <option value="">—</option>
                {INSTRUMENT_TYPES.map(it => <option key={it} value={it}>{it}</option>)}
              </select>
            </div>
          )}
          {form.category === 'Frais' && (
            <div>
              <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{t('configGenerale.fields.feeType')}</label>
              <select aria-label={t('configGenerale.fields.feeType')} value={form.fee_type} onChange={e => setForm(f => ({ ...f, fee_type: e.target.value }))} style={inputSt}>
                <option value="">—</option>
                {FEE_TYPES.map(ft => <option key={ft} value={ft}>{ft}</option>)}
              </select>
            </div>
          )}
          <div>
            <label style={{ fontSize: '0.85rem', fontWeight: 600, display: 'block', marginBottom: 4 }}>{t('configGenerale.fields.currency')} <span style={{ color: '#C9190B' }}>*</span></label>
            <input aria-label={t('configGenerale.fields.currency')} value={form.currency} onChange={e => setForm(f => ({ ...f, currency: e.target.value.toUpperCase() }))} placeholder="Ex: EUR" style={inputSt} />
          </div>
          {formError && <div style={{ color: '#C9190B', fontSize: '0.85rem' }}>{formError}</div>}
        </div>
        </ModalBody>
        <ModalFooter>
          <Button key="save" variant="primary" onClick={handleSave}>{t('common.save')}</Button>
          <Button key="cancel" variant="link" onClick={closeModal}>{t('common.cancel')}</Button>
        </ModalFooter>
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

      <EtfCompositionModal ticker={compositionTicker} onClose={() => setCompositionTicker(null)} />
    </div>
  );
}

// ── Macro indicators region manager ───────────────────────────────────────

const EMPTY_REGION_FORM: MacroRegionConfig = {
  code: '', label: '', equity_ticker: '', bond_ticker: '', equity_label: '', bond_label: '',
};

function RegionManager() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: regions = [], refetch } = useMacroRegions();

  const onMutated = () => {
    refetch();
    qc.invalidateQueries({ queryKey: ['macro-regions'] });
    qc.invalidateQueries({ queryKey: ['macro-growth'] });
    qc.invalidateQueries({ queryKey: ['macro-inflation'] });
  };

  return (
    <CrudManager<MacroRegionConfig>
      items={regions}
      emptyForm={EMPTY_REGION_FORM}
      codeLabel={t('indicators.regionCode')}
      codePlaceholder="Ex: de"
      codeValidationMessage={t('indicators.validation.codeRequired')}
      fields={[
        { key: 'label', label: t('indicators.regionLabel'), placeholder: 'Ex: Allemagne', validationMessage: t('indicators.validation.labelRequired') },
        { key: 'equity_label', label: t('indicators.regionEquityLabel'), placeholder: 'Ex: DAX 40', validationMessage: t('indicators.validation.equityLabelRequired') },
        { key: 'equity_ticker', label: t('indicators.tickerEquity'), placeholder: 'Ex: ^GDAXI', monospace: true, validationMessage: t('indicators.validation.equityTickerRequired') },
        { key: 'bond_label', label: t('indicators.regionBondLabel'), placeholder: 'Ex: Bund 10 ans', validationMessage: t('indicators.validation.bondLabelRequired') },
        { key: 'bond_ticker', label: t('indicators.tickerBond'), placeholder: 'Ex: BUND', monospace: true, validationMessage: t('indicators.validation.bondTickerRequired') },
      ]}
      modalOrder={['label', 'equity_ticker', 'equity_label', 'bond_ticker', 'bond_label']}
      validationOrder={['label', 'equity_ticker', 'bond_ticker', 'equity_label', 'bond_label']}
      ariaNoun=""
      countLabel={`${regions.length} région(s)`}
      newLabel={t('indicators.newRegion')}
      editLabel={t('indicators.editRegion')}
      emptyLabel={t('indicators.noRegions')}
      deleteConfirmMessage={(item) => t('indicators.deleteRegionConfirm', { name: `${item.code} — ${item.label}` })}
      onCreate={createMacroRegion}
      onUpdate={updateMacroRegion}
      onDelete={deleteMacroRegion}
      onMutated={onMutated}
    />
  );
}

// ── Market Country Manager (country-performance leaderboard universe) ──────

const EMPTY_COUNTRY_FORM: CountryPerfConfig = { code: '', label: '', index_ticker: '', currency: '', index_label: '' };

function MarketCountryManager() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: countries = [], refetch } = useCountryPerfConfigs();

  const onMutated = () => {
    refetch();
    qc.invalidateQueries({ queryKey: ['country-perf-configs'] });
    qc.invalidateQueries({ queryKey: ['country-performance'] });
  };

  return (
    <CrudManager<CountryPerfConfig>
      items={countries}
      emptyForm={EMPTY_COUNTRY_FORM}
      codeLabel={t('marketPerformance.countryCode')}
      codePlaceholder="Ex: de"
      codeValidationMessage={t('marketPerformance.validation.codeRequired')}
      fields={[
        { key: 'label', label: t('marketPerformance.countryLabel'), placeholder: 'Ex: Allemagne', validationMessage: t('marketPerformance.validation.labelRequired') },
        { key: 'index_label', label: t('marketPerformance.indexLabel'), placeholder: 'Ex: DAX 40', validationMessage: t('marketPerformance.validation.indexLabelRequired') },
        { key: 'index_ticker', label: t('marketPerformance.indexTicker'), placeholder: 'Ex: ^GDAXI', monospace: true, validationMessage: t('marketPerformance.validation.indexTickerRequired') },
        { key: 'currency', label: t('marketPerformance.currency'), placeholder: 'Ex: EUR', monospace: true, transform: (v) => v.toUpperCase(), validationMessage: t('marketPerformance.validation.currencyRequired') },
      ]}
      validationOrder={['label', 'index_ticker', 'currency', 'index_label']}
      // "pays" distinguishes these from RegionManager's bare "Modifier fr"/"Supprimer fr" —
      // both managers can have a row with the same code (e.g. "fr"), which made their
      // aria-labels collide on the same page until this was caught in a real browser check
      // (unit tests used non-overlapping fixture codes, hiding it).
      ariaNoun="pays"
      countLabel={`${countries.length} pays`}
      newLabel={t('marketPerformance.newCountry')}
      editLabel={t('marketPerformance.editCountry')}
      emptyLabel={t('marketPerformance.noCountries')}
      deleteConfirmMessage={(item) => t('marketPerformance.deleteCountryConfirm', { name: `${item.code} — ${item.label}` })}
      onCreate={createCountryPerfConfig}
      onUpdate={updateCountryPerfConfig}
      onDelete={deleteCountryPerfConfig}
      onMutated={onMutated}
    />
  );
}

// ── Sector Manager (sector-performance fixed universe) ──────────────────────

const EMPTY_SECTOR_FORM: SectorPerfConfig = { code: '', label: '', index_ticker: '', currency: '', index_label: '' };

function SectorManager() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: sectors = [], refetch } = useSectorPerfConfigs();

  const onMutated = () => {
    refetch();
    qc.invalidateQueries({ queryKey: ['sector-perf-configs'] });
    qc.invalidateQueries({ queryKey: ['sector-performance'] });
  };

  return (
    <CrudManager<SectorPerfConfig>
      items={sectors}
      emptyForm={EMPTY_SECTOR_FORM}
      codeLabel={t('sectorPerformance.sectorCode')}
      codePlaceholder="Ex: metaux"
      codeValidationMessage={t('sectorPerformance.validation.codeRequired')}
      fields={[
        { key: 'label', label: t('sectorPerformance.sectorLabel'), placeholder: 'Ex: Métaux industriels', validationMessage: t('sectorPerformance.validation.labelRequired') },
        { key: 'index_label', label: t('sectorPerformance.indexLabel'), placeholder: 'Ex: Invesco DB Base Metals Fund', validationMessage: t('sectorPerformance.validation.indexLabelRequired') },
        { key: 'index_ticker', label: t('sectorPerformance.indexTicker'), placeholder: 'Ex: DBB', monospace: true, validationMessage: t('sectorPerformance.validation.indexTickerRequired') },
        { key: 'currency', label: t('sectorPerformance.currency'), placeholder: 'Ex: USD', monospace: true, transform: (v) => v.toUpperCase(), validationMessage: t('sectorPerformance.validation.currencyRequired') },
      ]}
      validationOrder={['label', 'index_ticker', 'currency', 'index_label']}
      // "secteur" disambiguates from RegionManager's/MarketCountryManager's own aria-labels —
      // same collision-avoidance rule as "pays" above, applied defensively even though sector
      // codes don't currently overlap either.
      ariaNoun="secteur"
      countLabel={`${sectors.length} secteurs`}
      newLabel={t('sectorPerformance.newSector')}
      editLabel={t('sectorPerformance.editSector')}
      emptyLabel={t('sectorPerformance.noSectors')}
      deleteConfirmMessage={(item) => t('sectorPerformance.deleteSectorConfirm', { name: `${item.code} — ${item.label}` })}
      onCreate={createSectorPerfConfig}
      onUpdate={updateSectorPerfConfig}
      onDelete={deleteSectorPerfConfig}
      onMutated={onMutated}
    />
  );
}

// ── Equity Premium Manager (equity risk premium universe) ───────────────────

const EMPTY_EQUITY_PREMIUM_FORM: EquityPremiumConfig = {
  code: '', label: '', equity_ticker: '', bond_ticker: '', equity_label: '', bond_label: '',
};

function EquityPremiumManager() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: countries = [], refetch } = useEquityPremiumConfigs();

  const onMutated = () => {
    refetch();
    qc.invalidateQueries({ queryKey: ['equity-premium-configs'] });
    qc.invalidateQueries({ queryKey: ['equity-premium'] });
  };

  return (
    <CrudManager<EquityPremiumConfig>
      items={countries}
      emptyForm={EMPTY_EQUITY_PREMIUM_FORM}
      codeLabel={t('equityPremium.countryCode')}
      codePlaceholder="Ex: de"
      codeValidationMessage={t('equityPremium.validation.codeRequired')}
      fields={[
        { key: 'label', label: t('equityPremium.countryLabel'), placeholder: 'Ex: Allemagne', validationMessage: t('equityPremium.validation.labelRequired') },
        { key: 'equity_label', label: t('equityPremium.equityLabel'), placeholder: 'Ex: Actions allemandes (EWG)', validationMessage: t('equityPremium.validation.equityLabelRequired') },
        { key: 'equity_ticker', label: t('equityPremium.equityTicker'), placeholder: 'Ex: EWG', monospace: true, validationMessage: t('equityPremium.validation.equityTickerRequired') },
        { key: 'bond_label', label: t('equityPremium.bondLabel'), placeholder: "Ex: Obligations d'État allemandes 10.5+ ans", validationMessage: t('equityPremium.validation.bondLabelRequired') },
        { key: 'bond_ticker', label: t('equityPremium.bondTicker'), placeholder: 'Ex: EXX6.DE', monospace: true, validationMessage: t('equityPremium.validation.bondTickerRequired') },
      ]}
      validationOrder={['label', 'equity_ticker', 'bond_ticker', 'equity_label', 'bond_label']}
      // "prime" disambiguates from RegionManager's/MarketCountryManager's own aria-labels —
      // same collision-avoidance rule as "pays"/"secteur" above: these country codes
      // (us/de/fr/...) literally overlap both managers'.
      ariaNoun="prime"
      countLabel={`${countries.length} pays`}
      newLabel={t('equityPremium.newCountry')}
      editLabel={t('equityPremium.editCountry')}
      emptyLabel={t('equityPremium.noCountries')}
      deleteConfirmMessage={(item) => t('equityPremium.deleteCountryConfirm', { name: `${item.code} — ${item.label}` })}
      onCreate={createEquityPremiumConfig}
      onUpdate={updateEquityPremiumConfig}
      onDelete={deleteEquityPremiumConfig}
      onMutated={onMutated}
    />
  );
}

export default function GlobalConfigPage() {
  const { t } = useTranslation();
  const { data: ttfSetting } = useSystemSetting('ttf_rate');
  const { data: topNSetting } = useSystemSetting('country_perf.top_n');
  const topN = topNSetting?.value ?? '15';
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
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>


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

      {/* ── Produits et frais financiers ── */}
      <Card style={{ marginBottom: '1.5rem' }}>
        <CardTitle>📦 Produits et frais financiers</CardTitle>
        <CardBody>
          <p style={{ fontSize: '0.85rem', color: '#6A6E73', marginBottom: '1rem' }}>
            Catalogue des instruments financiers (ETF, actions, cash, or…) et des types de frais. Le ticker est la clé primaire et ne peut pas être modifié. La suppression est bloquée si des transactions y font référence.
          </p>
          <ProductManager />
        </CardBody>
      </Card>

      {/* ── Indicateurs macro (régions + tickers communs) ── */}
      <Card style={{ marginBottom: '1.5rem' }}>
        <CardTitle>{t('indicators.macroSectionTitle')}</CardTitle>
        <CardBody>
          <p style={{ fontSize: '0.85rem', color: '#6A6E73', marginBottom: '1rem' }}>
            {t('indicators.macroSectionDescription')}
          </p>
          <RegionManager />
          <div style={{ fontWeight: 600, margin: '1.25rem 0 0.5rem' }}>{t('indicators.sharedTickersLabel')}</div>
          <SettingField settingKey="macro.ticker.oil" label={t('indicators.tickerOil')} defaultValue="CL=F" />
          <SettingField settingKey="macro.ticker.oil.label" label={t('indicators.tickerOilLabel')} defaultValue="Pétrole (WTI)" />
          <SettingField settingKey="macro.ticker.gold" label={t('indicators.tickerGold')} defaultValue="GC=F" />
          <SettingField settingKey="macro.ticker.gold.label" label={t('indicators.tickerGoldLabel')} defaultValue="Or" />
          <SettingField settingKey="macro.ma_years" label={t('indicators.maYearsLabel')} defaultValue="7" type="number" />
          <div style={{ fontSize: '0.78rem', color: '#6A6E73', marginTop: '0.5rem' }}>
            {t('indicators.settingsHint')}
          </div>
        </CardBody>
      </Card>

      {/* ── Rééquilibrage — seuils de tolérance ── */}
      <Card style={{ marginBottom: '1.5rem' }}>
        <CardTitle>{t('rebalancing.toleranceSectionTitle')}</CardTitle>
        <CardBody>
          <p style={{ fontSize: '0.85rem', color: '#6A6E73', marginBottom: '1rem' }}>
            {t('rebalancing.toleranceSectionDescription')}
          </p>
          <SettingField settingKey="rebalancing.tolerance_ok_pct" label={t('rebalancing.toleranceOkLabel')} defaultValue="1" type="number" />
          <SettingField settingKey="rebalancing.tolerance_warning_pct" label={t('rebalancing.toleranceWarningLabel')} defaultValue="2" type="number" />
        </CardBody>
      </Card>

      {/* ── Performance des actions (univers de pays) ── */}
      <Card style={{ marginBottom: '1.5rem' }}>
        <CardTitle>{t('marketPerformance.sectionTitle')}</CardTitle>
        <CardBody>
          <p style={{ fontSize: '0.85rem', color: '#6A6E73', marginBottom: '1rem' }}>
            {t('marketPerformance.sectionDescription', { topN })}
          </p>
          <MarketCountryManager />
          <div style={{ marginTop: '1.25rem' }}>
            <SettingField settingKey="country_perf.top_n" label={t('marketPerformance.topNLabel')} defaultValue="15" type="number" />
          </div>
        </CardBody>
      </Card>

      {/* ── Performance des classes d'actifs (univers de classes d'actifs) — pas de Top N ── */}
      <Card style={{ marginBottom: '1.5rem' }}>
        <CardTitle>{t('sectorPerformance.sectionTitle')}</CardTitle>
        <CardBody>
          <p style={{ fontSize: '0.85rem', color: '#6A6E73', marginBottom: '1rem' }}>
            {t('sectorPerformance.sectionDescription')}
          </p>
          <SectorManager />
        </CardBody>
      </Card>

      {/* ── Premium action (univers de pays pour la prime de risque des actions) ── */}
      <Card style={{ marginBottom: '1.5rem' }}>
        <CardTitle>{t('equityPremium.sectionTitle')}</CardTitle>
        <CardBody>
          <p style={{ fontSize: '0.85rem', color: '#6A6E73', marginBottom: '1rem' }}>
            {t('equityPremium.sectionDescription')}
          </p>
          <EquityPremiumManager />
        </CardBody>
      </Card>
    </PageSection>
  );
}
