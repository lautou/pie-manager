/**
 * FiscalitePage — Moins-values reportables (tax carry-forward tracker).
 *
 * Business rules (current year = 2026):
 *  - EXPIRED:  tax_year <= 2015  (older than 10 years)
 *  - EXPIRING: tax_year == 2016  (last usable year — warn)
 *  - ACTIVE:   tax_year >= 2016
 *
 * Totals only include ACTIVE rows (tax_year >= 2016).
 * amount_eur is stored as negative (loss), e.g. -12450.
 */
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  FormSelect,
  FormSelectOption,
  PageSection,
  Spinner,
  Title,
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';
import { PencilAltIcon, TrashIcon } from '@patternfly/react-icons';
import { useState } from 'react';
import {
  useFiscalCarryForwards,
  useFiscalCurrentYearPv,
  useCreateCarryForward,
  useUpdateCarryForward,
  useDeleteCarryForward,
} from '../api/queries';
import type { FiscalCarryForward } from '../types';

// ── Constants ────────────────────────────────────────────────────────────────

const CURRENT_YEAR = 2026;
const EXPIRY_LIMIT = 10; // carry-forward expires after 10 years

function isExpired(taxYear: number): boolean {
  return CURRENT_YEAR - taxYear > EXPIRY_LIMIT; // <= 2015
}

function isExpiring(taxYear: number): boolean {
  return CURRENT_YEAR - taxYear === EXPIRY_LIMIT; // == 2016
}

function isCurrent(taxYear: number): boolean {
  return taxYear === CURRENT_YEAR;
}

function formatEUR(value: number): string {
  return new Intl.NumberFormat('fr-FR', {
    style: 'currency',
    currency: 'EUR',
    minimumFractionDigits: 2,
  }).format(value);
}

// ── Year selector helpers ─────────────────────────────────────────────────────

function buildAvailableYears(
  existing: FiscalCarryForward[],
  minYear: number,
): number[] {
  const usedYears = new Set(existing.map((e) => e.tax_year));
  const years: number[] = [];
  const start = CURRENT_YEAR; // current year is enterable (capital gains already realised)
  const end = Math.min(minYear, 2010);
  for (let y = start; y >= end; y--) {
    if (!usedYears.has(y)) years.push(y);
  }
  return years;
}

// ── Row components ────────────────────────────────────────────────────────────

