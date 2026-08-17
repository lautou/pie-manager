import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import {
  Card, CardBody, CardTitle,
  Grid, GridItem,
  Label,
  PageSection, PageSectionVariants,
  Spinner, Content, ContentVariants, Title,
  Tooltip,
} from '@patternfly/react-core';
import { ExclamationTriangleIcon } from '@patternfly/react-icons';
import { Table, Thead, Tbody, Tr, Th, Td, SortByDirection } from '@patternfly/react-table';
import { formatEUR, formatPct2, formatUnitPrice } from '../utils/format';
import { useAccountsSummary, useCapitalGains } from '../api/queries';
import SyncBadge from '../components/SyncBadge';
import TickerLink from '../components/TickerLink';
import EtfCompositionModal from '../components/EtfCompositionModal';
import { StalePriceBadge } from './HoldingsPage';
import type { AccountPosition, AccountSummary } from '../types';

// Fallback colors by account name (used when account.color is not set in DB)
const ACCOUNT_COLOR_FB: Record<string, string> = {
  'BourseDirect PEA': '#0066CC',
  'Degiro':           '#F0AB00',
  'auCoffre.com':     '#B8860B',
  'Revolut':          '#3E8635',
  'IBKR':             '#8A8D90',
};
const getAccountColor = (account: { name: string; color?: string | null }): string =>
  account.color ?? ACCOUNT_COLOR_FB[account.name] ?? '#6A6E73';

function PriceSourceBadge({ source }: { source: string }) {
  const { t } = useTranslation();
  if (source === 'manual') {
    return (
      <Label color="orange" style={{ gap: '0.25rem' }}>
        <Tooltip content={t('positions.manualPriceTooltip')}>
          <ExclamationTriangleIcon style={{ cursor: 'pointer' }} />
        </Tooltip>
        manual
      </Label>
    );
  }
  return <Label color="blue">{source}</Label>;
}

// Column indices for summary table
const SUMM_COL = { name: 0, cash: 1, positions: 2, total: 3, pct: 4 } as const;
type SummColIndex = typeof SUMM_COL[keyof typeof SUMM_COL];

// Column indices for per-account detail table
const ACC_COL = { ticker: 0, name: 1, qty: 2, price: 3, native: 4, totalEur: 5, pvEur: 6, pvPct: 7, source: 8 } as const;
type AccColIndex = typeof ACC_COL[keyof typeof ACC_COL];

function pvColor(val: number): string {
  if (val > 0) return '#137333';
  if (val < 0) return '#C9190B';
  return "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--Color--200 */;
}

function computePV(pos: AccountPosition, cump: number | undefined): { pvEur: number; pvPct: number } | null {
  if (!cump || cump === 0 || pos.category === 'Frais') return null;
  const costBasis = Math.abs(pos.quantity) * cump;
  if (costBasis === 0) return null;
  const pvEur = pos.value_eur - costBasis;
  return { pvEur, pvPct: (pvEur / costBasis) * 100 };
}

// ── Per-account card with its own CUMP (per account_id) ───────────────────────

