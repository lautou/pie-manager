// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
	Alert,
	Button,
	FormGroup,
	FormSelect,
	FormSelectOption,
	Modal,
	ModalBody,
	ModalFooter,
	ModalHeader,
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
	ToolbarItem
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';
import { PencilAltIcon, TrashIcon } from '@patternfly/react-icons';
import {
  useTransactions,
  useBrokers,
  useProducts,
  useDeleteTransaction,
} from '../api/queries';
import type { Transaction } from '../types';
import FrDatePicker from '../components/FrDatePicker';
import ConfirmModal from '../components/ConfirmModal';
import TickerLink from '../components/TickerLink';
import EtfCompositionModal from '../components/EtfCompositionModal';
import { formatEUR, formatEUR3, formatQty as fmtQty, formatNativeCurrency } from '../utils/format';
import { isWeekendNewYork } from '../utils/commission';
import { TRANSACTION_TYPES, LIQUIDITE_TICKER } from '../utils/transactionConstants';
import { useTransactionForm, defaultExecRow } from '../hooks/useTransactionForm';

// Use centralized fr-FR formatters
const formatQty = (val: number) => fmtQty(val);

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
  const {
    form, setForm, setField, error, isEditing, isLoading,
    accounts, selectedAccount, filteredProducts,
    flatFee, setFlatFee,
    direction, setDirection,
    operationType, setOperationType,
    isCash, isCashDirectDeposit, isEurCurrency, isCurrencyLocked, isRevolutFX,
    monthWithdrawals, monthFXTxs,
    handleTypeChange, handleTickerChange, handleCurrencyChange, handleSubmit,
  } = useTransactionForm(isOpen, portfolioId, editingTx, linkedFees, onClose);

  return (
    <Modal
      variant={ModalVariant.large}
      isOpen={isOpen}
      onClose={onClose}
      onEscapePress={onClose}
    >
      <ModalHeader title={isEditing ? t('transactions.editTransaction') : t('transactions.newTransaction')} />
      <ModalBody>
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

          {/* Sens — Achat/Vente/Attribution pour Actif, placé avant Taux */}
          {form.type === 'Actif' && !isCashDirectDeposit && (
            <FormGroup label={t('transactions.fields.direction')} isRequired fieldId="tx-sens-inline" style={{ marginBottom: '1rem' }}>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <Button variant={operationType === 'buy' ? 'primary' : 'control'} size="sm"
                  onClick={() => setOperationType('buy')}>📉 {t('transactions.direction.buy')}</Button>
                <Button variant={operationType === 'sell' ? 'primary' : 'control'} size="sm"
                  onClick={() => setOperationType('sell')}>📈 {t('transactions.direction.sell')}</Button>
                <Button variant={operationType === 'grant' ? 'primary' : 'control'} size="sm"
                  onClick={() => {
                    setOperationType('grant');
                    setForm((prev) => ({ ...prev, unit_price: 0, courtage_eur: 0, ttf_eur: 0 }));
                  }}>🎁 {t('transactions.direction.grant')}</Button>
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
          form.type === 'Actif' && isCashDirectDeposit ? (
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
                disabled={operationType === 'grant'}
                onFocus={(e) => e.target.select()}
                onChange={(e) => setField('courtage_eur', parseFloat(e.target.value) || 0)}
                style={{ width: '100px', padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '1rem', opacity: operationType === 'grant' ? 0.5 : 1 }}
              />
            </FormGroup>
            <FormGroup label={t('transactions.fields.ttf')} fieldId="tx-ttf" style={{ margin: 0 }}>
              <input
                id="tx-ttf"
                type="number"
                min={0}
                step={0.01}
                value={form.ttf_eur || ''}
                disabled={operationType === 'sell' || operationType === 'grant'}
                onFocus={(e) => e.target.select()}
                onChange={(e) => setField('ttf_eur', parseFloat(e.target.value) || 0)}
                style={{ width: '100px', padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '1rem', opacity: (operationType === 'sell' || operationType === 'grant') ? 0.5 : 1 }}
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

      </ModalBody>
      <ModalFooter>
        <Button
          key="submit"
          variant="primary"
          onClick={handleSubmit}
          isLoading={isLoading}
          isDisabled={isLoading}
        >
          {isEditing ? t('common.save') : t('common.add')}
        </Button>
        <Button key="cancel" variant="link" onClick={onClose} isDisabled={isLoading}>
          {t('common.cancel')}
        </Button>
      </ModalFooter>
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
  const [deleteTarget, setDeleteTarget] = useState<Transaction | null>(null);
  const [compositionTicker, setCompositionTicker] = useState<string | null>(null);

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

  // Ticker → product map, for the tooltip's product name and the composition click affordance
  const productByTicker = useMemo(
    () => new Map(allProducts.map((p) => [p.ticker, p])),
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

  const handleDeleteClick = (tx: Transaction) => {
    setDeleteTarget(tx);
  };

  const handleConfirmDelete = async () => {
    /* v8 ignore next -- @preserve */
    if (!deleteTarget) return;
    await deleteMutation.mutateAsync({ id: deleteTarget.id, portfolio_id: Number(portfolioId) });
    setDeleteTarget(null);
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
    <PageSection hasBodyWrapper={false}>
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
          <ToolbarItem align={{ default: "alignEnd" }}>
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
                <Th>{t('transactions.fields.direction')}</Th>
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
                  <Td colSpan={showDevise ? 13 : 10} style={{ textAlign: 'center', color: 'var(--pf-t--global--text--color--subtle)' }}>
                    {t('transactions.noTransactions')}
                  </Td>
                </Tr>
              ) : (
                paginated.map((tx) => {
                  const CURRENCY_BG: Record<string, string> = {
                    EUR: '#fff', JPY: '#FFFDE7', GBP: '#FCE4EC', USD: '#E3F2FD',
                  };
                  const rowBg = CURRENCY_BG[tx.currency] ?? '#f9f9f9';
                  // Dépôt/Retrait (the LIQUIDITE.EURO pseudo-type) shows its own
                  // direction; other Actif transactions show operation
                  // (Achat/Vente/Attribution); Frais/Revenu have no "sens".
                  const sens = tx.type !== 'Actif' ? '—'
                    : tx.ticker === LIQUIDITE_TICKER
                    ? (tx.quantity > 0 ? t('transactions.direction.deposit') : t('transactions.direction.withdrawal'))
                    : tx.operation === 'Achat' ? t('transactions.direction.buy')
                    : tx.operation === 'Vente' ? t('transactions.direction.sell')
                    : tx.operation === 'Attribution' ? t('transactions.direction.grant')
                    : '—';
                  return (
                  <Tr key={tx.id} style={{ backgroundColor: rowBg }}>
                    <Td dataLabel="Date">{tx.date}</Td>
                    <Td dataLabel="Compte">{accountMap.get(tx.account_id) ?? tx.account_id}</Td>
                    <Td dataLabel="Type">{tx.type}</Td>
                    <Td dataLabel="Sens">{sens}</Td>
                    <Td dataLabel="Ticker">
                      {productByTicker.has(tx.ticker) ? (
                        <Tooltip content={productByTicker.get(tx.ticker)?.name}>
                          <span style={{ cursor: 'help', textDecoration: 'underline dotted' }}>
                            <TickerLink
                              ticker={tx.ticker}
                              instrumentType={productByTicker.get(tx.ticker)?.instrument_type}
                              onClick={setCompositionTicker}
                            />
                          </span>
                        </Tooltip>
                      ) : (
                        <TickerLink
                          ticker={tx.ticker}
                          instrumentType={productByTicker.get(tx.ticker)?.instrument_type}
                          onClick={setCompositionTicker}
                        />
                      )}
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
                      <Button icon={<PencilAltIcon />}
                        variant="plain"
                        aria-label={t('common.edit')}
                        onClick={() => handleEditClick(tx)}
                        style={{ padding: '0 0.5rem' }}
                       />
                      <Button icon={<TrashIcon />}
                        variant="plain"
                        aria-label={t('common.delete')}
                        onClick={() => handleDeleteClick(tx)}
                        style={{ padding: '0 0.5rem', color: 'var(--pf-t--global--text--color--status--danger--default)' }}
                       />
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

      <ConfirmModal
        isOpen={!!deleteTarget}
        title={t('common.confirmDeleteTitle')}
        message={t('transactions.deleteConfirm')}
        isLoading={deleteMutation.isPending}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      <EtfCompositionModal ticker={compositionTicker} onClose={() => setCompositionTicker(null)} />
    </PageSection>
  );
}
