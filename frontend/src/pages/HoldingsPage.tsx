// SPDX-License-Identifier: AGPL-3.0-or-later
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import {
  Badge,
  Card, CardBody, CardTitle,
  Gallery, GalleryItem,
  PageSection, PageSectionVariants,
  Title,
  Tooltip,
} from '@patternfly/react-core';
import { ExclamationTriangleIcon } from '@patternfly/react-icons';
import { Table, Thead, Tbody, Tr, Th, Td, SortByDirection } from '@patternfly/react-table';
import { useState } from 'react';
import { formatEUR, formatPct1, formatPct2, formatUnitPrice, formatNativeCurrency } from '../utils/format';
import { pvColor } from '../utils/pv';
import { INSTRUMENT_TYPE_GOLD } from '../utils/productConstants';
import { useCapitalGains, useDashboard, useHoldings } from '../api/queries';
import type { TickerCapitalGains } from '../types';
import { useSyncStatus } from '../hooks/useSyncStatus';
import SyncBadge from '../components/SyncBadge';
import TickerLink from '../components/TickerLink';
import EtfCompositionModal from '../components/EtfCompositionModal';
import PoolAllocationSection from '../components/PoolAllocationSection';
import { PriceSourceBadge, StalePriceBadge } from '../components/PriceBadges';
import { renderLoadingState, renderErrorState } from '../components/QueryStateGuard';
import {
  groupAndSort,
  UNASSIGNED_POOL_KEY,
} from './holdings.utils';
import type { Holding } from '../types';

// Column indices for holdings table sort
const POS_COL = { ticker: 0, name: 1, qty: 2, price: 3, totalEur: 4, totalNative: 5, pctPool: 6, source: 7, pvLatente: 8, pvLatentePct: 9 } as const;
type PosColIndex = typeof POS_COL[keyof typeof POS_COL];

