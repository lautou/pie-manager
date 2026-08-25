// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  Card, CardBody, CardTitle,
  PageSection, PageSectionVariants,
  Content, ContentVariants, Title,
} from '@patternfly/react-core';
import { CogIcon, PlusCircleIcon } from '@patternfly/react-icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  usePools, usePoolProducts, useProducts, useAllBrokers,
  createPool, updatePool, deletePool, addTickerToPool, removeTickerFromPool,
  updateBrokerPortfoliosAPI,
} from '../api/queries';
import type { Pool, Broker } from '../types';
import { useSortable } from '../hooks/useSortable';
import ConfirmModal from '../components/ConfirmModal';

// ── Pool Management sub-component ─────────────────────────────────────────

function PoolManager({ portfolioId }: { portfolioId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: pools = [], refetch: refetchPools } = usePools(portfolioId);
  const { data: products = [] } = useProducts();
  const [selectedPool, setSelectedPool] = useState<Pool | null>(null);
  const { data: poolProducts = [], refetch: refetchProducts } = usePoolProducts(selectedPool?.id ?? null);

  // Sortable pools table
  const { sorted: sortedPools, toggle: togglePool, indicator: poolInd, thStyle: poolTh } =
    useSortable<Pool, keyof Pool>({
      data: pools, defaultCol: 'name',
      /* v8 ignore next -- @preserve */
      getValue: (p, col) => col === 'target_pct' ? p.target_pct : col === 'is_active' ? (p.is_active ? 1 : 0) : String(p[col] ?? ''),
    });

  // Pool form state
  const [editingPool, setEditingPool] = useState<Pool | null>(null);
  const [newName, setNewName] = useState('');
  const [newStrategy, setNewStrategy] = useState<'Offensive' | 'Defensive'>('Offensive');
  const [newTarget, setNewTarget] = useState('25');
  const [newColor, setNewColor] = useState('#1890FF');
  const [poolError, setPoolError] = useState('');

  // Ticker search
  const [tickerSearch, setTickerSearch] = useState('');
  const [poolDeleteTarget, setPoolDeleteTarget] = useState<Pool | null>(null);
  const [isDeletingPool, setIsDeletingPool] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const openNew = () => {
    setEditingPool({ id: 0, portfolio_id: Number(portfolioId), name: '', strategy: 'Offensive', target_pct: 0.25, is_active: true, color: null });
    setNewName(''); setNewStrategy('Offensive'); setNewTarget('25'); setNewColor('#1890FF'); setPoolError('');
  };
  const openEdit = (p: Pool) => {
    setEditingPool(p);
    setNewName(p.name); setNewStrategy(p.strategy as 'Offensive' | 'Defensive');
    setNewTarget(String(Math.round(p.target_pct * 100))); setNewColor(p.color ?? '#1890FF'); setPoolError('');
  };
  const cancelEdit = () => { setEditingPool(null); setPoolError(''); };

  const savePool = async () => {
    if (!newName.trim()) { setPoolError(t('pools.nameRequired')); return; }
    const pct = parseFloat(newTarget) / 100;
    if (isNaN(pct) || pct <= 0 || pct > 1) { setPoolError(t('pools.invalidTarget')); return; }
    try {
      if (editingPool!.id === 0) {
        await createPool({ portfolio_id: Number(portfolioId), name: newName.trim(), strategy: newStrategy, target_pct: pct, is_active: true, color: newColor });
      } else {
        await updatePool(editingPool!.id, { name: newName.trim(), strategy: newStrategy, target_pct: pct, color: newColor });
      }
      setEditingPool(null); setPoolError('');
      refetchPools(); qc.invalidateQueries({ queryKey: ['pools'] });
    } catch (e: any) { setPoolError(e?.response?.data?.detail ?? t('error.saveFailed')); }
  };

  const handleDelete = (p: Pool) => {
    setPoolDeleteTarget(p);
  };

  const handleConfirmDeletePool = async () => {
    /* v8 ignore next -- @preserve */
    if (!poolDeleteTarget) return;
    setIsDeletingPool(true);
    try {
      await deletePool(poolDeleteTarget.id);
      if (selectedPool?.id === poolDeleteTarget.id) setSelectedPool(null);
      refetchPools();
      setPoolDeleteTarget(null);
      setActionError(null);
    } catch (e: any) { setActionError(e?.response?.data?.detail ?? t('error.deleteFailed')); }
    finally { setIsDeletingPool(false); }
  };

  const handleAddTicker = async (ticker: string) => {
    /* v8 ignore next -- @preserve */
    if (!selectedPool) return;
    try { await addTickerToPool(selectedPool.id, ticker); refetchProducts(); setTickerSearch(''); setActionError(null); }
    catch (e: any) { setActionError(e?.response?.data?.detail ?? t('error.saveFailed')); }
  };

  const handleRemoveTicker = async (ticker: string) => {
    /* v8 ignore next -- @preserve */
    if (!selectedPool) return;
    await removeTickerFromPool(selectedPool.id, ticker); refetchProducts();
  };

  const assignedTickers = new Set(poolProducts.map(pp => pp.ticker));
  const availableProducts = products.filter(p =>
    !assignedTickers.has(p.ticker) &&
    (tickerSearch === '' || p.ticker.toLowerCase().includes(tickerSearch.toLowerCase()) || p.name.toLowerCase().includes(tickerSearch.toLowerCase()))
  ).slice(0, 10);

  const inputStyle: React.CSSProperties = { padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc', fontSize: '0.9rem' };
  const btnSm = (extra?: React.CSSProperties): React.CSSProperties => ({ padding: '3px 10px', borderRadius: 4, cursor: 'pointer', fontSize: '0.8rem', ...extra });

  return (
    <div>
      {actionError && (
        <Alert variant="danger" isInline title={actionError} style={{ marginBottom: '0.75rem' }} />
      )}

      {/* Pool list */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
        <span style={{ fontSize: '0.85rem', color: '#6A6E73' }}>{pools.length} pool(s)</span>
        <Button variant="primary" icon={<PlusCircleIcon />} size="sm" onClick={openNew}>{t('pools.newPool')}</Button>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem', marginBottom: '1rem' }}>
        <thead>
          <tr style={{ background: '#f5f5f5' }}>
            <th style={poolTh('name')} onClick={() => togglePool('name')}>{t('pools.fields.name')}{poolInd('name')}</th>
            <th style={poolTh('strategy')} onClick={() => togglePool('strategy')}>{t('pools.fields.strategy')}{poolInd('strategy')}</th>
            <th style={poolTh('target_pct')} onClick={() => togglePool('target_pct')}>{t('pools.fields.target')}{poolInd('target_pct')}</th>
            <th style={poolTh('is_active')} onClick={() => togglePool('is_active')}>{t('pools.fields.active')}{poolInd('is_active')}</th>
            <th style={{ padding: '6px 8px', borderBottom: '1px solid #ddd' }}></th>
          </tr>
        </thead>
        <tbody>
          {sortedPools.map((p) => (
            <tr key={p.id} onClick={() => setSelectedPool(selectedPool?.id === p.id ? null : p)}
              style={{ cursor: 'pointer', background: selectedPool?.id === p.id ? '#E8F0FE' : 'transparent', borderBottom: '1px solid #eee' }}>
              <td style={{ padding: '6px 8px', fontWeight: 500 }}>
                <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
                  backgroundColor: p.color ?? '#6A6E73', marginRight: 6, verticalAlign: 'middle' }} />
                {p.name}
              </td>
              <td style={{ padding: '6px 8px' }}>
                <span style={{ padding: '2px 8px', borderRadius: 12, fontSize: '0.78rem',
                  background: p.strategy === 'Offensive' ? '#E8F4FD' : '#E6F4EA',
                  color: p.strategy === 'Offensive' ? '#0066CC' : '#137333' }}>{p.strategy}</span>
              </td>
              <td style={{ padding: '6px 8px' }}>{Math.round(p.target_pct * 100)}%</td>
              <td style={{ padding: '6px 8px' }}>{p.is_active ? '✅' : '⏸️'}</td>
              <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }} onClick={e => e.stopPropagation()}>
                <button style={btnSm({ marginRight: 4, background: '#f5f5f5', border: '1px solid #ccc' })} onClick={() => openEdit(p)}>✏️</button>
                <button style={btnSm({ background: '#FAEAE8', border: '1px solid #C9190B', color: '#C9190B' })} onClick={() => handleDelete(p)}>🗑</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Inline pool form */}
      {editingPool && (
        <div style={{ padding: '1rem', background: '#f9f9f9', border: '1px solid #ddd', borderRadius: 6, marginBottom: '1rem' }}>
          <strong style={{ fontSize: '0.9rem' }}>{editingPool.id === 0 ? t('pools.newPool') : `${t('pools.editPool')} — ${editingPool.name}`}</strong>
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginTop: '0.75rem', alignItems: 'flex-end' }}>
            <div><label style={{ fontSize: '0.8rem', display: 'block', marginBottom: 2 }}>{t('pools.fields.name')}</label>
              <input value={newName} onChange={e => setNewName(e.target.value)} style={{ ...inputStyle, width: 160 }} /></div>
            <div><label style={{ fontSize: '0.8rem', display: 'block', marginBottom: 2 }}>{t('pools.fields.strategy')}</label>
              <select value={newStrategy} onChange={e => setNewStrategy(e.target.value as 'Offensive' | 'Defensive')} style={inputStyle}>
                <option value="Offensive">Offensive</option>
                <option value="Defensive">Defensive</option>
              </select></div>
            <div><label style={{ fontSize: '0.8rem', display: 'block', marginBottom: 2 }}>{t('pools.fields.target')}</label>
              <input type="number" value={newTarget} onChange={e => setNewTarget(e.target.value)} style={{ ...inputStyle, width: 70 }} min={1} max={100} /></div>
            <div><label style={{ fontSize: '0.8rem', display: 'block', marginBottom: 2 }}>{t('pools.fields.color')}</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <input type="color" value={newColor} onChange={e => setNewColor(e.target.value)}
                  style={{ width: 32, height: 28, border: 'none', padding: 0, cursor: 'pointer', borderRadius: 4 }} />
                <span style={{ fontSize: '0.75rem', color: '#6A6E73', fontFamily: 'monospace' }}>{newColor}</span>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.4rem' }}>
              <Button variant="primary" size="sm" onClick={savePool}>{t('common.save')}</Button>
              <Button variant="secondary" size="sm" onClick={cancelEdit}>{t('common.cancel')}</Button>
            </div>
          </div>
          {poolError && <div style={{ color: '#C9190B', fontSize: '0.8rem', marginTop: '0.5rem' }}>{poolError}</div>}
        </div>
      )}

      {/* Pool tickers panel */}
      {selectedPool && (
        <div style={{ border: '1px solid #0066CC', borderRadius: 6, padding: '1rem', marginTop: '0.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
            <strong style={{ fontSize: '0.9rem' }}>{t('admin.poolAssetsTitle', { name: selectedPool.name })}</strong>
            <button onClick={() => setSelectedPool(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1rem' }}>✕</button>
          </div>

          {/* Current tickers */}
          {poolProducts.length === 0
            ? <p style={{ fontSize: '0.85rem', color: '#6A6E73' }}>{t('dashboard.noPositionInPool')}</p>
            : <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '0.75rem' }}>
                {poolProducts.map(pp => (
                  <span key={pp.ticker} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '3px 8px',
                    background: '#f0f0f0', borderRadius: 12, fontSize: '0.82rem', border: '1px solid #ddd' }}>
                    {pp.ticker}
                    <button onClick={() => handleRemoveTicker(pp.ticker)}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: '#C9190B', lineHeight: 1 }}>×</button>
                  </span>
                ))}
              </div>
          }

          {/* Add ticker search */}
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.5rem' }}>
            <input placeholder={t('pools.searchTicker')} value={tickerSearch} onChange={e => setTickerSearch(e.target.value)}
              style={{ ...inputStyle, flex: 1 }} />
          </div>
          {tickerSearch && availableProducts.length > 0 && (
            <div style={{ border: '1px solid #ddd', borderRadius: 4, maxHeight: 200, overflowY: 'auto' }}>
              {availableProducts.map(p => (
                <div key={p.ticker} onClick={() => handleAddTicker(p.ticker)}
                  style={{ padding: '6px 10px', cursor: 'pointer', fontSize: '0.85rem',
                    display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid #f0f0f0' }}
                  onMouseEnter={e => (e.currentTarget.style.background = '#f5f5f5')}
                  onMouseLeave={e => (e.currentTarget.style.background = '')}>
                  <span><strong>{p.ticker}</strong> — {p.name}</span>
                  <span style={{ color: '#0066CC', fontSize: '0.8rem' }}>+ {t('pools.addTicker')}</span>
                </div>
              ))}
            </div>
          )}
          {tickerSearch && availableProducts.length === 0 && (
            <p style={{ fontSize: '0.82rem', color: '#6A6E73' }}>{t('admin.noAvailableAssets', { search: tickerSearch })}</p>
          )}
        </div>
      )}

      <ConfirmModal
        isOpen={!!poolDeleteTarget}
        title={t('common.confirmDeleteTitle')}
        message={poolDeleteTarget ? t('pools.deleteConfirm', { name: poolDeleteTarget.name }) : ''}
        isLoading={isDeletingPool}
        onConfirm={handleConfirmDeletePool}
        onCancel={() => setPoolDeleteTarget(null)}
      />
    </div>
  );
}

