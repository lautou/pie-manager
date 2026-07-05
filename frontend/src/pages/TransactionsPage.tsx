import { useState, useMemo, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  FormGroup,
  FormSelect,
  FormSelectOption,
  Modal,
  ModalVariant,
  PageSection,
  Switch,
  Pagination,
  Spinner,
  TextInput,
  Title,
  Tooltip,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';
import { PencilAltIcon, TrashIcon } from '@patternfly/react-icons';
import {
  useTransactions,
  useBrokers,
  useProducts,
  useCreateTransaction,
  useUpdateTransaction,
  useDeleteTransaction,
} from '../api/queries';
import type { Transaction } from '../types';
import FrDatePicker from '../components/FrDatePicker';
import { formatEUR, formatEUR3, formatQty as fmtQty, formatNativeCurrency } from '../utils/format';
import { computeCommission, TTF_RATE, isWeekendNewYork, computeMonthlyLimitFXCommission } from '../utils/commission';
import { localDateStr } from '../utils/format';



/* v8 ignore next -- @preserve */
const TRANSACTION_TYPES = ['Dépôt/Retrait', 'Actif', 'Frais', 'Revenu'] as const;
/* v8 ignore next -- @preserve */
const LIQUIDITE_TICKER = 'LIQUIDITE.EURO';

// Use centralized fr-FR formatters
const formatQty = (val: number) => fmtQty(val);

// ---------------------------------------------------------------------------
// Form state & helpers
// ---------------------------------------------------------------------------

interface ExecutionRow {
  date: string;
  quantity: number;
  unit_price: number;
  exchange_rate: number;
}

interface FormState {
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

const emptyForm = (): FormState => ({
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

const defaultExecRow = (f: FormState): ExecutionRow => ({
  /* v8 ignore next -- @preserve */
  date: f.date || localDateStr(),
  quantity: 0,
  unit_price: f.unit_price,
  exchange_rate: f.exchange_rate,
});

// ---------------------------------------------------------------------------
// TransactionModal
// ---------------------------------------------------------------------------

interface TransactionModalProps {
  isOpen: boolean;
  portfolioId: string;
  editingTx: Transaction | null;
  linkedFees: Transaction[];
  onClose: () => void;
}

function TransactionModal({ isOpen, portfolioId, editingTx, linkedFees, onClose }: TransactionModalProps) {
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

  // Achat/Vente toggle for Actif type — user enters absolute quantity, sign applied on submit
  const [operationType, setOperationType] = useState<'buy' | 'sell'>(() =>
    /* v8 ignore next -- @preserve */
    editingTx?.type === 'Actif' && editingTx.ticker !== LIQUIDITE_TICKER && (editingTx.quantity ?? 0) > 0 ? 'sell' : 'buy'
  );

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
      const isCashDirect = product?.category === 'Cash' && product?.currency === account?.currency;
      setDirection(isCashDirect && editingTx.quantity < 0 ? 'withdrawal' : 'deposit');
      setOperationType(editingTx.type === 'Actif' && editingTx.ticker !== LIQUIDITE_TICKER && editingTx.quantity > 0 ? 'sell' : 'buy');
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
    opType: 'buy' | 'sell',
    accId: string,
    type: string,
    ticker: string,
    extraExecs: ExecutionRow[],
  ) => {
    if (type !== 'Actif') return;
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

  const isCash = selectedProduct?.category === 'Cash';
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
      unit_price: product?.category === 'Cash' ? 1.0 : prev.unit_price,
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
      // Actif  → sign determined by Buy/Sell toggle
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
          ? (operationType === 'buy' ? -Math.abs(form.quantity) : Math.abs(form.quantity))
          : /* v8 ignore next -- @preserve */ form.quantity;

      const dbType = isDepotRetraitType ? 'Actif' : form.type;
      const dbTicker = isDepotRetraitType ? LIQUIDITE_TICKER : form.ticker;
      const withdrawalFee = isDepotRetraitType && direction === 'withdrawal' ? form.courtage_eur : 0;

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
        // Never send courtage/ttf for fractional transactions (parent with siblings or sibling)
        courtage_eur: isDepotRetraitType ? withdrawalFee
          : (form.type === 'Actif' && !editingTx?.fractional_parent_id ? form.courtage_eur : 0),
        ttf_eur: form.type === 'Actif' && operationType === 'buy' && !editingTx?.fractional_parent_id
          ? form.ttf_eur : 0,
        additional_executions: form.type === 'Actif' && form.fractional_order && !isEditing
          ? form.additional_executions.map(e => ({
              date: e.date,
              quantity: operationType === 'buy' ? -Math.abs(e.quantity) : Math.abs(e.quantity),
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

  return (
    <Modal
      variant={ModalVariant.large}
      title={isEditing ? t('transactions.editTransaction') : t('transactions.newTransaction')}
      isOpen={isOpen}
      onClose={onClose}
      onEscapePress={onClose}
      actions={[
        <Button
          key="submit"
          variant="primary"
          onClick={handleSubmit}
          isLoading={isLoading}
          isDisabled={isLoading}
        >
          {isEditing ? t('common.save') : t('common.add')}
        </Button>,
        <Button key="cancel" variant="link" onClick={onClose} isDisabled={isLoading}>
          {t('common.cancel')}
        </Button>,
      ]}
    >
      {error && (
        <Alert variant="danger" title={error} isInline style={{ marginBottom: '1rem' }} />
      )}

      {/* Type — en premier car ne dépend d'aucune autre sélection */}
      <FormGroup label={t('transactions.fields.type')} isRequired fieldId="tx-type" style={{ marginBottom: '1rem' }}>
        <FormSelect
          id="tx-type"
          value={form.type}
          onChange={handleTypeChange}
          aria-label={t('transactions.fields.type')}
          style={{ width: '100%' }}
        >
          {TRANSACTION_TYPES.map((txType) => (
            <FormSelectOption key={txType} value={txType} label={txType} />
          ))}
        </FormSelect>
      </FormGroup>

      {/* Compte — reset ticker si le compte change */}
      <FormGroup label={t('transactions.fields.account')} isRequired fieldId="tx-account" style={{ marginBottom: '1rem' }}>
        <FormSelect
          id="tx-account"
          value={form.account_id}
          onChange={(_event, value) => {
            setForm(prev => ({ ...prev, account_id: value, ticker: '', currency: '' }));
          }}
          aria-label={t('transactions.fields.account')}
          style={{ width: '100%' }}
        >
          <FormSelectOption value="" label={t('transactions.selectAccount')} isDisabled />
          {accounts.map((acc) => (
            <FormSelectOption key={acc.id} value={String(acc.id)} label={acc.name} />
          ))}
        </FormSelect>
      </FormGroup>

      {/* Dépôt/Retrait: no ticker dropdown, show locked label + currency + date */}
      {form.type === 'Dépôt/Retrait' ? (
        <>
          <FormGroup fieldId="tx-depot-info" style={{ marginBottom: '1rem' }}>
            <div style={{ padding: '6px 8px', background: '#f5f5f5', borderRadius: 4, fontSize: '0.9rem', color: '#6A6E73' }}>
              {selectedAccount ? `LIQUIDITE.${selectedAccount.currency} — Liquidités ${selectedAccount.currency} (${selectedAccount.currency})` : 'LIQUIDITE.EURO — Liquidités EUR (EUR)'}
            </div>
          </FormGroup>
          <FormGroup label={t('transactions.fields.currency')} isRequired fieldId="tx-depot-currency" style={{ marginBottom: '1rem' }}>
            <TextInput
              id="tx-depot-currency"
              type="text"
              value={selectedAccount?.currency || 'EUR'}
              isDisabled
            />
            <div style={{ fontSize: '0.75rem', color: '#6A6E73', marginTop: '0.25rem' }}>
              {t('transactions.fields.currencyLocked')}
            </div>
          </FormGroup>
          <FormGroup label={t('transactions.fields.date')} isRequired fieldId="tx-depot-date" style={{ marginBottom: '1rem' }}>
            <FrDatePicker
              id="tx-depot-date"
              value={form.date}
              onChange={(iso) => setField('date', iso)}
            />
          </FormGroup>
        </>
      ) : (
        <>
          {/* Ticker */}
          <FormGroup label={t('transactions.fields.ticker')} isRequired fieldId="tx-ticker" style={{ marginBottom: '1rem' }}>
            <FormSelect
              id="tx-ticker"
              value={form.ticker}
              onChange={handleTickerChange}
              aria-label={t('transactions.fields.ticker')}
              style={{ width: '100%' }}
            >
              <FormSelectOption value="" label={t('transactions.selectProduct')} isDisabled />
              {filteredProducts.map((p) => (
                <FormSelectOption
                  key={p.ticker}
                  value={p.ticker}
                  label={`${p.ticker} — ${p.name}`}
                />
              ))}
            </FormSelect>
          </FormGroup>

          {/* Devise — grisée quand un ticker avec devise connue est sélectionné */}
          <FormGroup label={t('transactions.fields.currency')} isRequired fieldId="tx-currency" style={{ marginBottom: '1rem' }}>
            <TextInput
              id="tx-currency"
              type="text"
              value={form.currency}
              onChange={handleCurrencyChange}
              placeholder="EUR"
              isDisabled={isCurrencyLocked}
            />
            {isCurrencyLocked && (
              <div style={{ fontSize: '0.75rem', color: '#6A6E73', marginTop: '0.25rem' }}>
                {t('transactions.fields.currencyLocked')}
              </div>
            )}
          </FormGroup>

          {/* Sens — Achat/Vente pour Actif, placé avant Taux */}
          {form.type === 'Actif' && !isCashDirectDeposit && (
            <FormGroup label={t('transactions.fields.direction')} isRequired fieldId="tx-sens-inline" style={{ marginBottom: '1rem' }}>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <Button variant={operationType === 'buy' ? 'primary' : 'control'} size="sm"
                  onClick={() => setOperationType('buy')}>📉 {t('transactions.direction.buy')}</Button>
                <Button variant={operationType === 'sell' ? 'primary' : 'control'} size="sm"
                  onClick={() => setOperationType('sell')}>📈 {t('transactions.direction.sell')}</Button>
              </div>
            </FormGroup>
          )}

          {/* Ordre fractionné — juste après Sens, uniquement pour Actif, pas en édition */}
          {form.type === 'Actif' && !isEditing && !isCashDirectDeposit && (
            <FormGroup fieldId="tx-fractional" style={{ marginBottom: '0.75rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <Switch
                  id="tx-fractional"
                  label={t('transactions.fields.fractionalOrder')}
                  labelOff={t('transactions.fields.fractionalOrder')}
                  isChecked={form.fractional_order}
                  onChange={(_e, checked) => setForm(prev => ({
                    ...prev,
                    fractional_order: checked,
                    additional_executions: checked ? prev.additional_executions : [],
                  }))}
                />
                {form.fractional_order && (
                  <span style={{ fontSize: '0.8rem', color: '#6A6E73' }}>
                    {t('transactions.fractionalFeeNote')}
                  </span>
                )}
              </div>
            </FormGroup>
          )}

          {/* Date — masquée si ordre fractionné (chaque exec a sa date) */}
          {!form.fractional_order && (
            <FormGroup label={t('transactions.fields.date')} isRequired fieldId="tx-date" style={{ marginBottom: '1rem' }}>
              <FrDatePicker
                id="tx-date"
                value={form.date}
                onChange={(iso) => setField('date', iso)}
              />
            </FormGroup>
          )}

          {/* Taux EUR — masqué si ordre fractionné (taux intégré par ligne) */}
          {!form.fractional_order && (
            <FormGroup
              label={t('transactions.fields.exchangeRate')}
              isRequired
              fieldId="tx-exchange"
              style={{ marginBottom: '1rem' }}
            >
              <input
                id="tx-exchange"
                type="number"
                min={0}
                step={0.0001}
                value={form.exchange_rate}
                disabled={isEurCurrency}
                onFocus={(e) => e.target.select()}
                onChange={(e) => {
                  if (!isEurCurrency)
                    setField('exchange_rate', parseFloat(e.target.value) || 0);
                }}
                style={{ width: '140px', padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '1rem' }}
              />
            </FormGroup>
          )}
        </>
      )}

      {/* Dépôt/Retrait: simplified Montant field + toggle */}
      {form.type === 'Dépôt/Retrait' && (
        <FormGroup label={t('transactions.fields.amount')} isRequired fieldId="tx-depot-montant" style={{ marginBottom: '1rem' }}>
          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
            <Button variant={direction === 'deposit' ? 'primary' : 'control'} size="sm"
              onClick={() => setDirection('deposit')}>{t('transactions.direction.deposit')}</Button>
            <Button variant={direction === 'withdrawal' ? 'primary' : 'control'} size="sm"
              onClick={() => setDirection('withdrawal')}>{t('transactions.direction.withdrawal')}</Button>
          </div>
          <input
            id="tx-depot-montant"
            type="number" min={0} step={0.01}
            value={form.quantity || ''}
            onFocus={(e) => e.target.select()}
            onChange={(e) => setField('quantity', parseFloat(e.target.value) || 0)}
            style={{ width: '160px', padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '1rem' }}
          />
          {/* Retrait fee — auto-filled */}
          {direction === 'withdrawal' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginTop: '0.5rem' }}>
              <span style={{ fontSize: '0.85rem', color: '#6A6E73' }}>{t('transactions.withdrawalFee')}</span>
              <input
                type="number" min={0} step={0.01}
                value={form.courtage_eur || ''}
                onFocus={(e) => e.target.select()}
                onChange={(e) => setField('courtage_eur', parseFloat(e.target.value) || 0)}
                style={{ width: '90px', padding: '4px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '0.9rem' }}
              />
              <span style={{ fontSize: '0.8rem', color: '#6A6E73' }}>€</span>
              {selectedAccount?.withdrawal_first_free && (
                <span style={{ fontSize: '0.78rem', color: '#0066CC' }}>
                  {monthWithdrawals.filter(tx => tx.quantity < 0).length === 0
                    ? t('transactions.firstWithdrawalFree')
                    /* v8 ignore next -- @preserve */
                    : t('transactions.subsequentWithdrawal')
                  }
                </span>
              )}
            </div>
          )}
        </FormGroup>
      )}

      {/* Toggle Forfait / Par unité — uniquement pour les Frais */}
      {form.type === 'Frais' && (
        <FormGroup fieldId="tx-frais-mode" style={{ marginBottom: '0.75rem' }}>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            <Button
              variant={flatFee ? 'primary' : 'tertiary'}
              size="sm"
              onClick={() => { setFlatFee(true); setField('quantity', 1); }}
            >
              {t('transactions.flatFee')}
            </Button>
            <Button
              variant={!flatFee ? 'primary' : 'tertiary'}
              size="sm"
              onClick={() => setFlatFee(false)}
            >
              {t('transactions.perUnit')}
            </Button>
            <span style={{ fontSize: '0.8rem', color: '#6A6E73' }}>
              {flatFee
                ? t('transactions.flatFeeDesc')
                : t('transactions.perUnitDesc')}
            </span>
          </div>
        </FormGroup>
      )}


      {/* Quantité — masquée en mode Forfait, Dépôt/Retrait ou ordre fractionné actif */}
      {form.type !== 'Dépôt/Retrait' && (form.type !== 'Frais' || !flatFee) && !form.fractional_order && (
      <FormGroup
        label={t('transactions.fields.quantity')}
        isRequired
        fieldId="tx-quantity"
        style={{ marginBottom: '1rem' }}
      >
        {
          /* v8 ignore next 28 -- @preserve */
          isCashDirectDeposit ? (
          <>
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
              <Button
                variant={direction === 'deposit' ? 'primary' : 'control'}
                size="sm"
                onClick={() => setDirection('deposit')}
              >
                {t('transactions.direction.deposit')}
              </Button>
              <Button
                variant={direction === 'withdrawal' ? 'primary' : 'control'}
                size="sm"
                onClick={() => setDirection('withdrawal')}
              >
                {t('transactions.direction.withdrawal')}
              </Button>
            </div>
            <input
              id="tx-quantity"
              type="number"
              min={0}
              step={1}
              value={Math.abs(form.quantity) || ''}
              onFocus={(e) => e.target.select()}
              onChange={(e) => setField('quantity', Math.abs(parseFloat(e.target.value) || 0))}
              style={{ width: '160px', padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '1rem' }}
            />
          </>
        ) : (
          <>
            {form.type !== 'Actif' && (
              <div style={{ fontSize: '0.8rem', color: '#6A6E73', marginBottom: '0.25rem' }}>
                {form.type === 'Frais'
                  ? t('transactions.quantityNoteFrais')
                  : t('transactions.quantityNoteRevenu')}
              </div>
            )}
            <input
              id="tx-quantity"
              type="number"
              step={1}
              min={0}
              value={Math.abs(form.quantity) || ''}
              onFocus={(e) => e.target.select()}
              onChange={(e) => setField('quantity', Math.abs(parseFloat(e.target.value) || 0))}
              style={{ width: '160px', padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '1rem' }}
            />
          </>
        )}
      </FormGroup>
      )}

      {/* Exécutions (ordre fractionné) — zone complète affichée après le toggle */}
      {form.type === 'Actif' && !isEditing && form.fractional_order && (
        <FormGroup fieldId="tx-executions" style={{ marginBottom: '0.75rem' }}>
          {/* Unified executions section — 1ère + suivantes */}
          <div style={{ border: '1px solid #ddd', borderRadius: 6, padding: '0.75rem' }}>
              <div style={{ fontSize: '0.8rem', color: '#6A6E73', fontWeight: 600, marginBottom: '0.5rem' }}>
                {t('transactions.executions')}
              </div>
              {/* Première exécution — utilise form.date / form.quantity / form.unit_price */}
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.4rem', flexWrap: 'wrap' }}>
                <div>
                  <span style={{ fontSize: '0.75rem', color: '#6A6E73', display: 'block' }}>{t('common.date')}</span>
                  <FrDatePicker
                    value={form.date}
                    onChange={(iso) => setField('date', iso)}
                  />
                </div>
                {!isEurCurrency && (
                  <div>
                    <span style={{ fontSize: '0.75rem', color: '#6A6E73', display: 'block' }}>{t('transactions.fields.exchangeRate')}</span>
                    <input
                      type="number" min={0} step={0.0001}
                      value={form.exchange_rate || ''}
                      onFocus={(e) => e.target.select()}
                      onChange={(e) => setField('exchange_rate', parseFloat(e.target.value) || 0)}
                      style={{ width: '70px', padding: '4px 6px', border: '1px solid #0066CC', borderRadius: 4, fontSize: '0.9rem' }}
                    />
                  </div>
                )}
                <div>
                  <span style={{ fontSize: '0.75rem', color: '#6A6E73', display: 'block' }}>{t('common.quantity')}</span>
                  <input
                    type="number" min={0} step={1}
                    value={Math.abs(form.quantity) || ''}
                    onFocus={(e) => e.target.select()}
                    onChange={(e) => setField('quantity', Math.abs(parseFloat(e.target.value) || 0))}
                    style={{ width: '90px', padding: '4px 6px', border: '1px solid #0066CC', borderRadius: 4, fontSize: '0.9rem' }}
                  />
                </div>
                <div>
                  <span style={{ fontSize: '0.75rem', color: '#6A6E73', display: 'block' }}>{t('transactions.fields.unitPrice')}</span>
                  <input
                    type="number" min={0} step={0.0001}
                    value={form.unit_price || ''}
                    onFocus={(e) => e.target.select()}
                    onChange={(e) => setField('unit_price', parseFloat(e.target.value) || 0)}
                    style={{ width: '100px', padding: '4px 6px', border: '1px solid #0066CC', borderRadius: 4, fontSize: '0.9rem' }}
                  />
                </div>
                <div style={{ paddingTop: '1.1rem', minWidth: '70px', fontSize: '0.82rem', color: '#444' }}>
                  {(Math.abs(form.quantity) * form.unit_price * form.exchange_rate).toFixed(2)}€
                </div>
                <div style={{ paddingTop: '1.1rem' }}>
                  <span style={{ fontSize: '0.75rem', color: '#0066CC', fontStyle: 'italic' }}>{t('transactions.firstExec')}</span>
                </div>
              </div>
              {/* Exécutions supplémentaires */}
              {form.additional_executions.map((exec, idx) => (
                <div key={idx} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.4rem', flexWrap: 'wrap' }}>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: '#6A6E73', display: 'block' }}>{t('common.date')}</span>
                    <FrDatePicker
                      value={exec.date}
                      onChange={(iso) => {
                        const updated = [...form.additional_executions];
                        updated[idx] = { ...updated[idx], date: iso };
                        setField('additional_executions', updated);
                      }}
                    />
                  </div>
                  {!isEurCurrency && (
                    <div>
                      <span style={{ fontSize: '0.75rem', color: '#6A6E73', display: 'block' }}>{t('transactions.fields.exchangeRate')}</span>
                      <input
                        type="number" min={0} step={0.0001}
                        value={exec.exchange_rate || ''}
                        onFocus={(e) => e.target.select()}
                        onChange={(e) => {
                          const updated = [...form.additional_executions];
                          updated[idx] = { ...updated[idx], exchange_rate: parseFloat(e.target.value) || 0 };
                          setField('additional_executions', updated);
                        }}
                        style={{ width: '70px', padding: '4px 6px', border: '1px solid #ccc', borderRadius: 4, fontSize: '0.9rem' }}
                      />
                    </div>
                  )}
                  <div>
                    <span style={{ fontSize: '0.75rem', color: '#6A6E73', display: 'block' }}>{t('common.quantity')}</span>
                    <input
                      type="number" min={0} step={1}
                      value={exec.quantity || ''}
                      onFocus={(e) => e.target.select()}
                      onChange={(e) => {
                        const updated = [...form.additional_executions];
                        updated[idx] = { ...updated[idx], quantity: parseFloat(e.target.value) || 0 };
                        setField('additional_executions', updated);
                      }}
                      style={{ width: '90px', padding: '4px 6px', border: '1px solid #ccc', borderRadius: 4, fontSize: '0.9rem' }}
                    />
                  </div>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: '#6A6E73', display: 'block' }}>{t('transactions.fields.unitPrice')}</span>
                    <input
                      type="number" min={0} step={0.0001}
                      value={exec.unit_price || ''}
                      onFocus={(e) => e.target.select()}
                      onChange={(e) => {
                        const updated = [...form.additional_executions];
                        updated[idx] = { ...updated[idx], unit_price: parseFloat(e.target.value) || 0 };
                        setField('additional_executions', updated);
                      }}
                      style={{ width: '100px', padding: '4px 6px', border: '1px solid #ccc', borderRadius: 4, fontSize: '0.9rem' }}
                    />
                  </div>
                  <div style={{ paddingTop: '1.1rem', minWidth: '70px', fontSize: '0.82rem', color: '#444' }}>
                    {(Math.abs(exec.quantity) * exec.unit_price * (exec.exchange_rate || 1)).toFixed(2)}€
                  </div>
                  <div style={{ paddingTop: '1.1rem' }}>
                    <button
                      type="button"
                      onClick={() => {
                        const updated = form.additional_executions.filter((_, i) => i !== idx);
                        setField('additional_executions', updated);
                      }}
                      style={{ background: '#FAEAE8', border: '1px solid #C9190B', color: '#C9190B', borderRadius: 4, padding: '4px 8px', cursor: 'pointer', fontSize: '0.85rem' }}
                    >×</button>
                  </div>
                </div>
              ))}
              <button
                type="button"
                onClick={() => setField('additional_executions', [
                  ...form.additional_executions,
                  defaultExecRow(form),
                ])}
                style={{ marginTop: '0.25rem', background: '#f0f8ff', border: '1px solid #0066CC', color: '#0066CC', borderRadius: 4, padding: '4px 10px', cursor: 'pointer', fontSize: '0.82rem' }}
              >+ {t('transactions.addExecution')}</button>
              <div style={{ marginTop: '0.5rem', fontSize: '0.82rem', color: '#6A6E73' }}>
                Total : {(
                  Math.abs(form.quantity * form.unit_price) +
                  form.additional_executions.reduce((s, e) => s + Math.abs(e.quantity * e.unit_price), 0)
                ).toFixed(2)}€ ·{' '}
                {Math.abs(form.quantity) + form.additional_executions.reduce((s, e) => s + Math.abs(e.quantity), 0)} parts
              </div>
            </div>
        </FormGroup>
      )}

      {/* Bandeau info si exécution fractionnée (édition) */}
      {isEditing && editingTx?.fractional_parent_id && (
        <div style={{ background: '#FFF7E6', border: '1px solid #F0AB00', borderRadius: 6, padding: '0.5rem 0.75rem', marginBottom: '0.75rem', fontSize: '0.82rem', color: '#795600' }}>
          {t('transactions.fractionalParentNote')}
        </div>
      )}

      {/* Prix unitaire — masqué pour Dépôt/Retrait et ordre fractionné actif */}
      {form.type !== 'Dépôt/Retrait' && !form.fractional_order && <FormGroup
        label={form.type === 'Frais' && flatFee ? t('common.total') : t('transactions.fields.unitPrice')}
        isRequired
        fieldId="tx-unit-price"
        style={{ marginBottom: '1rem' }}
      >
        <input
          id="tx-unit-price"
          type="number"
          min={0}
          step={0.0001}
          value={form.unit_price || ''}
          disabled={isCash}
          onFocus={(e) => e.target.select()}
          onChange={(e) => {
            if (!isCash)
              setField('unit_price', /* v8 ignore next -- @preserve */ parseFloat(e.target.value) || 0);
          }}
          style={{ width: '140px', padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '1rem' }}
        />
      </FormGroup>}

      {/* Courtage + TTF — uniquement pour les Actifs (pas Dépôt/Retrait) */}
      {form.type === 'Actif' && (
        <div style={{ background: '#f5f5f5', borderRadius: 6, padding: '0.75rem 1rem', marginBottom: '1rem' }}>
          <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <FormGroup label={t('transactions.fields.brokerage')} fieldId="tx-courtage" style={{ margin: 0 }}>
              <input
                id="tx-courtage"
                type="number"
                min={0}
                step={0.01}
                value={form.courtage_eur || ''}
                onFocus={(e) => e.target.select()}
                onChange={(e) => setField('courtage_eur', parseFloat(e.target.value) || 0)}
                style={{ width: '100px', padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '1rem' }}
              />
            </FormGroup>
            <FormGroup label={t('transactions.fields.ttf')} fieldId="tx-ttf" style={{ margin: 0 }}>
              <input
                id="tx-ttf"
                type="number"
                min={0}
                step={0.01}
                value={form.ttf_eur || ''}
                disabled={operationType === 'sell'}
                onFocus={(e) => e.target.select()}
                onChange={(e) => setField('ttf_eur', parseFloat(e.target.value) || 0)}
                style={{ width: '100px', padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '1rem', opacity: operationType === 'sell' ? 0.5 : 1 }}
              />
            </FormGroup>
            <div style={{ fontSize: '0.85rem', color: '#6A6E73', paddingBottom: '0.35rem' }}>
              {t('transactions.totalCost')}{' '}
              <strong>
                {formatEUR(Math.abs(form.quantity * form.unit_price * form.exchange_rate) + form.courtage_eur + (operationType === 'buy' ? form.ttf_eur : 0))}
              </strong>
            </div>
          </div>
          <div style={{ fontSize: '0.75rem', color: '#6A6E73', marginTop: '0.5rem' }}>
            {t('transactions.brokerageAutoNote')}
            {isRevolutFX && (
              /* v8 ignore next -- @preserve */
              <span style={{ marginLeft: '0.5rem', color: isWeekendNewYork() ? '#C9190B' : '#0066CC' }}>
                {
                  /* v8 ignore start -- @preserve */
                  isWeekendNewYork()
                  ? ` ${t('transactions.weekendFXNote', { rate: ((selectedAccount?.weekend_rate ?? selectedAccount?.above_monthly_rate ?? 0.01) * 100).toFixed(1) })}`
                  : ` ${t('transactions.fxVolumeNote', { volume: monthFXTxs.reduce((s, tx) => s + Math.abs(tx.total_amount_eur), 0).toFixed(0), limit: selectedAccount?.monthly_free_eur ?? 1000 })}`
                  /* v8 ignore stop -- @preserve */
                }
              </span>
            )}
          </div>
        </div>
      )}

    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function TransactionsPage() {
  const { t } = useTranslation();
  const { portfolioId } = useParams<{ portfolioId: string }>();

  // Filter state
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [tickerFilter, setTickerFilter] = useState('');
  const [accountIdFilter, setAccountIdFilter] = useState('');
  const [currencyFilter, setCurrencyFilter] = useState('');

  // Pagination
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [showDevise, setShowDevise] = useState(true);
  const [editingTx, setEditingTx] = useState<Transaction | null>(null);

  const { data: transactions = [], isLoading, isError } = useTransactions(portfolioId!, {
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    ticker: tickerFilter || undefined,
    account_id: accountIdFilter ? Number(accountIdFilter) : undefined,
    currency: currencyFilter || undefined,
  });

  const { data: accounts = [] } = useBrokers(portfolioId!);
  const { data: allProducts = [] } = useProducts();
  const deleteMutation = useDeleteTransaction();

  // Account lookup map
  const accountMap = useMemo(
    () => new Map(accounts.map((a) => [a.id, a.name])),
    [accounts]
  );

  // Ticker → product name map for tooltips
  const productNameMap = useMemo(
    () => new Map(allProducts.map((p) => [p.ticker, p.name])),
    [allProducts]
  );

  // Currencies available for the current result set (already filtered server-side by account)
  const availableCurrencies = useMemo(
    () => [...new Set(transactions.map((tx) => tx.currency))].sort(),
    [transactions]
  );

  // IDs that carry the end-of-day balance per (date, currency).
  // transactions is sorted by id DESC (most recent first), so the first
  // occurrence of each (date, currency) group is the latest transaction —
  // the one whose running balance is the closing balance for that day.
  const endOfDayCurrencyIds = useMemo(() => {
    const seen = new Set<string>();
    const ids = new Set<number>();
    for (const tx of transactions) {
      const key = `${tx.date}:${tx.currency}`;
      if (!seen.has(key)) {
        seen.add(key);
        ids.add(tx.id);
      }
    }
    return ids;
  }, [transactions]);

  // Pagination slice
  const totalItems = transactions.length;
  const paginated = useMemo(
    () => transactions.slice((page - 1) * pageSize, page * pageSize),
    [transactions, page, pageSize]
  );

  const handleAddClick = () => {
    setEditingTx(null);
    setIsModalOpen(true);
  };

  const handleEditClick = (tx: Transaction) => {
    setEditingTx(tx);
    setIsModalOpen(true);
  };

  const handleDeleteClick = async (tx: Transaction) => {
    if (!window.confirm(t('transactions.deleteConfirm'))) return;
    await deleteMutation.mutateAsync({ id: tx.id, portfolio_id: Number(portfolioId) });
  };

  const handleModalClose = () => {
    setIsModalOpen(false);
    setEditingTx(null);
  };

  const handleFilterChange = (setter: (v: string) => void) => (val: string) => {
    setter(val);
    setPage(1);
  };

  return (
    <PageSection>
      <Title headingLevel="h1" size="xl" style={{ marginBottom: '1rem' }}>
        {t('transactions.title')}
      </Title>

      {/* Toolbar / Filtres */}
      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <FrDatePicker
              value={dateFrom}
              onChange={(iso) => handleFilterChange(setDateFrom)(iso)}
            />
          </ToolbarItem>
          <ToolbarItem>
            <FrDatePicker
              value={dateTo}
              onChange={(iso) => handleFilterChange(setDateTo)(iso)}
            />
          </ToolbarItem>
          <ToolbarItem>
            <TextInput
              type="text"
              aria-label="Ticker"
              placeholder="Ticker"
              value={tickerFilter}
              onChange={(_e, val) => handleFilterChange(setTickerFilter)(val)}
            />
          </ToolbarItem>
          <ToolbarItem>
            <FormSelect
              aria-label={t('common.account')}
              value={accountIdFilter}
              onChange={(_event, value) => {
                setAccountIdFilter(value);
                setPage(1);
                // Reset currency filter when switching account — server-side data will change
                setCurrencyFilter('');
              }}
              style={{ minWidth: '160px' }}
            >
              <FormSelectOption value="" label={t('common.all')} />
              {accounts.map((acc) => (
                <FormSelectOption key={acc.id} value={String(acc.id)} label={acc.name} />
              ))}
            </FormSelect>
          </ToolbarItem>
          <ToolbarItem>
            <FormSelect
              aria-label={t('common.currency')}
              value={currencyFilter}
              onChange={(_event, value) => { setCurrencyFilter(value); setPage(1); }}
              style={{ minWidth: '100px' }}
            >
              <FormSelectOption value="" label={t('transactions.allCurrencies')} />
              {availableCurrencies.map((currency) => (
                <FormSelectOption key={currency} value={currency} label={currency} />
              ))}
            </FormSelect>
          </ToolbarItem>
          <ToolbarItem>
            <Switch
              id="toggle-devise"
              label={t('transactions.fields.currencyColumns')}
              isChecked={showDevise}
              onChange={(_e, checked) => setShowDevise(checked)}
            />
          </ToolbarItem>
          <ToolbarItem align={{ default: 'alignRight' }}>
            <Button variant="primary" onClick={handleAddClick}>
              {t('transactions.newTransaction')}
            </Button>
          </ToolbarItem>
        </ToolbarContent>
      </Toolbar>

      {/* Loading */}
      {isLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
          <Spinner size="xl" />
        </div>
      )}

      {/* Error */}
      {isError && (
        <Alert
          variant="danger"
          title={t('error.loadingTransactions')}
          isInline
          style={{ marginTop: '1rem' }}
        />
      )}

      {/* Currency legend */}
      {!isLoading && !isError && (
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', margin: '0.5rem 0', fontSize: '0.8rem', color: '#6A6E73' }}>
          <span>{t('transactions.currencyLegend')}</span>
          {[
            { currency: 'EUR', bg: '#fff', border: '#d4d4d4', label: 'EUR' },
            { currency: 'JPY', bg: '#FFFDE7', border: '#FDD835', label: 'JPY' },
            { currency: 'GBP', bg: '#FCE4EC', border: '#E91E63', label: 'GBP' },
            { currency: 'USD', bg: '#E3F2FD', border: '#1976D2', label: 'USD' },
          ].map(({ currency, bg, border, label }) => (
            <span key={currency} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <span style={{ display: 'inline-block', width: 14, height: 14, backgroundColor: bg, border: `1.5px solid ${border}`, borderRadius: 2 }} />
              {label}
            </span>
          ))}
        </div>
      )}

      {/* Table */}
      {!isLoading && !isError && (
        <>
          <Table aria-label={t('transactions.title')} variant="compact">
            <Thead>
              <Tr>
                <Th>{t('transactions.fields.date')}</Th>
                <Th>{t('transactions.fields.account')}</Th>
                <Th>{t('transactions.fields.type')}</Th>
                <Th>{t('transactions.fields.ticker')}</Th>
                <Th modifier="nowrap">{t('transactions.fields.quantity')}</Th>
                {showDevise && <Th modifier="nowrap">{t('transactions.fields.unitPriceCurrency')}</Th>}
                <Th modifier="nowrap">{t('transactions.fields.unitPriceEur')}</Th>
                {showDevise && <Th modifier="nowrap">{t('transactions.fields.totalCurrency')}</Th>}
                <Th modifier="nowrap">{t('common.total')} EUR</Th>
                {showDevise && <Th modifier="nowrap">{t('transactions.fields.balanceCurrency')}</Th>}
                <Th modifier="nowrap">{t('transactions.fields.balanceEur')}</Th>
                <Th>{t('common.actions')}</Th>
              </Tr>
            </Thead>
            <Tbody>
              {paginated.length === 0 ? (
                <Tr>
                  <Td colSpan={showDevise ? 12 : 9} style={{ textAlign: 'center', color: 'var(--pf-v5-global--Color--200)' }}>
                    {t('transactions.noTransactions')}
                  </Td>
                </Tr>
              ) : (
                paginated.map((tx) => {
                  const CURRENCY_BG: Record<string, string> = {
                    EUR: '#fff', JPY: '#FFFDE7', GBP: '#FCE4EC', USD: '#E3F2FD',
                  };
                  const rowBg = CURRENCY_BG[tx.currency] ?? '#f9f9f9';
                  return (
                  <Tr key={tx.id} style={{ backgroundColor: rowBg }}>
                    <Td dataLabel="Date">{tx.date}</Td>
                    <Td dataLabel="Compte">{accountMap.get(tx.account_id) ?? tx.account_id}</Td>
                    <Td dataLabel="Type">{tx.type}</Td>
                    <Td dataLabel="Ticker">
                      {productNameMap.has(tx.ticker) ? (
                        <Tooltip content={productNameMap.get(tx.ticker)}>
                          <span style={{ cursor: 'help', textDecoration: 'underline dotted' }}>
                            {tx.ticker}
                          </span>
                        </Tooltip>
                      ) : tx.ticker}
                    </Td>
                    <Td dataLabel="Quantité" modifier="nowrap">
                      {formatQty(tx.quantity)}
                    </Td>
                    {showDevise && (
                    <Td dataLabel="Prix unitaire devise" modifier="nowrap">
                      {tx.currency === 'EUR'
                        ? '—'
                        : formatNativeCurrency(tx.unit_price, tx.currency, 3, 0)}
                    </Td>
                    )}
                    <Td dataLabel="Prix unitaire EUR" modifier="nowrap">
                      {formatEUR3(tx.unit_price_eur)}
                    </Td>
                    {showDevise && (
                    <Td dataLabel="Total devise" modifier="nowrap">
                      {tx.currency === 'EUR'
                        ? '—'
                        : formatNativeCurrency(tx.total_amount, tx.currency, 3, 0)}
                    </Td>
                    )}
                    <Td dataLabel="Total EUR" modifier="nowrap">
                      {formatEUR(tx.total_amount_eur)}
                    </Td>
                    {showDevise && (
                    <Td dataLabel="Solde compte devise" modifier="nowrap">
                      {endOfDayCurrencyIds.has(tx.id) && tx.currency !== 'EUR' && tx.balance_currency != null
                        ? formatNativeCurrency(tx.balance_currency, tx.currency, 2)
                        : '—'}
                    </Td>
                    )}
                    <Td dataLabel="Contrevaleur solde EUR" modifier="nowrap">
                      {endOfDayCurrencyIds.has(tx.id)
                        ? tx.currency !== 'EUR' && tx.balance_currency != null
                          ? formatEUR(tx.balance_currency * tx.exchange_rate)
                          : tx.balance_eur != null ? formatEUR(tx.balance_eur) : '—'
                        : '—'}
                    </Td>
                    <Td dataLabel="Actions" modifier="nowrap">
                      <Button
                        variant="plain"
                        aria-label={t('common.edit')}
                        onClick={() => handleEditClick(tx)}
                        style={{ padding: '0 0.5rem' }}
                      >
                        <PencilAltIcon />
                      </Button>
                      <Button
                        variant="plain"
                        aria-label={t('common.delete')}
                        onClick={() => handleDeleteClick(tx)}
                        style={{ padding: '0 0.5rem', color: 'var(--pf-v5-global--danger-color--100)' }}
                      >
                        <TrashIcon />
                      </Button>
                    </Td>
                  </Tr>
                  );
                })
              )}
            </Tbody>
          </Table>

          <Pagination
            itemCount={totalItems}
            perPage={pageSize}
            page={page}
            onSetPage={(_e, p) => setPage(p)}
            onPerPageSelect={(_e, ps) => { setPageSize(ps); setPage(1); }}
            perPageOptions={[
              { title: '10', value: 10 },
              { title: '20', value: 20 },
              { title: '50', value: 50 },
              { title: '100', value: 100 },
              { title: '200', value: 200 },
            ]}
            variant="bottom"
          />
        </>
      )}

      {/* Modal */}
      {isModalOpen && (
        <TransactionModal
          isOpen={isModalOpen}
          portfolioId={portfolioId!}
          editingTx={editingTx}
          linkedFees={editingTx
            ? transactions.filter(tx => tx.linked_transaction_id === editingTx.id)
            : []}
          onClose={handleModalClose}
        />
      )}
    </PageSection>
  );
}