function PoolHoldingsTable({ holdings, poolName, failedTickers, pvMap }: {
  holdings: Holding[];
  poolName: string;
  failedTickers: Set<string>;
  pvMap: Map<string, TickerCapitalGains>;
}) {
  const { t } = useTranslation();
  // Default sort: by product name (col index 1) ASC — preserves existing behaviour
  const [sortIndex, setSortIndex] = useState<PosColIndex>(POS_COL.name);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [compositionTicker, setCompositionTicker] = useState<string | null>(null);

  const onSort = (_: React.MouseEvent, index: number, direction: SortByDirection) => {
    setSortIndex(index as PosColIndex);
    setSortDir(direction as 'asc' | 'desc');
  };

  const poolTotal = holdings.reduce((sum, h) => sum + h.value_eur, 0);

  const sorted = [...holdings].sort((a, b) => {
    const dir = sortDir === 'asc' ? 1 : -1;
    switch (sortIndex) {
      case POS_COL.ticker:   return a.ticker.localeCompare(b.ticker) * dir;
      case POS_COL.name:     return a.product_name.localeCompare(b.product_name) * dir;
      case POS_COL.totalEur: return (a.value_eur - b.value_eur) * dir;
      case POS_COL.pctPool: {
        const pctA = poolTotal > 0 ? a.value_eur / poolTotal : 0;
        const pctB = poolTotal > 0 ? b.value_eur / poolTotal : 0;
        return (pctA - pctB) * dir;
      }
      case POS_COL.pvLatente: {
        const pvA = pvMap.get(a.ticker)?.unrealized_pv ?? 0;
        const pvB = pvMap.get(b.ticker)?.unrealized_pv ?? 0;
        return (pvA - pvB) * dir;
      }
      case POS_COL.pvLatentePct: {
        const dA = pvMap.get(a.ticker);
        const dB = pvMap.get(b.ticker);
        const pctA = dA && dA.cost_basis_eur !== 0 ? dA.unrealized_pv / dA.cost_basis_eur : 0;
        const pctB = dB && dB.cost_basis_eur !== 0 ? dB.unrealized_pv / dB.cost_basis_eur : 0;
        return (pctA - pctB) * dir;
      }
      default: return 0;
    }
  });

  const sortBy = { index: sortIndex, direction: sortDir as SortByDirection };

  // Pool-level PV subtotals
  const poolPvTotal = holdings.reduce((sum, h) => {
    const d = pvMap.get(h.ticker);
    return sum + (d ? d.unrealized_pv : 0);
  }, 0);
  const poolCostTotal = holdings.reduce((sum, h) => {
    const d = pvMap.get(h.ticker);
    return sum + (d ? d.cost_basis_eur : 0);
  }, 0);
  const hasPvData = holdings.some((h) => pvMap.has(h.ticker));

  return (
    <>
      <Table aria-label={`${t('holdings.table')} ${poolName}`} variant="compact">
        <Thead>
          <Tr>
            <Th sort={{ sortBy, onSort, columnIndex: POS_COL.ticker }}>{t('common.ticker')}</Th>
            <Th sort={{ sortBy, onSort, columnIndex: POS_COL.name }}>{t('positions.productName')}</Th>
            <Th modifier="nowrap">{t('positions.quantity')}</Th>
            <Th modifier="nowrap">{t('positions.lastPrice')}</Th>
            <Th modifier="nowrap" sort={{ sortBy, onSort, columnIndex: POS_COL.totalEur }}>{t('positions.valueEur')}</Th>
            <Th modifier="nowrap">{t('positions.valueNative')}</Th>
            <Th modifier="nowrap" sort={{ sortBy, onSort, columnIndex: POS_COL.pctPool }}>{t('positions.percentPool')}</Th>
            <Th modifier="nowrap">{t('positions.priceSource')}</Th>
            <Th modifier="nowrap" sort={{ sortBy, onSort, columnIndex: POS_COL.pvLatente }}>{t('positions.unrealizedPV')}</Th>
            <Th modifier="nowrap" sort={{ sortBy, onSort, columnIndex: POS_COL.pvLatentePct }}>{t('positions.unrealizedPVPct')}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {sorted.map((h, __idx) => {
            const pctOfPool = poolTotal > 0 ? (h.value_eur / poolTotal) * 100 : 0;
            const currency = h.currency || 'EUR';
            const valueNative =
              currency !== 'EUR' && h.last_price > 0
                ? h.value_eur / h.last_price
                : null;
            const isStale = failedTickers.has(h.ticker);
            const pvData = pvMap.get(h.ticker);
            const unrealizedPv = pvData?.unrealized_pv;
            const costBasis = pvData?.cost_basis_eur;
            const pvPct = pvData && costBasis !== undefined && costBasis !== 0
              ? (pvData.unrealized_pv / costBasis) * 100
              : undefined;

            return (
              <Tr key={h.ticker} style={{ backgroundColor: __idx % 2 === 0 ? '#fff' : '#f5f5f5' }}>
                <Td>
                  <strong>
                    <TickerLink ticker={h.ticker} instrumentType={h.instrument_type} onClick={setCompositionTicker} />
                  </strong>
                  <StalePriceBadge lastPriceDate={h.last_price_date} source={h.last_price_source} />
                </Td>
                <Td>{h.product_name}</Td>
                <Td>
                  {h.instrument_type === INSTRUMENT_TYPE_GOLD ? '—' : h.quantity.toLocaleString('fr-FR', {
                    maximumFractionDigits: 4,
                  })}
                </Td>
                <Td>
                  {h.instrument_type === INSTRUMENT_TYPE_GOLD ? '—' : (
                    <>
                      {formatUnitPrice(h.last_price, currency)}
                      {isStale && h.last_price_date && (
                        <Tooltip content={t('holdings.priceNotUpdated')}>
                          <div style={{ fontSize: '0.78rem', color: '#E65100', display: 'flex', alignItems: 'center', gap: '0.25rem', marginTop: '2px' }}>
                            <ExclamationTriangleIcon style={{ width: '0.85em' }} />
                            {h.last_price_date}
                          </div>
                        </Tooltip>
                      )}
                    </>
                  )}
                </Td>
                <Td>
                  {formatEUR(h.value_eur)}
                  {h.instrument_type === INSTRUMENT_TYPE_GOLD && h.last_price_date && (
                    <div style={{ fontSize: '0.78rem', color: 'var(--pf-t--global--text--color--subtle)', marginTop: '2px' }}>
                      {h.last_price_date}
                    </div>
                  )}
                </Td>
                <Td>
                  {valueNative != null
                    ? formatNativeCurrency(valueNative, currency, 0)
                    : '—'}
                </Td>
                <Td>{formatPct1(pctOfPool)}</Td>
                <Td><PriceSourceBadge source={h.last_price_source} /></Td>
                <Td>
                  {unrealizedPv !== undefined
                    ? <span style={{ color: pvColor(unrealizedPv), fontWeight: 500 }}>
                        {unrealizedPv > 0 ? '+' : ''}{formatEUR(unrealizedPv)}
                      </span>
                    : <span style={{ color: 'var(--pf-t--global--text--color--subtle)' }}>—</span>}
                </Td>
                <Td>
                  {pvPct !== undefined
                    ? <span style={{ color: pvColor(pvPct) }}>
                        {formatPct2(pvPct, true)}
                      </span>
                    : <span style={{ color: 'var(--pf-t--global--text--color--subtle)' }}>—</span>}
                </Td>
              </Tr>
            );
          })}
          {/* Pool PV subtotal row */}
          {hasPvData && (
            <Tr style={{ backgroundColor: '#f0f4ff', fontWeight: 'bold' }}>
              <Td colSpan={8}>
                <span style={{ fontSize: '0.85rem', color: 'var(--pf-t--global--text--color--subtle)' }}>
                  {t('holdings.poolSubtotal')}
                </span>
              </Td>
              <Td>
                <span style={{ color: pvColor(poolPvTotal), fontWeight: 600 }}>
                  {poolPvTotal > 0 ? '+' : ''}{formatEUR(poolPvTotal)}
                </span>
              </Td>
              <Td>
                {poolCostTotal !== 0
                  ? <span style={{ color: pvColor(poolPvTotal) }}>
                      {formatPct2((poolPvTotal / poolCostTotal) * 100, true)}
                    </span>
                  : '—'}
              </Td>
            </Tr>
          )}
        </Tbody>
      </Table>
      <EtfCompositionModal ticker={compositionTicker} onClose={() => setCompositionTicker(null)} />
    </>
  );
}