// ── Commission Manager sub-component ─────────────────────────────────────


// ── Account assignment for this portfolio ──────────────────────────────────

function AccountAssignmentManager({ portfolioId }: { portfolioId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data: allAccounts = [], isLoading } = useAllBrokers();
  const pid = Number(portfolioId);
  const [saving, setSaving] = useState<number | null>(null);

  const isAssigned = (acc: Broker) => acc.portfolio_ids.includes(pid);

  const toggle = async (acc: Broker) => {
    setSaving(acc.id);
    const newIds = isAssigned(acc)
      ? acc.portfolio_ids.filter(x => x !== pid)
      : [...acc.portfolio_ids, pid];
    try {
      await updateBrokerPortfoliosAPI(acc.id, newIds);
      qc.invalidateQueries({ queryKey: ['accounts'] });
    } finally {
      setSaving(null);
    }
  };

  if (isLoading) return <span style={{ color: '#6A6E73' }}>{t('common.loading')}</span>;
  if (allAccounts.length === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <span style={{ color: '#6A6E73' }}>{t('common.none')}</span>
        <Button variant="link" isInline icon={<CogIcon />}
          onClick={() => navigate(`/config?from=${portfolioId}`)}>
          {t('nav.globalConfig')}
        </Button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
      {allAccounts.map(acc => (
        <label key={acc.id} style={{
          display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px',
          border: `1px solid ${isAssigned(acc) ? '#0066CC' : '#ccc'}`,
          borderRadius: 6, cursor: 'pointer', fontSize: '0.9rem',
          background: isAssigned(acc) ? '#E7F3FF' : '#fafafa',
          opacity: saving === acc.id ? 0.6 : 1,
        }}>
          <input
            type="checkbox"
            checked={isAssigned(acc)}
            disabled={saving === acc.id}
            onChange={() => toggle(acc)}
          />
          <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
            backgroundColor: acc.color ?? '#6A6E73', marginRight: 2 }} />
          {acc.name}
          <span style={{ fontSize: '0.75rem', color: '#6A6E73', fontFamily: 'monospace' }}>
            {acc.currency}
          </span>
        </label>
      ))}
    </div>
  );
}

