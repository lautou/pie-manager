// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * FiscalitePage — Moins-values reportables (tax carry-forward tracker).
 *
 * Business rules (relative to the current calendar year — see CURRENT_YEAR below):
 *  - EXPIRED:  tax_year is more than EXPIRY_LIMIT years old
 *  - EXPIRING: tax_year is exactly EXPIRY_LIMIT years old (last usable year — warn)
 *  - ACTIVE:   tax_year is EXPIRY_LIMIT years old or newer
 *
 * Totals only include ACTIVE rows.
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
  useBrokers,
} from '../api/queries';
import { formatEUR, formatDate } from '../utils/format';
import { computeLossHarvestingPlan } from '../utils/lossHarvesting';
import type { FiscalCarryForward, Broker } from '../types';
import type { FiscalPvDetail, FiscalLossCandidate } from '../api/queries';

// ── Constants ────────────────────────────────────────────────────────────────

const CURRENT_YEAR = new Date().getFullYear();
const EXPIRY_LIMIT = 10; // carry-forward expires after 10 years

function isExpired(taxYear: number): boolean {
  return CURRENT_YEAR - taxYear > EXPIRY_LIMIT;
}

function isExpiring(taxYear: number): boolean {
  return CURRENT_YEAR - taxYear === EXPIRY_LIMIT;
}

function isCurrent(taxYear: number): boolean {
  return taxYear === CURRENT_YEAR;
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
          <Button icon={<PencilAltIcon />}
            variant="plain"
            aria-label={t('common.edit')}
            onClick={startEdit}
            isDisabled={updateMutation.isPending}
            style={{ marginRight: '0.25rem' }}
           />
        )}
        <Button icon={<TrashIcon />}
          variant="plain"
          aria-label={t('common.delete')}
          onClick={handleDelete}
          isDisabled={deleteMutation.isPending}
         />
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

// ── Fiscal-simulation detail sub-tables ────────────────────────────────────────

function DisposalTable({ rows }: { rows: FiscalPvDetail[] }) {
  const { t } = useTranslation();
  return (
    <Table aria-label="Détail des cessions" variant="compact" style={{ marginTop: '0.5rem' }}>
      <Thead>
        <Tr>
          <Th>{t('capitalGains.eventDate')}</Th>
          <Th>{t('capitalGains.ticker')}</Th>
          <Th>{t('capitalGains.productNameHistory')}</Th>
          <Th>{t('capitalGains.eventQtySold')}</Th>
          <Th>{t('capitalGains.realizedPV')}</Th>
        </Tr>
      </Thead>
      <Tbody>
        {rows.map((d, idx) => (
          <Tr key={`${d.date}-${d.ticker}-${idx}`}>
            <Td>{formatDate(d.date)}</Td>
            <Td><strong>{d.ticker}</strong></Td>
            <Td>{d.product_name}</Td>
            <Td>{d.qty_sold.toLocaleString('fr-FR', { maximumFractionDigits: 4 })}</Td>
            <Td>
              <span style={{ color: d.realized_pv >= 0 ? '#137333' : '#c00', fontWeight: 500 }}>
                {d.realized_pv > 0 ? '+' : ''}{formatEUR(d.realized_pv)}
              </span>
            </Td>
          </Tr>
        ))}
      </Tbody>
    </Table>
  );
}

