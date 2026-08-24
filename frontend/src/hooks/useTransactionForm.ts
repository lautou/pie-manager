// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useMemo, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  useBrokers,
  useProducts,
  useTransactions,
  useCreateTransaction,
  useUpdateTransaction,
} from '../api/queries';
import type { Transaction } from '../types';
import { computeCommission, TTF_RATE, isWeekendNewYork, computeMonthlyLimitFXCommission } from '../utils/commission';
import { localDateStr } from '../utils/format';
import { LIQUIDITE_TICKER } from '../utils/transactionConstants';

export interface ExecutionRow {
  date: string;
  quantity: number;
  unit_price: number;
  exchange_rate: number;
}

export interface FormState {
  date: string;
  account_id: string;
  type: string;
  ticker: string;
  currency: string;
  exchange_rate: number;
  quantity: number;
  unit_price: number;
  linked_transaction_id: number | null;
  courtage_eur: number;
  ttf_eur: number;
  fractional_order: boolean;
  additional_executions: ExecutionRow[];
}

export const emptyForm = (): FormState => ({
  date: localDateStr(),
  account_id: '',
  type: 'Actif',
  ticker: '',
  currency: '',
  exchange_rate: 1.0,
  quantity: 0,
  unit_price: 0,
  linked_transaction_id: null,
  courtage_eur: 0,
  ttf_eur: 0,
  fractional_order: false,
  additional_executions: [],
});

export const defaultExecRow = (f: FormState): ExecutionRow => ({
  /* v8 ignore next -- @preserve */
  date: f.date || localDateStr(),
  quantity: 0,
  unit_price: f.unit_price,
  exchange_rate: f.exchange_rate,
});