// ── Admin page ─────────────────────────────────────────────────────────────

export default function AdminPage() {
  const { t } = useTranslation();
  const { portfolioId: _portfolioId } = useParams<{ portfolioId: string }>();

  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
      <Title headingLevel="h1" size="xl" style={{ marginBottom: '1.5rem' }}>
        {t('admin.title')}
      </Title>

      {/* ── Comptes assignés à ce portefeuille ── */}
      <Card style={{ maxWidth: 900, marginBottom: '1.5rem' }}>
        <CardTitle>{t('admin.assignedAccounts')}</CardTitle>
        <CardBody>
          <Content style={{ marginBottom: '1rem' }}>
            <Content component={ContentVariants.p}>
              {t('admin.assignedAccountsDesc')}
            </Content>
          </Content>
          <AccountAssignmentManager portfolioId={_portfolioId!} />
        </CardBody>
      </Card>

      {/* ── Gestion des pools ── */}
      <Card style={{ maxWidth: 900, marginBottom: '1.5rem' }}>
        <CardTitle>{t('admin.poolManagement')}</CardTitle>
        <CardBody>
          <Content style={{ marginBottom: '1rem' }}>
            <Content component={ContentVariants.p}>
              {t('admin.poolManagementDesc')}
            </Content>
          </Content>
          <PoolManager portfolioId={_portfolioId!} />
        </CardBody>
      </Card>
    </PageSection>
  );
}