function LossHarvestingSection({
  candidates,
  brokersById,
}: {
  candidates: FiscalLossCandidate[];
  brokersById: Map<number, Broker>;
}) {
  const { t } = useTranslation();
  return (
    <div style={{ marginTop: '1rem' }}>
      <Title headingLevel="h3" size="md" style={{ marginBottom: '0.4rem' }}>
        {t('taxation.lossHarvestingTitle')}
      </Title>
      {candidates.length === 0 ? (
        <p style={{ fontSize: '0.85rem', color: '#6A6E73', margin: 0 }}>
          {t('taxation.lossHarvestingEmpty')}
        </p>
      ) : (
        <Table aria-label="Positions en moins-value latente" variant="compact">
          <Thead>
            <Tr>
              <Th>{t('capitalGains.ticker')}</Th>
              <Th>{t('capitalGains.productName')}</Th>
              <Th>{t('common.account')}</Th>
              <Th>{t('taxation.qtyHeld')}</Th>
              <Th>{t('capitalGains.cump')}</Th>
              <Th>{t('capitalGains.currentValue')}</Th>
              <Th>{t('capitalGains.unrealizedPV')}</Th>
            </Tr>
          </Thead>
          <Tbody>
            {candidates.map((c) => (
              <Tr key={`${c.account_id}-${c.ticker}`}>
                <Td><strong>{c.ticker}</strong></Td>
                <Td>{c.product_name}</Td>
                <Td>{brokersById.get(c.account_id)?.name ?? c.account_id}</Td>
                <Td>{c.qty_held.toLocaleString('fr-FR', { maximumFractionDigits: 4 })}</Td>
                <Td>{formatEUR(c.cump)}</Td>
                <Td>{formatEUR(c.current_value_eur)}</Td>
                {/* Always a loss — the API only ever returns candidates with unrealized_pv < 0 */}
                <Td><span style={{ color: '#c00', fontWeight: 500 }}>{formatEUR(c.unrealized_pv)}</span></Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </div>
  );
}

function LossHarvestingPlanSection({
  candidates,
  target,
  brokersById,
}: {
  candidates: FiscalLossCandidate[];
  target: number;
  brokersById: Map<number, Broker>;
}) {
  const { t } = useTranslation();
  const [fractionable, setFractionable] = useState(false);

  if (target <= 0 || candidates.length === 0) return null;

  const plan = computeLossHarvestingPlan(candidates, target, fractionable, brokersById);

  return (
    <div style={{ marginTop: '1rem' }}>
      <Title headingLevel="h3" size="md" style={{ marginBottom: '0.4rem' }}>
        {t('taxation.planTitle')}
      </Title>

      <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
        <input
          type="checkbox"
          checked={fractionable}
          onChange={(e) => setFractionable(e.target.checked)}
        />
        {t('taxation.planFractionable')}
      </label>

      <Table aria-label="Recommandation vente puis rachat" variant="compact">
        <Thead>
          <Tr>
            <Th>{t('capitalGains.ticker')}</Th>
            <Th>{t('capitalGains.productName')}</Th>
            <Th>{t('common.account')}</Th>
            <Th>{t('taxation.planQtyToSell')}</Th>
            <Th>{t('taxation.planEstimatedLoss')}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {plan.lines.map((line) => (
            <Tr key={`${line.account_id}-${line.ticker}`}>
              <Td><strong>{line.ticker}</strong></Td>
              <Td>{line.product_name}</Td>
              <Td>{brokersById.get(line.account_id)?.name ?? line.account_id}</Td>
              <Td>{line.qty.toLocaleString('fr-FR', { maximumFractionDigits: 4 })}</Td>
              <Td><span style={{ color: '#c00', fontWeight: 500 }}>{formatEUR(-line.estimated_loss)}</span></Td>
            </Tr>
          ))}
        </Tbody>
      </Table>

      <p style={{ fontSize: '0.85rem', marginTop: '0.5rem' }}>
        {t('taxation.planCovered', { covered: formatEUR(plan.covered), target: formatEUR(target) })}
      </p>
      {plan.shortfall > 0 && (
        <p style={{ fontSize: '0.85rem', color: '#c00' }}>
          {t('taxation.planShortfall', { amount: formatEUR(plan.shortfall) })}
        </p>
      )}

      <ul style={{ fontSize: '0.78rem', color: '#6A6E73', paddingLeft: '1.1rem', margin: '0.5rem 0 0' }}>
        <li>{t('taxation.planDisclaimerExecution')}</li>
        <li>{t('taxation.planDisclaimerFees')}</li>
        <li>{t('taxation.planDisclaimerRebalancing')}</li>
      </ul>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function TaxPage() {
  const { t } = useTranslation();
  const { portfolioId: portfolioIdStr } = useParams<{ portfolioId: string }>();
  const portfolioId = Number(portfolioIdStr);
  const [addingNew, setAddingNew] = useState(false);
  const [showDetail, setShowDetail] = useState(false);

  const { data: entries = [], isLoading, isError } = useFiscalCarryForwards(portfolioIdStr);
  const { data: currentYearPv } = useFiscalCurrentYearPv(portfolioIdStr);
  const { data: brokers = [] } = useBrokers(portfolioId);
  const brokersById = new Map(brokers.map((b) => [b.id, b]));

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

  // Per-disposal breakdown behind the net figure (already sorted by date desc by the API)
  const pvDetails = currentYearPv?.details ?? [];
  const grossGains = pvDetails.reduce((sum, d) => sum + (d.realized_pv > 0 ? d.realized_pv : 0), 0);
  const grossLosses = pvDetails.reduce((sum, d) => sum + (d.realized_pv < 0 ? d.realized_pv : 0), 0);
  // A net-zero disposal counts as a gain/neutral row, not a loss — every row lands in
  // exactly one of the two sections below.
  const realizedGainsDetails = pvDetails.filter((d) => d.realized_pv >= 0);
  const realizedLossesDetails = pvDetails.filter((d) => d.realized_pv < 0);

  // Currently-held CTO positions sitting at an unrealized loss right now — candidates
  // for year-end tax-loss harvesting. Already sorted worst-first by the API.
  const lossCandidates = currentYearPv?.loss_harvesting_candidates ?? [];

  if (isLoading) {
    return (
      <PageSection hasBodyWrapper={false}>
        <Spinner aria-label={t('taxation.loading')} />
      </PageSection>
    );
  }

  if (isError) {
    return (
      <PageSection hasBodyWrapper={false}>
        <Alert variant="danger" title={t('taxation.loadError')} />
      </PageSection>
    );
  }

  return (
    <PageSection hasBodyWrapper={false}>
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
            {pvDetails.length > 0 && (
              <div style={{
                display: 'flex', justifyContent: 'space-between', maxWidth: 420,
                fontSize: '0.82rem', color: '#6A6E73',
              }}>
                <span>
                  {t('taxation.grossGains')}:{' '}
                  <strong style={{ color: '#137333' }}>+{formatEUR(grossGains)}</strong>
                </span>
                <span>
                  {t('taxation.grossLosses')}:{' '}
                  <strong style={{ color: '#c00' }}>{formatEUR(grossLosses)}</strong>
                </span>
              </div>
            )}
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
          {stockAjuste >= 0 ? (
            <div style={{ marginTop: '0.75rem', padding: '0.5rem', background: '#fff3cd', borderRadius: 4, fontSize: '0.85rem', color: '#856404' }}>
              {t('taxation.taxableGainsAlert', { amount: formatEUR(stockAjuste), year: CURRENT_YEAR })}
            </div>
          ) : (
            <div style={{ marginTop: '0.75rem', padding: '0.5rem', background: '#d4edda', borderRadius: 4, fontSize: '0.85rem', color: '#155724' }}>
              {t('taxation.lossStockAvailableAlert', { amount: formatEUR(Math.abs(stockAjuste)), year: CURRENT_YEAR })}
            </div>
          )}
          <div style={{ marginTop: '0.75rem', fontSize: '0.78rem', color: '#6A6E73' }}>
            {t('taxation.disclaimer')}
          </div>

          <LossHarvestingSection candidates={lossCandidates} brokersById={brokersById} />
          <LossHarvestingPlanSection candidates={lossCandidates} target={stockAjuste} brokersById={brokersById} />

          {pvDetails.length > 0 && (
            <div style={{ marginTop: '1rem' }}>
              <Button
                variant="link"
                isInline
                onClick={() => setShowDetail((s) => !s)}
                style={{ fontSize: '0.82rem' }}
              >
                {showDetail ? t('taxation.hideDetail') : t('taxation.viewDetail')}
              </Button>
              {showDetail && (
                <>
                  {realizedGainsDetails.length > 0 && (
                    <div style={{ marginTop: '0.5rem' }}>
                      <strong style={{ fontSize: '0.85rem', color: '#137333' }}>
                        {t('taxation.realizedGains')}
                      </strong>
                      <DisposalTable rows={realizedGainsDetails} />
                    </div>
                  )}
                  {realizedLossesDetails.length > 0 && (
                    <div style={{ marginTop: '0.5rem' }}>
                      <strong style={{ fontSize: '0.85rem', color: '#c00' }}>
                        {t('taxation.realizedLosses')}
                      </strong>
                      <DisposalTable rows={realizedLossesDetails} />
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </PageSection>
  );
}