export default function HoldingsPage() {
  const { t } = useTranslation();
  const { portfolioId } = useParams<{ portfolioId: string }>();

  const {
    data: dashboard,
    isLoading: dashLoading,
    isError: dashError,
  } = useDashboard(portfolioId!);

  const {
    data: holdings,
    isLoading: holdingsLoading,
    isError: holdingsError,
  } = useHoldings(portfolioId!);
  const { data: syncStatus } = useSyncStatus();
  const failedTickers = new Set(syncStatus?.failed_tickers ?? []);

  // Capital gains — portfolio-level (no account filter) for PV columns in pool tables
  const { data: capitalGains } = useCapitalGains(portfolioId!);
  const pvMap = new Map<string, TickerCapitalGains>(
    (capitalGains?.tickers ?? []).map((tg) => [tg.ticker, tg])
  );

  const isLoading = dashLoading || holdingsLoading;
  const isError = dashError || holdingsError;

  if (isLoading) return renderLoadingState(t('common.loading'));
  if (isError || !dashboard || !holdings) return renderErrorState(t('error.loadingPositions'));

  // Separate liquidity from investable holdings
  const investableHoldings = holdings.filter((h) => h.ticker !== 'LIQUIDITE.EURO');
  const groups = groupAndSort(investableHoldings, dashboard.pools);
  const grandTotal = investableHoldings.reduce((sum, h) => sum + h.value_eur, 0);

  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
        <Title headingLevel="h1" size="xl">{t('holdings.currentHoldings')}</Title>
        <SyncBadge />
      </div>

      {/* Cash holdings — shown separately above pool groups */}
      <Card style={{ marginBottom: '1.5rem', borderLeft: '4px solid var(--pf-t--global--color--nonstatus--yellow--400)' }}>
        <CardTitle>{t('dashboard.availableCash')}</CardTitle>
        <CardBody>
          <div style={{ display: 'flex', alignItems: 'center', gap: '2rem' }}>
            <span style={{ fontSize: '1.4rem', fontWeight: 'bold' }}>
              {formatEUR(dashboard.liquidity_eur)}
            </span>
            <span style={{ fontSize: '0.85rem', color: 'var(--pf-t--global--text--color--subtle)' }}>
              {t('holdings.cashNotInvested')}
            </span>
          </div>
        </CardBody>
      </Card>

      {/* KPI cards */}
      <Gallery hasGutter minWidths={{ default: '180px' }} style={{ marginBottom: '2rem' }}>
        <GalleryItem>
          <Card>
            <CardTitle>{t('dashboard.totalPortfolio')}</CardTitle>
            <CardBody>
              <span style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>
                {formatEUR(dashboard.total_eur)}
              </span>
            </CardBody>
          </Card>
        </GalleryItem>
        <GalleryItem>
          <Card>
            <CardTitle>{t('dashboard.offensive')}</CardTitle>
            <CardBody>
              <span style={{ fontSize: '1.3rem', fontWeight: 'bold' }}>
                {formatEUR(dashboard.offensive_eur)}
              </span>
              <div style={{ fontSize: '0.9rem', color: 'var(--pf-t--global--text--color--subtle)' }}>
                {dashboard.total_eur > 0
                  ? formatPct1(dashboard.offensive_eur / dashboard.total_eur * 100)
                  : '–'}
              </div>
            </CardBody>
          </Card>
        </GalleryItem>
        <GalleryItem>
          <Card>
            <CardTitle>{t('dashboard.defensive')}</CardTitle>
            <CardBody>
              <span style={{ fontSize: '1.3rem', fontWeight: 'bold' }}>
                {formatEUR(dashboard.defensive_eur)}
              </span>
              <div style={{ fontSize: '0.9rem', color: 'var(--pf-t--global--text--color--subtle)' }}>
                {dashboard.total_eur > 0
                  ? formatPct1(dashboard.defensive_eur / dashboard.total_eur * 100)
                  : '–'}
              </div>
            </CardBody>
          </Card>
        </GalleryItem>
        <GalleryItem>
          <Card>
            <CardTitle>{t('holdings.investedHoldings')}</CardTitle>
            <CardBody>
              <span style={{ fontSize: '1.3rem', fontWeight: 'bold' }}>
                {formatEUR(grandTotal)}
              </span>
            </CardBody>
          </Card>
        </GalleryItem>
      </Gallery>

      {/* One section per pool */}
      {groups.map((group) => {
        if (group.holdings.length === 0) return null;

        const poolTotal = group.holdings.reduce((sum, h) => sum + h.value_eur, 0);
        // Translate the unassigned sentinel key to a UI label
        /* v8 ignore next -- @preserve */
        const displayName = group.poolName === UNASSIGNED_POOL_KEY
          ? t('holdings.unassigned')
          : group.poolName;

        return (
          <Card key={group.poolName} style={{ marginBottom: '1.5rem' }}>
            <CardTitle>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <span>{displayName}</span>
                {group.pool && (
                  <Badge
                    style={{
                      backgroundColor:
                        group.pool.strategy === 'Offensive'
                          ? 'var(--pf-t--global--color--nonstatus--blue--200)'
                          : 'var(--pf-t--global--color--nonstatus--green--200)',
                      color: 'var(--pf-t--global--text--color--regular)',
                    }}
                  >
                    {group.pool.strategy}
                  </Badge>
                )}
                <span style={{ marginLeft: 'auto', fontWeight: 'normal', fontSize: '0.95rem' }}>
                  {formatEUR(poolTotal)}
                  {group.pool && (
                    <span style={{ marginLeft: '0.5rem', color: 'var(--pf-t--global--text--color--subtle)' }}>
                      · {t('holdings.target')} {formatPct1(group.pool.target_pct * 100)} · {t('holdings.actual')}{' '}
                      {formatPct1(group.pool.current_pct)}
                    </span>
                  )}
                </span>
              </div>
            </CardTitle>
            <CardBody>
              <PoolHoldingsTable
                holdings={group.holdings}
                poolName={displayName}
                failedTickers={failedTickers}
                pvMap={pvMap}
              />
              {group.pool && (
                <PoolAllocationSection portfolioId={portfolioId!} poolId={group.pool.id} />
              )}
            </CardBody>
          </Card>
        );
      })}

      {/* Grand total footer */}
      <Card>
        <CardBody>
          <div
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              alignItems: 'center',
              gap: '1rem',
            }}
          >
            <strong>{t('holdings.totalHoldings')}</strong>
            <span style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>
              {formatEUR(grandTotal)}
            </span>
          </div>
        </CardBody>
      </Card>
    </PageSection>
  );
}
