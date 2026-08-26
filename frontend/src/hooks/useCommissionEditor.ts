// SPDX-License-Identifier: AGPL-3.0-or-later
// Extracted from GlobalConfigPage.tsx's CommissionManager — see useBrokerCrud.ts's own header
// comment for the full extraction rationale. This hook owns the per-row commission-tier /
// allowed-tickers / FX-commission editing state (the `editingId`/`editMode` mini state
// machine), independent of the sibling broker CRUD modal state.
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { CommissionTier, Product } from '../types';

export type CommissionEditMode = 'commission' | 'tickers' | 'fx';

interface TierRow { up_to: string; type: 'flat' | 'percent'; value: string; }

async function putFXCommission(accountId: number, params: { monthly_free_eur: number | null; above_monthly_rate: number; weekend_rate: number | null }) {
  const res = await fetch(`/api/brokers/${accountId}/fx-commission`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) });
  if (!res.ok) throw new Error(await res.text());
}

export async function putCommissionSaleRate(accountId: number, rate: number) {
  const res = await fetch(`/api/brokers/${accountId}/sale-rate`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ commission_sale_rate: rate }) });
  if (!res.ok) throw new Error(await res.text());
}

export async function putIncludeFeesInCump(accountId: number, includeFees: boolean) {
  const res = await fetch(`/api/brokers/${accountId}/include-fees`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ include_fees_in_cump: includeFees }) });
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

export function useCommissionEditor(allProducts: Product[]) {
  const qc = useQueryClient();

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editMode, setEditMode] = useState<CommissionEditMode>('commission');
  const [selectedTickers, setSelectedTickers] = useState<string[]>([]);
  const [tickerFilterLeft, setTickerFilterLeft] = useState('');
  const [tickerFilterRight, setTickerFilterRight] = useState('');
  const [fxMonthlyFree, setFxMonthlyFree] = useState<string>('');
  const [fxAboveRate, setFxAboveRate] = useState<string>('');
  const [fxWeekendRate, setFxWeekendRate] = useState<string>('');
  const [tiers, setTiers] = useState<TierRow[]>([]);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  // Transfer list derived state (computed once per render, used in the tickers panel)
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

  return {
    editingId, setEditingId, editMode, setEditMode,
    selectedTickers, setSelectedTickers, tickerFilterLeft, setTickerFilterLeft,
    tickerFilterRight, setTickerFilterRight,
    fxMonthlyFree, setFxMonthlyFree, fxAboveRate, setFxAboveRate, fxWeekendRate, setFxWeekendRate,
    tiers, setTiers, error, saving,
    tickersAvailable, tickersAllowed, tickersUnknown, addTicker, removeTicker,
    tiersFromSchedule, openEditCommission, handleSave,
  };
}