function ExistingRow({
  entry,
  portfolioId,
}: {
  entry: FiscalCarryForward;
  portfolioId: number;
}) {
  const { t } = useTranslation();
  const expired = isExpired(entry.tax_year);
  const expiring = isExpiring(entry.tax_year);
  const current = isCurrent(entry.tax_year);
  const updateMutation = useUpdateCarryForward();
  const deleteMutation = useDeleteCarryForward();

  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(Math.abs(entry.amount_eur));

  const rowStyle: React.CSSProperties = expired
    ? { backgroundColor: '#f5f5f5', color: '#888' }
    : expiring
    ? { backgroundColor: '#fffde7' }
    : {};

  const cellStyle: React.CSSProperties = expired ? { color: '#aaa' } : {};

  function handleDelete() {
    deleteMutation.mutate({ id: entry.id, portfolio_id: portfolioId });
  }

  function startEdit() {
    setEditValue(Math.abs(entry.amount_eur));
    setEditing(true);
  }

  function saveEdit() {
    const newAmount = -Math.abs(editValue);
    if (newAmount !== entry.amount_eur) {
      updateMutation.mutate({ id: entry.id, portfolio_id: portfolioId, amount_eur: newAmount });
    }
    setEditing(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') saveEdit();
    if (e.key === 'Escape') setEditing(false);
  }

  const displayAmount = formatEUR(entry.amount_eur);

  return (
    <Tr style={rowStyle}>
      {/* Année */}
      <Td style={cellStyle}>
        {entry.tax_year}
        {current && (
          <span
            data-testid="current-year-badge"
            style={{
              marginLeft: '0.5rem',
              background: '#0066CC',
              color: 'white',
              borderRadius: 4,
              padding: '2px 6px',
              fontSize: '0.75rem',
              fontWeight: 600,
            }}
          >
            {t('taxation.currentYearBadge')}
          </span>
        )}
        {expiring && (
          <span
            data-testid="expiry-warning"
            style={{
              marginLeft: '0.5rem',
              background: '#ffc107',
              color: '#333',
              borderRadius: 4,
              padding: '2px 6px',
              fontSize: '0.75rem',
              fontWeight: 600,
            }}
          >
            {t('taxation.expiringBadge', { year: CURRENT_YEAR })}
          </span>
        )}
      </Td>

      {/* Montant MV — éditable inline */}
      <Td style={cellStyle}>
        {editing ? (
          <input
            type="number"
            min={0}
            step={0.01}
            value={/* v8 ignore next -- @preserve */editValue || ''}
            autoFocus
            onFocus={(e) => e.target.select()}
            /* v8 ignore next -- @preserve */
            onChange={(e) => setEditValue(Math.abs(parseFloat(e.target.value) || 0))}
            onBlur={saveEdit}
            onKeyDown={handleKeyDown}
            style={{ width: '120px', padding: '4px 6px', border: '1px solid #0066CC', borderRadius: 4, fontSize: '0.9rem' }}
          />
        ) : (
          <span
            data-testid="amount-display"
            onClick={expired ? undefined : startEdit}
            title={expired ? undefined : t('taxation.clickToEdit')}
            style={{ cursor: expired ? 'default' : 'pointer', borderBottom: expired ? undefined : '1px dashed #aaa' }}
          >
            {displayAmount}
          </span>
        )}
      </Td>

      {/* Reste à imputer */}
      <Td style={cellStyle}>
        {expired ? (
          <em style={{ color: '#aaa' }}>
            {t('taxation.expiredNote')}
          </em>
        ) : (
          displayAmount
        )}
      </Td>

      {/* Actions */}
      <Td>
        {!expired && (
          <Button
            variant="plain"
            aria-label={t('common.edit')}
            onClick={startEdit}
            isDisabled={updateMutation.isPending}
            style={{ marginRight: '0.25rem' }}
          >
            <PencilAltIcon />
          </Button>
        )}
        <Button
          variant="plain"
          aria-label={t('common.delete')}
          onClick={handleDelete}
          isDisabled={deleteMutation.isPending}
        >
          <TrashIcon />
        </Button>
      </Td>
    </Tr>
  );
}

function NewRow({
  portfolioId,
  availableYears,
  onCancel,
}: {
  portfolioId: number;
  availableYears: number[];
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const createMutation = useCreateCarryForward();
  /* v8 ignore next -- @preserve */
  const [taxYear, setTaxYear] = useState<number>(availableYears[0] ?? 2025);
  const [amountAbs, setAmountAbs] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (amountAbs <= 0) {
      setError(t('taxation.amountPositive'));
      return;
    }
    try {
      await createMutation.mutateAsync({
        portfolio_id: portfolioId,
        tax_year: taxYear,
        amount_eur: -Math.abs(amountAbs),
      });
      onCancel(); // close new row on success
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : t('taxation.creationError');
      setError(msg);
    }
  }

  return (
    <Tr data-testid="new-row">
      {/* Année */}
      <Td>
        <FormSelect
          value={String(taxYear)}
          onChange={(_e, val) => setTaxYear(Number(val))}
          aria-label={t('taxation.selectYear')}
        >
          {availableYears.map((y) => (
            <FormSelectOption key={y} value={String(y)} label={String(y)} />
          ))}
        </FormSelect>
      </Td>

      {/* Montant MV — user enters a positive value */}
      <Td>
        <input
          type="number"
          min={0}
          step={0.01}
          value={amountAbs || ''}
          onChange={(e) => setAmountAbs(Math.abs(Number(e.target.value)))}
          onFocus={(e) => e.target.select()}
          style={{ width: '120px' }}
          aria-label={t('taxation.amountLabel')}
        />
        {error && (
          <Alert
            variant="danger"
            isInline
            title={error}
            style={{ marginTop: '0.25rem' }}
          />
        )}
      </Td>

      {/* Reste à imputer — not available for new row */}
      <Td>—</Td>

      {/* Actions */}
      <Td>
        <Button
          variant="primary"
          onClick={handleSave}
          isDisabled={createMutation.isPending}
        >
          {t('common.save')}
        </Button>{' '}
        <Button variant="link" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
      </Td>
    </Tr>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function TaxPage() {
  const { t } = useTranslation();
  const { portfolioId: portfolioIdStr } = useParams<{ portfolioId: string }>();
  const portfolioId = Number(portfolioIdStr);
  const [addingNew, setAddingNew] = useState(false);

  const { data: entries = [], isLoading, isError } = useFiscalCarryForwards(portfolioIdStr);
  const { data: currentYearPv } = useFiscalCurrentYearPv(portfolioIdStr);

  // Years usable for a new row (not already in DB, not future)
  const oldestExisting = entries.length > 0
    ? Math.min(...entries.map((e) => e.tax_year))
    : 2010;
  const availableYears = buildAvailableYears(entries, oldestExisting);

  // Totals: only ACTIVE rows (tax_year >= 2016)
  const activeEntries = entries.filter((e) => !isExpired(e.tax_year));
  const totalDeclared = activeEntries.reduce((sum, e) => sum + e.amount_eur, 0);
  const totalRemaining = totalDeclared;

  // Fiscal simulation: MV backlog + current year net PV (CTO, excl. JPYEUR=X)
  const pvNetCurrentYear = currentYearPv?.net_realized_pv ?? null;
  const stockAjuste = pvNetCurrentYear !== null ? totalRemaining + pvNetCurrentYear : null;

  if (isLoading) {
    return (
      <PageSection>
        <Spinner aria-label={t('taxation.loading')} />
      </PageSection>
    );
  }

  if (isError) {
    return (
      <PageSection>
        <Alert variant="danger" title={t('taxation.loadError')} />
      </PageSection>
    );
  }

  return (
    <PageSection>
      <Title headingLevel="h1" size="xl" style={{ marginBottom: '1rem' }}>
        {t('taxation.title')}
      </Title>

      <p style={{ marginBottom: '1rem', color: '#555' }}>
        {t('taxation.trackingInfo')}
      </p>

      <Table aria-label="Moins-values reportables">
        <Thead>
          <Tr>
            <Th>{t('taxation.year')}</Th>
            <Th>{t('taxation.amountMV')}</Th>
            <Th>{t('taxation.remainingToOffset')}</Th>
            <Th>{t('common.actions')}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {entries.map((entry) => (
            <ExistingRow
              key={entry.id}
              entry={entry}
              portfolioId={portfolioId}
            />
          ))}

          {addingNew && availableYears.length > 0 && (
            <NewRow
              portfolioId={portfolioId}
              availableYears={availableYears}
              onCancel={() => setAddingNew(false)}
            />
          )}

          {entries.length === 0 && !addingNew && (
            <Tr>
              <Td colSpan={4}>
                <em>{t('taxation.noEntries')}</em>
              </Td>
            </Tr>
          )}
        </Tbody>
      </Table>

      {/* "Ajouter une année" button */}
      {!addingNew && availableYears.length > 0 && (
        <Button
          variant="secondary"
          onClick={() => setAddingNew(true)}
          style={{ marginTop: '1rem' }}
        >
          {t('taxation.addYear')}
        </Button>
      )}

      {/* Totals section */}
      <div
        style={{
          marginTop: '1.5rem',
          padding: '1rem',
          background: '#f9f9f9',
          borderRadius: 6,
          border: '1px solid #ddd',
        }}
      >
        <Title headingLevel="h2" size="md" style={{ marginBottom: '0.5rem' }}>
          {t('capitalGains.summary')}
        </Title>
        <div style={{ display: 'flex', gap: '2rem' }}>
          <div>
            <strong>{t('taxation.totalDeclared')}&nbsp;:</strong>{' '}
            <span data-testid="total-declared" style={{ color: '#c00', fontWeight: 600 }}>
              {formatEUR(totalDeclared)}
            </span>
          </div>
          <div>
            <strong>{t('taxation.totalRemaining')}&nbsp;:</strong>{' '}
            <span data-testid="total-remaining" style={{ color: '#c00', fontWeight: 600 }}>
              {formatEUR(totalRemaining)}
            </span>
          </div>
        </div>
      </div>

      {/* Simulation fiscale année en cours */}
      {stockAjuste !== null && pvNetCurrentYear !== null && (
        <div
          style={{
            marginTop: '1.5rem',
            padding: '1rem',
            background: '#f0f7ff',
            borderRadius: 6,
            border: '1px solid #b3d4ff',
          }}
        >
          <Title headingLevel="h2" size="md" style={{ marginBottom: '0.75rem' }}>
            {t('taxation.fiscalSimulation', { year: CURRENT_YEAR })}
          </Title>
          <div style={{ display: 'grid', gap: '0.4rem', fontSize: '0.95rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', maxWidth: 420 }}>
              <span>{t('taxation.activeDeclaredTotal')}</span>
              <strong style={{ color: '#c00' }}>{formatEUR(totalRemaining)}</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', maxWidth: 420 }}>
              <span>{t('taxation.netRealizedGains', { year: CURRENT_YEAR })}</span>
              <strong style={{ color: pvNetCurrentYear >= 0 ? '#137333' : '#c00' }}>
                {pvNetCurrentYear >= 0 ? '+' : ''}{formatEUR(pvNetCurrentYear)}
              </strong>
            </div>
            <div style={{
              display: 'flex', justifyContent: 'space-between', maxWidth: 420,
              borderTop: '1px solid #b3d4ff', paddingTop: '0.4rem', marginTop: '0.2rem',
            }}>
              <strong>{t('taxation.remainingLossStock')}</strong>
              <strong style={{
                color: stockAjuste >= 0 ? '#137333' : '#c00',
                fontSize: '1.05rem',
              }}>
                {stockAjuste >= 0 ? '+' : ''}{formatEUR(stockAjuste)}
              </strong>
            </div>
          </div>
          {stockAjuste >= 0 && (
            <div style={{ marginTop: '0.75rem', padding: '0.5rem', background: '#fff3cd', borderRadius: 4, fontSize: '0.85rem', color: '#856404' }}>
              {t('taxation.taxableGainsAlert', { amount: formatEUR(stockAjuste), year: CURRENT_YEAR })}
            </div>
          )}
          <div style={{ marginTop: '0.75rem', fontSize: '0.78rem', color: '#6A6E73' }}>
            {t('taxation.disclaimer')}
          </div>
        </div>
      )}
    </PageSection>
  );
}