// All non-JSX state, effects, and handlers backing TransactionModal
// (frontend/src/pages/TransactionsPage.tsx) — extracted so the modal's own
// function only deals with markup, not the form logic driving it.
export function useTransactionForm(
  isOpen: boolean,
  portfolioId: string,
  editingTx: Transaction | null,
  linkedFees: Transaction[],
  onClose: () => void,
) {
  const { t } = useTranslation();
  const { data: accounts = [] } = useBrokers(portfolioId);  // accounts = brokers for this portfolio
  const { data: products = [] } = useProducts();

  const createMutation = useCreateTransaction();
  const updateMutation = useUpdateTransaction();

  const isEditing = editingTx !== null;
  const mutation = isEditing ? updateMutation : createMutation;

  // For Frais type: "flatFee" = fixed amount (qty=-1, price=amount)
  // "per unit" = proportional (qty=N, price=unit_rate)
  // When editing, detect the convention from the existing transaction
  const [flatFee, setFlatFee] = useState<boolean>(() => {
    if (editingTx?.type === 'Frais') return editingTx.quantity === -1;
    return true; // default to flatFee for new Frais transactions
  });

  // Deposit/Withdrawal toggle: used when the selected product is a direct cash
  // account in the same currency as the brokerage account (e.g. LIQUIDITE.EURO
  // on a EUR account). Agnostic to currency — works for any cash product.
  const [direction, setDirection] = useState<'deposit' | 'withdrawal'>('deposit');

  // Achat/Vente/Attribution toggle for Actif type — user enters absolute quantity, sign applied on submit
  const [operationType, setOperationType] = useState<'buy' | 'sell' | 'grant'>(() => {
    /* v8 ignore next -- @preserve */
    if (editingTx?.operation === 'Attribution') return 'grant';
    /* v8 ignore next -- @preserve */
    return editingTx?.type === 'Actif' && editingTx.ticker !== LIQUIDITE_TICKER && (editingTx.quantity ?? 0) > 0 ? 'sell' : 'buy';
  });

  // Helper: is the editing tx a deposit/withdrawal (LIQUIDITE.EURO Actif)?
  const isDepotRetrait = (tx: Transaction | null) =>
    tx?.type === 'Actif' && tx?.ticker === LIQUIDITE_TICKER;

  // Pre-fill courtage/TTF from existing linked Frais amounts
  const initFees = (frais: Transaction[]) => {
    const amounts = frais.map(f => Math.abs(f.total_amount_eur)).sort((a, b) => a - b);
    return { courtage_eur: amounts[0] ?? 0, ttf_eur: amounts[1] ?? 0 };
  };

  const [form, setForm] = useState<FormState>(() => {
    if (editingTx) {
      return {
        date: editingTx.date,
        account_id: String(editingTx.account_id),
        type: isDepotRetrait(editingTx) ? 'Dépôt/Retrait' : editingTx.type,
        ticker: editingTx.ticker,
        currency: editingTx.currency,
        exchange_rate: editingTx.exchange_rate,
        quantity: Math.abs(editingTx.quantity),
        unit_price: editingTx.unit_price,
        linked_transaction_id: editingTx.linked_transaction_id,
        ...initFees(linkedFees),
        fractional_order: false,
        additional_executions: [],
      };
    }
    return emptyForm();
  });

  const [error, setError] = useState<string | null>(null);

  // Reset form whenever modal opens or editingTx changes
  useEffect(() => {
    /* v8 ignore next -- @preserve */
    if (!isOpen) return;
    setError(null);
    if (editingTx) {
      const product = products.find((p) => p.ticker === editingTx.ticker);
      const account = accounts.find((a) => a.id === editingTx.account_id);
      const isCashDirect = product?.instrument_type === 'Cash' && product?.currency === account?.currency;
      setDirection(isCashDirect && editingTx.quantity < 0 ? 'withdrawal' : 'deposit');
      setOperationType(
        editingTx.operation === 'Attribution' ? 'grant'
          : editingTx.type === 'Actif' && editingTx.ticker !== LIQUIDITE_TICKER && editingTx.quantity > 0 ? 'sell' : 'buy'
      );
      setForm({
        date: editingTx.date,
        account_id: String(editingTx.account_id),
        type: isDepotRetrait(editingTx) ? 'Dépôt/Retrait' : editingTx.type,
        ticker: editingTx.ticker,
        currency: editingTx.currency,
        exchange_rate: editingTx.exchange_rate,
        quantity: Math.abs(editingTx.quantity),
        unit_price: editingTx.unit_price,
        linked_transaction_id: editingTx.linked_transaction_id,
        ...initFees(linkedFees),
        fractional_order: false,
        additional_executions: [],
      });
    } else {
      setDirection('deposit');
      setOperationType('buy');
      setForm(emptyForm());
    }
  }, [isOpen, editingTx]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-compute courtage + TTF on total amount (all executions combined)
  const recomputeFees = useCallback((
    qty: number,
    price: number,
    rate: number,
    opType: 'buy' | 'sell' | 'grant',
    accId: string,
    type: string,
    ticker: string,
    extraExecs: ExecutionRow[],
  ) => {
    // A free share grant never incurs brokerage or TTF — skip auto-calculation
    // entirely so a manually-entered fair-value price doesn't produce a
    // spurious courtage estimate (the inputs stay locked at 0 either way).
    if (type !== 'Actif' || opType === 'grant') return;
    const firstAmount = Math.abs(qty * price * rate);
    const extraAmount = extraExecs.reduce(
      (sum, e) => sum + Math.abs(e.quantity * e.unit_price * rate), 0
    );
    const amount = firstAmount + extraAmount;
    if (amount === 0) return;
    const account = accounts.find((a) => a.id === Number(accId));
    const product = products.find((p) => p.ticker === ticker);
    const newCourtage = account?.commission_schedule
      ? Math.round(computeCommission(amount, account.commission_schedule) * 100) / 100
      : 0;
    const newTTF = opType === 'buy' && product?.is_ttf_eligible
      ? Math.round(amount * TTF_RATE * 100) / 100
      : 0;
    setForm((prev) => ({ ...prev, courtage_eur: newCourtage, ttf_eur: newTTF }));
  }, [accounts, products]);

  // Do not recalculate in edit mode (fees are managed via initFees)
  // and never for a fractional sibling (it has no fees of its own)
  const isFractionalTx = isEditing && (
    !!editingTx?.fractional_parent_id || linkedFees.length === 0 && !!editingTx?.fractional_parent_id
  );
  useEffect(() => {
    if (isEditing || isFractionalTx) return;
    recomputeFees(form.quantity, form.unit_price, form.exchange_rate,
      operationType, form.account_id, form.type, form.ticker, form.additional_executions);
  }, [form.quantity, form.unit_price, form.exchange_rate, operationType,
      form.account_id, form.type, form.ticker, form.additional_executions]); // eslint-disable-line react-hooks/exhaustive-deps

  // Selected product and account info — declared early (used by fees and filteredProducts)
  const selectedProduct = useMemo(
    () => products.find((p) => p.ticker === form.ticker) ?? null,
    [products, form.ticker]
  );
  const selectedAccount = useMemo(
    () => accounts.find((a) => a.id === Number(form.account_id)) ?? null,
    [accounts, form.account_id]
  );

  // Auto-detect withdrawal fee: query this month's LIQUIDITE.EURO retraits for the account
  const currentMonthStart = localDateStr().slice(0, 7) + '-01';
  const isRetrait = form.type === 'Dépôt/Retrait' && direction === 'withdrawal';
  const { data: monthWithdrawals = [] } = useTransactions(
    portfolioId,
    { account_id: form.account_id ? Number(form.account_id) : undefined,
      ticker: LIQUIDITE_TICKER, date_from: currentMonthStart },
    { enabled: isRetrait && !!form.account_id }
  );

  // Auto-fill retrait fee when conditions change
  useEffect(() => {
    if (!isRetrait || !selectedAccount) return;
    /* v8 ignore next -- @preserve */
    const feeStd = selectedAccount.withdrawal_fee_eur;
    /* v8 ignore next -- @preserve */
    const firstFree = selectedAccount.withdrawal_first_free;
    /* v8 ignore next -- @preserve */
    const withdrawalsThisMonth = monthWithdrawals.filter(
    /* v8 ignore next -- @preserve */
      tx => tx.account_id === Number(form.account_id) && tx.quantity < 0
    ).length;
    const fee = firstFree && withdrawalsThisMonth === 0 ? 0 : feeStd;
    setForm(prev => ({ ...prev, courtage_eur: fee }));
  }, [isRetrait, form.account_id, monthWithdrawals, selectedAccount]); // eslint-disable-line react-hooks/exhaustive-deps

  // Generic monthly-limit FX: any account with monthly_free_eur set + forex ticker
  const isRevolutFX = (selectedAccount?.monthly_free_eur ?? null) !== null && form.ticker === 'JPYEUR=X';
  const { data: monthFXTxs = [] } = useTransactions(
    portfolioId,
    { account_id: form.account_id ? Number(form.account_id) : undefined,
      ticker: 'JPYEUR=X', date_from: currentMonthStart },
    { enabled: isRevolutFX && !!form.account_id }
  );

  // Auto-fill Revolut FX commission
  useEffect(() => {
    if (!isRevolutFX) return;
    // In edit mode, only auto-fill if fees were already recorded for this transaction.
    // Otherwise the original "no fees" state would be silently overridden.
    if (isEditing && linkedFees.length === 0) return;
    /* v8 ignore next -- @preserve */
    const amount = Math.abs(form.quantity * form.unit_price * form.exchange_rate);
    /* v8 ignore next -- @preserve */
    if (amount === 0) return;
    // Previous volume this month (excluding any editing tx)
    /* v8 ignore next -- @preserve */
    const prevVolume = monthFXTxs
    /* v8 ignore next -- @preserve */
      .filter(tx => !editingTx || tx.id !== editingTx.id)
    /* v8 ignore next -- @preserve */
      .reduce((sum, tx) => sum + Math.abs(tx.total_amount_eur), 0);
    /* v8 ignore next -- @preserve */
    const weekend = isWeekendNewYork();
    /* v8 ignore next -- @preserve */
    const fee = computeMonthlyLimitFXCommission(
    /* v8 ignore next -- @preserve */
      amount, prevVolume, weekend,
    /* v8 ignore next -- @preserve */
      selectedAccount?.monthly_free_eur ?? 0,
    /* v8 ignore next -- @preserve */
      selectedAccount?.above_monthly_rate ?? 0.01,
    /* v8 ignore next -- @preserve */
      selectedAccount?.weekend_rate ?? null,
    );
    /* v8 ignore next -- @preserve */
    setForm(prev => ({ ...prev, courtage_eur: fee }));
  }, [isRevolutFX, form.quantity, form.unit_price, form.exchange_rate, monthFXTxs]); // eslint-disable-line react-hooks/exhaustive-deps

  // Derived: products filtered by type and by account whitelist
  const filteredProducts = useMemo(() => {
    if (form.type === 'Dépôt/Retrait') return []; // ticker auto-set, no dropdown needed
    const allowed = selectedAccount?.allowed_tickers ?? null;
    const byType = form.type === 'Frais'
      ? products.filter((p) => p.category === 'Frais')
      : products.filter((p) => p.category !== 'Frais' && p.ticker !== LIQUIDITE_TICKER);
    if (!allowed) return byType;
    const allowedSet = new Set(allowed);
    return byType.filter((p) => allowedSet.has(p.ticker));
  }, [products, form.type, selectedAccount]);

  const isCash = selectedProduct?.instrument_type === 'Cash';
  // Show Deposit/Withdrawal toggle when the cash product's currency matches the
  // account currency — i.e. it's a direct account balance movement, not a
  // forex position (e.g. JPYEUR=X on an EUR account is NOT isCashDirectDeposit).
  const isCashDirectDeposit = isCash && selectedProduct?.currency === selectedAccount?.currency;
  const isEurCurrency = form.currency === 'EUR';
  // Devise locked when a product with a known currency is selected
  const isCurrencyLocked = !!selectedProduct?.currency;

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleTypeChange = (_event: React.FormEvent, value: string) => {
    if (value === 'Dépôt/Retrait') {
      setDirection('deposit');
      setForm((prev) => ({
        ...prev, type: value,
        ticker: LIQUIDITE_TICKER, currency: 'EUR', exchange_rate: 1.0,
        unit_price: 1.0, courtage_eur: 0, ttf_eur: 0,
      }));
    } else {
      setForm((prev) => ({ ...prev, type: value, ticker: '', currency: '', unit_price: 0, courtage_eur: 0, ttf_eur: 0 }));
      if (value === 'Frais') setFlatFee(true);
      if (value === 'Actif') setOperationType('buy');
    }
  };

  const handleTickerChange = (_event: React.FormEvent, value: string) => {
    /* v8 ignore next -- @preserve */
    const product = products.find((p) => p.ticker === value) ?? null;
    // For forex positions (JPYEUR=X, USDEUR=X…), the held currency is the foreign
    // one (JPY, USD), not the product's stored currency (EUR).
    const forexMatch = value.match(/^([A-Z]{3})[A-Z]{3}=X$/);
    /* v8 ignore next -- @preserve */
    const firstCurrency = forexMatch ? forexMatch[1] : (product?.currency ?? '');
    setDirection('deposit');
    setForm((prev) => ({
      ...prev,
      ticker: value,
      currency: firstCurrency,
      exchange_rate: firstCurrency === 'EUR' ? 1.0 : prev.exchange_rate,
      unit_price: product?.instrument_type === 'Cash' ? 1.0 : prev.unit_price,
    }));
  };

  const handleCurrencyChange = (_event: React.FormEvent<HTMLInputElement>, value: string) => {
    setForm((prev) => ({
      ...prev,
      currency: value,
      exchange_rate: value === 'EUR' ? 1.0 : prev.exchange_rate,
    }));
  };

  const handleSubmit = async () => {
    setError(null);
    try {
      // Deposit/Withdrawal (direct cash) → sign driven by direction toggle
      // Frais  → quantity always negative
      // Revenu → quantity always positive
      // Actif  → sign determined by Buy/Sell/Grant toggle (Buy and Grant both negative)
      // Forex Cash → user controls sign (inverted convention)
      const isDepotRetraitType = form.type === 'Dépôt/Retrait';
      const normalizedQty = isDepotRetraitType
        ? (direction === 'deposit'
            ? Math.abs(form.quantity)
            /* v8 ignore next -- @preserve */
            : -Math.abs(form.quantity))
        /* v8 ignore start -- @preserve */
        : isCashDirectDeposit
        ? (direction === 'deposit'
            ? Math.abs(form.quantity)
            : -Math.abs(form.quantity))
        /* v8 ignore stop -- @preserve */
        : form.type === 'Frais'
          ? flatFee
            ? -1
            : -Math.abs(form.quantity)
          : form.type === 'Revenu'
          ? Math.abs(form.quantity)
          : form.type === 'Actif'
          ? (operationType === 'sell' ? Math.abs(form.quantity) : -Math.abs(form.quantity))
          : /* v8 ignore next -- @preserve */ form.quantity;

      const dbType = isDepotRetraitType ? 'Actif' : form.type;
      const dbTicker = isDepotRetraitType ? LIQUIDITE_TICKER : form.ticker;
      const withdrawalFee = isDepotRetraitType && direction === 'withdrawal' ? form.courtage_eur : 0;
      // Achat/Vente/Attribution only applies to real financial instruments (not
      // cash direct movements or Dépôt/Retrait, which use the direction toggle)
      const operation = form.type === 'Actif' && !isCashDirectDeposit
        ? (operationType === 'sell' ? 'Vente' : operationType === 'grant' ? 'Attribution' : 'Achat')
        : undefined;

      const payload = {
        portfolio_id: Number(portfolioId),
        account_id: Number(form.account_id),
        date: form.date,
        type: dbType,
        ticker: dbTicker,
        currency: isDepotRetraitType ? (selectedAccount?.currency || 'EUR') : form.currency,
        exchange_rate: form.exchange_rate,
        quantity: normalizedQty,
        unit_price: isDepotRetraitType ? 1.0 : form.unit_price,
        linked_transaction_id: form.linked_transaction_id,
        operation,
        // Never send courtage/ttf for fractional transactions (parent with siblings or sibling)
        courtage_eur: isDepotRetraitType ? withdrawalFee
          : (form.type === 'Actif' && !editingTx?.fractional_parent_id ? form.courtage_eur : 0),
        ttf_eur: form.type === 'Actif' && operationType === 'buy' && !editingTx?.fractional_parent_id
          ? form.ttf_eur : 0,
        additional_executions: form.type === 'Actif' && form.fractional_order && !isEditing
          ? form.additional_executions.map(e => ({
              date: e.date,
              quantity: operationType === 'sell' ? Math.abs(e.quantity) : -Math.abs(e.quantity),
              unit_price: e.unit_price,
              /* v8 ignore next -- @preserve */
              exchange_rate: e.exchange_rate || form.exchange_rate,
            }))
          : [],
      };
      if (isEditing && editingTx) {
        await updateMutation.mutateAsync({ id: editingTx.id, ...payload });
      } else {
        await createMutation.mutateAsync(payload);
      }
      onClose();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t('error.generic')
      );
    }
  };

  const isLoading = mutation.isPending;

  return {
    form, setForm, setField, error, isEditing, isLoading,
    accounts, selectedAccount, filteredProducts,
    flatFee, setFlatFee,
    direction, setDirection,
    operationType, setOperationType,
    isCash, isCashDirectDeposit, isEurCurrency, isCurrencyLocked, isRevolutFX,
    monthWithdrawals, monthFXTxs,
    handleTypeChange, handleTickerChange, handleCurrencyChange, handleSubmit,
  };
}