function AccountDetailCard({
  account, portfolioId, accSortIndex, accSortDir, accSortBy, onAccSort,
}: {
  account: AccountSummary;
  portfolioId: string;
  accSortIndex: AccColIndex;
  accSortDir: 'asc' | 'desc';
  accSortBy: { index: number; direction: SortByDirection };
  onAccSort: (_: React.MouseEvent, index: number, direction: SortByDirection) => void;
}) {
  const { t } = useTranslation();
  const [compositionTicker, setCompositionTicker] = useState<string | null>(null);
  // Per-account capital gains → per-account CUMP (not the global one)
  const { data: perAccountGains } = useCapitalGains(portfolioId, account.id);

  const cumpMap: Record<string, number> = {};
  for (const t of perAccountGains?.tickers ?? []) {
    cumpMap[t.ticker] = t.cump;
  }

  const accountPV = account.positions.reduce((sum, pos) => {
    const pv = computePV(pos, cumpMap[pos.ticker]);
    return sum + (pv?.pvEur ?? 0);
  }, 0);
  const hasPV = account.positions.some((pos) => computePV(pos, cumpMap[pos.ticker]) !== null);

  return (
    <Card
      style={{
        marginBottom: '1.5rem',
        borderLeft: `4px solid ${getAccountColor(account)}`,
      }}
    >
      <CardTitle>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 'bold' }}>{account.name}</span>
          <span style={{ marginLeft: 'auto', fontWeight: 'normal', fontSize: '0.95rem', color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--Color--200 */ }}>
            {t('accountsSummary.cashLabel')} : {formatEUR(account.cash_balance_eur)}
            &nbsp;·&nbsp;
            {t('accountsSummary.securitiesLabel')} : {formatEUR(account.positions_value_eur)}
            &nbsp;·&nbsp;
            <strong style={{ color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--Color--100 */ }}>
              {t('accountsSummary.totalLabel')} : {formatEUR(account.total_eur)}
            </strong>
            {hasPV && (
              <>
                &nbsp;·&nbsp;
                <span style={{ color: pvColor(accountPV), fontWeight: 600 }}>
                  {t('accountsSummary.pvLabel')} : {accountPV > 0 ? '+' : ''}{formatEUR(accountPV)}
                </span>
              </>
            )}
          </span>
        </div>
      </CardTitle>
      <CardBody>
        {account.positions.length === 0 ? (
          <Content>
            <Content component={ContentVariants.p} style={{ color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--Color--200 */, fontStyle: 'italic' }}>
              {t('accountsSummary.noPositions')}
            </Content>
          </Content>
        ) : (
          <Table aria-label={`Positions ${account.name}`} variant="compact">
            <Thead>
              <Tr>
                <Th sort={{ sortBy: accSortBy, onSort: onAccSort, columnIndex: ACC_COL.ticker }}>{t('common.ticker')}</Th>
                <Th sort={{ sortBy: accSortBy, onSort: onAccSort, columnIndex: ACC_COL.name }}>{t('positions.productName')}</Th>
                <Th modifier="nowrap">{t('common.quantity')}</Th>
                <Th modifier="nowrap">{t('positions.lastPrice')}</Th>
                <Th modifier="nowrap">{t('positions.valueNative')}</Th>
                <Th modifier="nowrap" sort={{ sortBy: accSortBy, onSort: onAccSort, columnIndex: ACC_COL.totalEur }}>{t('positions.valueEur')}</Th>
                <Th modifier="nowrap" sort={{ sortBy: accSortBy, onSort: onAccSort, columnIndex: ACC_COL.pvEur }}>{t('dashboard.unrealizedPV')}</Th>
                <Th modifier="nowrap" sort={{ sortBy: accSortBy, onSort: onAccSort, columnIndex: ACC_COL.pvPct }}>{t('accountsSummary.pvPct')}</Th>
                <Th modifier="nowrap">{t('accountsSummary.source')}</Th>
              </Tr>
            </Thead>
            <Tbody>
              {[...account.positions].sort((a, b) => {
                const dir = accSortDir === 'asc' ? 1 : -1;
                const pvA = computePV(a, cumpMap[a.ticker])?.pvEur ?? -Infinity;
                const pvB = computePV(b, cumpMap[b.ticker])?.pvEur ?? -Infinity;
                const pctA = computePV(a, cumpMap[a.ticker])?.pvPct ?? -Infinity;
                const pctB = computePV(b, cumpMap[b.ticker])?.pvPct ?? -Infinity;
                switch (accSortIndex) {
                  case ACC_COL.ticker:   return a.ticker.localeCompare(b.ticker) * dir;
                  case ACC_COL.name:     return a.product_name.localeCompare(b.product_name) * dir;
                  case ACC_COL.totalEur: return (a.value_eur - b.value_eur) * dir;
                  case ACC_COL.pvEur:    return (pvA - pvB) * dir;
                  case ACC_COL.pvPct:    return (pctA - pctB) * dir;
                  /* v8 ignore next -- @preserve */
                  default: return 0;
                }
              }).map((pos, idx) => {
                const pv = computePV(pos, cumpMap[pos.ticker]);
                return (
                  <Tr key={pos.ticker} style={{ backgroundColor: idx % 2 === 0 ? '#fff' : '#f5f5f5' }}>
                    <Td style={{ paddingLeft: '0.5rem' }}>
                      <strong>
                        <TickerLink ticker={pos.ticker} instrumentType={pos.instrument_type} onClick={setCompositionTicker} />
                      </strong>
                      <StalePriceBadge lastPriceDate={pos.last_price_date} source={pos.last_price_source} />
                    </Td>
                    <Td>{pos.product_name}</Td>
                    <Td>
                      {pos.instrument_type === 'Or physique'
                        ? '—'
                        : pos.quantity.toLocaleString('fr-FR', { maximumFractionDigits: 4 })}
                    </Td>
                    <Td>
                      {pos.instrument_type === 'Or physique' ? '—' : (
                        formatUnitPrice(pos.last_price, pos.currency || 'EUR')
                      )}
                    </Td>
                    <Td>
                      {pos.currency !== 'EUR' && pos.last_price > 0 && pos.instrument_type !== 'Or physique'
                        ? new Intl.NumberFormat('fr-FR', {
                            minimumFractionDigits: 0,
                            maximumFractionDigits: 0,
                          }).format(pos.value_eur / pos.last_price) + ' ' + pos.currency
                        : '—'}
                    </Td>
                    <Td>
                      {formatEUR(pos.value_eur)}
                      {pos.instrument_type === 'Or physique' && pos.last_price_date && (
                        <div style={{ fontSize: '0.8rem', color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--Color--200 */ }}>
                          {pos.last_price_date}
                        </div>
                      )}
                    </Td>
                    <Td>
                      {pv !== null ? (
                        <span style={{ color: pvColor(pv.pvEur), fontWeight: 500 }}>
                          {pv.pvEur > 0 ? '+' : ''}{formatEUR(pv.pvEur)}
                        </span>
                      ) : <span style={{ color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--Color--200 */ }}>—</span>}
                    </Td>
                    <Td>
                      {pv !== null ? (
                        <span style={{ color: pvColor(pv.pvPct) }}>
                          {formatPct2(pv.pvPct, true)}
                        </span>
                      ) : <span style={{ color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--Color--200 */ }}>—</span>}
                    </Td>
                    <Td>
                      <PriceSourceBadge source={pos.last_price_source} />
                    </Td>
                  </Tr>
                );
              })}
            </Tbody>
          </Table>
        )}
      </CardBody>
      <EtfCompositionModal ticker={compositionTicker} onClose={() => setCompositionTicker(null)} />
    </Card>
  );
}

export default function AccountsSummaryPage() {
  const { t } = useTranslation();
  const { portfolioId } = useParams<{ portfolioId: string }>();
  const { data: summaries, isLoading, isError } = useAccountsSummary(portfolioId!);

  // Summary table sort state
  const [summSortIndex, setSummSortIndex] = useState<SummColIndex>(SUMM_COL.name);
  const [summSortDir, setSummSortDir] = useState<'asc' | 'desc'>('asc');

  const onSummSort = (_: React.MouseEvent, index: number, direction: SortByDirection) => {
    setSummSortIndex(index as SummColIndex);
    setSummSortDir(direction as 'asc' | 'desc');
  };

  // Per-account detail table sort state (shared — same columns for all accounts)
  const [accSortIndex, setAccSortIndex] = useState<AccColIndex>(ACC_COL.ticker);
  const [accSortDir, setAccSortDir] = useState<'asc' | 'desc'>('asc');

  const onAccSort = (_: React.MouseEvent, index: number, direction: SortByDirection) => {
    setAccSortIndex(index as AccColIndex);
    setAccSortDir(direction as 'asc' | 'desc');
  };

  if (isLoading) {
    return (
      <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
          <Spinner size="xl" />
        </div>
      </PageSection>
    );
  }

  if (isError || !summaries) {
    return (
      <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
        <Content>
          <Content component={ContentVariants.p} style={{ color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--danger-color--100 */ }}>
            {t('accountsSummary.loadError')}
          </Content>
        </Content>
      </PageSection>
    );
  }

  const grandTotalCash = summaries.reduce((s, a) => s + a.cash_balance_eur, 0);
  const grandTotalPositions = summaries.reduce((s, a) => s + a.positions_value_eur, 0);
  const grandTotal = summaries.reduce((s, a) => s + a.total_eur, 0);

  // Sort summaries for the summary table
  const sortedSummaries = [...summaries].sort((a, b) => {
    const dir = summSortDir === 'asc' ? 1 : -1;
    switch (summSortIndex) {
      case SUMM_COL.name:      return a.name.localeCompare(b.name) * dir;
      case SUMM_COL.cash:      return (a.cash_balance_eur - b.cash_balance_eur) * dir;
      case SUMM_COL.positions: return (a.positions_value_eur - b.positions_value_eur) * dir;
      case SUMM_COL.total:     return (a.total_eur - b.total_eur) * dir;
      case SUMM_COL.pct: {
        const pA = grandTotal > 0 ? a.total_eur / grandTotal : 0;
        const pB = grandTotal > 0 ? b.total_eur / grandTotal : 0;
        return (pA - pB) * dir;
      }
      /* v8 ignore next -- @preserve */
      default: return 0; // TypeScript exhaustive switch — unreachable
    }
  });

  const summSortBy = { index: summSortIndex, direction: summSortDir as SortByDirection };
  const accSortBy  = { index: accSortIndex,  direction: accSortDir  as SortByDirection };

  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
        <Title headingLevel="h1" size="xl">{t('accountsSummary.pageTitle')}</Title>
        <SyncBadge />
      </div>

      {/* ── KPI globaux ── */}
      <Grid hasGutter style={{ marginBottom: '1.5rem' }}>
        <GridItem span={4}>
          <Card>
            <CardTitle>{t('dashboard.totalPortfolio')}</CardTitle>
            <CardBody>
              <span style={{ fontSize: '1.6rem', fontWeight: 'bold' }}>{formatEUR(grandTotal)}</span>
            </CardBody>
          </Card>
        </GridItem>
        <GridItem span={4}>
          <Card>
            <CardTitle>{t('accountsSummary.totalCash')}</CardTitle>
            <CardBody>
              <span style={{ fontSize: '1.3rem', fontWeight: 'bold' }}>{formatEUR(grandTotalCash)}</span>
            </CardBody>
          </Card>
        </GridItem>
        <GridItem span={4}>
          <Card>
            <CardTitle>{t('accountsSummary.totalSecurities')}</CardTitle>
            <CardBody>
              <span style={{ fontSize: '1.3rem', fontWeight: 'bold' }}>{formatEUR(grandTotalPositions)}</span>
            </CardBody>
          </Card>
        </GridItem>
      </Grid>

      {/* ── Tableau récapitulatif ── */}
      <Card style={{ marginBottom: '1.5rem' }}>
        <CardTitle>{t('accountsSummary.summaryByAccount')}</CardTitle>
        <CardBody>
          <Table aria-label={t('accountsSummary.summaryByAccount')} variant="compact">
            <Thead>
              <Tr>
                <Th sort={{ sortBy: summSortBy, onSort: onSummSort, columnIndex: SUMM_COL.name }}>{t('common.account')}</Th>
                <Th modifier="nowrap" sort={{ sortBy: summSortBy, onSort: onSummSort, columnIndex: SUMM_COL.cash }}>{t('accountsSummary.cash')}</Th>
                <Th modifier="nowrap" sort={{ sortBy: summSortBy, onSort: onSummSort, columnIndex: SUMM_COL.positions }}>{t('accountsSummary.securities')}</Th>
                <Th modifier="nowrap" sort={{ sortBy: summSortBy, onSort: onSummSort, columnIndex: SUMM_COL.total }}>{t('accountsSummary.total')}</Th>
                <Th modifier="nowrap" sort={{ sortBy: summSortBy, onSort: onSummSort, columnIndex: SUMM_COL.pct }}>{t('accountsSummary.pctOfTotal')}</Th>
              </Tr>
            </Thead>
            <Tbody>
              {sortedSummaries.map((account) => (
                <Tr key={account.id}>
                  <Td>
                    <span style={{
                      display: 'inline-block', width: 10, height: 10,
                      borderRadius: '50%',
                      backgroundColor: getAccountColor(account),
                      marginRight: 6,
                    }} />
                    <strong>{account.name}</strong>
                  </Td>
                  <Td>{formatEUR(account.cash_balance_eur)}</Td>
                  <Td>{formatEUR(account.positions_value_eur)}</Td>
                  <Td style={{ fontWeight: 'bold' }}>{formatEUR(account.total_eur)}</Td>
                  <Td style={{ color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--Color--200 */ }}>
                    {grandTotal > 0
                      ? (account.total_eur / grandTotal * 100).toLocaleString('fr-FR', {
                          minimumFractionDigits: 1,
                          maximumFractionDigits: 1,
                        }) + ' %'
                      : '—'}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardBody>
      </Card>

      {/* ── Détail par compte — CUMP calculé par compte via useCapitalGains(portfolioId, account.id) ── */}
      {summaries.map((account) => (
        <AccountDetailCard
          key={account.id}
          account={account}
          portfolioId={portfolioId!}
          accSortIndex={accSortIndex}
          accSortDir={accSortDir}
          accSortBy={accSortBy}
          onAccSort={onAccSort}
        />
      ))}
    </PageSection>
  );
}
