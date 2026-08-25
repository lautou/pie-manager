// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useNavigate } from 'react-router-dom';
import {
	Alert,
	Button,
	Card,
	CardBody,
	CardTitle,
	EmptyState,
	EmptyStateBody,
	Grid,
	GridItem,
	Modal,
	ModalBody,
	ModalHeader,
	ModalVariant,
	PageSection,
	PageSectionVariants,
	Spinner,
	Content,
	ContentVariants,
	Title
} from '@patternfly/react-core';
import { CogIcon, ImportIcon } from '@patternfly/react-icons';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';
import {
	ChartDonut,
	ChartThemeColor
} from '@patternfly/react-charts/victory';
import { Treemap, ResponsiveContainer } from 'recharts';
import { formatEUR, formatPct1, formatUnitPrice, localDateStr } from '../utils/format';
import { INSTRUMENT_TYPE_GOLD } from '../utils/productConstants';
import { renderLoadingState, renderErrorState } from '../components/QueryStateGuard';
import { useCapitalGains, useDashboard, useHoldings, useProducts, usePrices } from '../api/queries';
import type { Product } from '../types';
import SyncBadge from '../components/SyncBadge';
import TickerLink from '../components/TickerLink';
import EtfCompositionModal from '../components/EtfCompositionModal';



const STALE_DAYS = 30;

/** Returns how many calendar days ago `dateStr` (YYYY-MM-DD) is, relative to today. */
function daysSince(dateStr: string): number {
  const todayStr = localDateStr();
  const todayMs = new Date(todayStr).getTime();
  const priceMs = new Date(dateStr).getTime();
  return Math.floor((todayMs - priceMs) / (1000 * 60 * 60 * 24));
}

/**
 * One sub-component per Manuel product so each can call usePrices() unconditionally.
 * Reports staleness to parent via onStale/onFresh callbacks after data loads.
 */
function ManuelProductStalenessCheck({
  product,
  onStale,
  onFresh,
}: {
  product: Product;
  onStale: (name: string) => void;
  onFresh: (name: string) => void;
}) {
  const { data: prices } = usePrices(product.ticker);

  useEffect(() => {
    // prices===undefined means still loading — don't flag yet
    if (prices === undefined) return;

    const latestDate = prices.length > 0 ? prices[0].date : null;
    const isStale = !latestDate || daysSince(latestDate) > STALE_DAYS;

    if (isStale) {
      onStale(product.name);
    } else {
      onFresh(product.name);
    }
  }, [prices, product.name, onStale, onFresh]);

  return null;
}

/**
 * Fetches prices for every Manuel product and shows a warning Alert listing
 * those whose latest price is absent or older than 30 days.
 */
function StalePriceWarning({ manuelProducts }: { manuelProducts: Product[] }) {
  const { t } = useTranslation();
  const [staleNames, setStaleNames] = useState<string[]>([]);

  // useCallback + early return on same-value prevent infinite re-render:
  // filter() always returns a new array ref even when unchanged, causing
  // ManuelProductStalenessCheck's useEffect to re-fire on every render.
  const handleStale = useCallback((name: string) => {
    /* v8 ignore next -- @preserve */
    setStaleNames((prev) => prev.includes(name) ? prev : [...prev, name]);
  }, []);

  const handleFresh = useCallback((name: string) => {
    setStaleNames((prev) => {
      const idx = prev.indexOf(name);
      return idx === -1 ? prev : prev.filter((n) => n !== name);
    });
  }, []);

  return (
    <>
      {manuelProducts.map((p) => (
        <ManuelProductStalenessCheck
          key={p.ticker}
          product={p}
          onStale={handleStale}
          onFresh={handleFresh}
        />
      ))}
      {staleNames.length > 0 && (
        <Alert
          variant="warning"
          isInline
          title={t('dashboard.stalePriceWarning', { days: STALE_DAYS, names: staleNames.join(', ') })}
          style={{ marginBottom: '1rem' }}
        />
      )}
    </>
  );
}

// Fallback colors by pool name (used when pool.color is not set in DB)
const POOL_COLORS: Record<string, string> = {
  Asie:    '#0066CC',
  Energie: '#F0AB00',
  Or:      '#B8860B',
  Yen:     '#3E8635',
  Legacy:  '#8A8D90',
};

/** Resolve pool color: DB color takes priority over hardcoded fallback */
export const getPoolColor = (name: string, pools?: { name: string; color?: string | null }[]) => {
  const pool = pools?.find(p => p.name === name);
  return pool?.color ?? POOL_COLORS[name] ?? '#6A6E73';
};

// Lighter shades for assets within each pool
const POOL_LIGHT: Record<string, string[]> = {
  Asie:    ['#4394E5','#6BA5E8','#8FB9EB','#B3CDF0','#D3E3F7'],
  Energie: ['#F5BE40','#F7CA60','#F9D880','#FBE5A0','#FDF0C0'],
  Or:      ['#C8960C','#D4A420','#DEB240','#E8C060','#F0D080'],
  Yen:     ['#5BA347','#75B263','#8FC27F','#A9D29B','#C3E2B7'],
  Legacy:  ['#A0A3A8','#B0B3B8','#C0C3C8','#D0D3D8'],
};

interface TreemapNode {
  name: string;
  value?: number;
  pool?: string;
  poolColor?: string;
  pct?: number;
  children?: TreemapNode[];
  [key: string]: unknown;
}

export function TreemapContent(props: {
  x: number; y: number; width: number; height: number;
  name: string; value: number; depth: number; pool?: string; poolColor?: string; pct?: number;
  index: number; root?: { children?: TreemapNode[] };
}) {
  const { x, y, width, height, name, value, depth, pool, poolColor: propPoolColor, pct, index } = props;
  /* v8 ignore next -- @preserve */
  if (width < 10 || height < 10) return null;

  /* v8 ignore next -- @preserve */
  const poolColor = propPoolColor ?? (pool ? (POOL_COLORS[pool] ?? '#6A6E73') : '#6A6E73');
  /* v8 ignore next -- @preserve */
  const lightColors = pool ? (POOL_LIGHT[pool] ?? ['#AAA']) : ['#AAA'];
  const fill = depth === 1 ? poolColor : lightColors[index % lightColors.length];
  const textColor = depth === 1 ? '#fff' : '#222';
  const fontSize = depth === 1 ? 13 : Math.max(9, Math.min(12, width / 8));

  return (
    <g>
      <rect
        x={x + 1} y={y + 1}
        width={width - 2} height={height - 2}
        fill={fill}
        rx={3}
        style={{ cursor: depth === 2 ? 'pointer' : 'default' }}
      />
      {width > 40 && height > 20 && (
        <>
          <text
            x={x + width / 2} y={y + height / 2 - (depth === 2 && height > 36 ? 8 : 0)}
            textAnchor="middle" dominantBaseline="middle"
            fill={textColor} fontSize={fontSize} fontWeight={depth === 1 ? 'bold' : 'normal'}
            style={{ pointerEvents: 'none' }}
          >
            {/* v8 ignore next -- @preserve */}
            {width > 60 ? name : name.slice(0, Math.floor(width / 7))}
          </text>
          {depth === 2 && height > 36 && (
            <text
              x={x + width / 2} y={y + height / 2 + 10}
              textAnchor="middle" dominantBaseline="middle"
              fill={textColor} fontSize={Math.max(8, fontSize - 1)}
              style={{ pointerEvents: 'none' }}
            >
              {/* v8 ignore next -- @preserve */}
              {pct !== undefined ? `${formatPct1(pct).replace(" %","")}` : formatEUR(value)}
            </text>
          )}
        </>
      )}
    </g>
  );
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { portfolioId } = useParams<{ portfolioId: string }>();
  const { data: dashboard, isLoading, isError } = useDashboard(portfolioId!);
  const { data: holdings } = useHoldings(portfolioId!);
  const { data: products } = useProducts();
  const { data: capitalGains, isLoading: cgLoading } = useCapitalGains(portfolioId!);
  const [selectedPool, setSelectedPool] = useState<string | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [compositionTicker, setCompositionTicker] = useState<string | null>(null);

  // Scope to this portfolio's actual holdings (issue #75) — the global product catalog has
  // exactly one OR.PHYSIQUE row shared across every portfolio, so filtering it alone showed
  // the stale-price banner for every portfolio regardless of whether it ever held physical gold.
  const heldTickers = new Set((holdings ?? []).map((h) => h.ticker));
  const manuelProducts = (products ?? []).filter(
    (p) => p.instrument_type === INSTRUMENT_TYPE_GOLD && heldTickers.has(p.ticker),
  );

  if (isLoading) return renderLoadingState(t('common.loading'));

  if (isError) return renderErrorState(t('error.loadingDashboard'));

  if (!dashboard || dashboard.pools.length === 0) {
    return (
      <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
        <EmptyState titleText={<Title headingLevel="h2" size="lg">{t('dashboard.onboardingTitle')}</Title>}>
          <EmptyStateBody>
            {t('dashboard.onboardingBody')}
          </EmptyStateBody>
          <Button variant="primary" icon={<CogIcon />}
            onClick={() => navigate(`/portfolio/${portfolioId}/admin`)}>
            {t('dashboard.onboardingConfigureButton')}
          </Button>
          <div style={{ marginTop: '1rem' }}>
            <Button variant="link" icon={<ImportIcon />}
              onClick={() => navigate(`/portfolio/${portfolioId}/import`)}>
              {t('dashboard.onboardingImportButton')}
            </Button>
          </div>
        </EmptyState>
      </PageSection>
    );
  }

  const activePools = dashboard.pools.filter(
    (p) => p.name !== 'Legacy' || p.current_value_eur > 0
  );

  // Donut data
  const donutData = activePools.map((p) => ({
    x: `${p.name} (${formatPct1(p.current_pct)})`,
    y: p.current_value_eur,
  }));
  const donutColors = activePools.map((p) => getPoolColor(p.name, activePools));

  // Treemap data: pools as parents, assets as children
  const treemapData: TreemapNode[] = activePools
    .filter((p) => p.current_value_eur > 0)
    .map((pool) => {
      /* v8 ignore next -- @preserve */
      const poolPositions = (holdings ?? [])
        .filter((pos) => pos.pool_name === pool.name && pos.value_eur > 0);
      const pc = getPoolColor(pool.name, activePools);
      return {
        name: pool.name,
        pool: pool.name,
        poolColor: pc,
        children: poolPositions.length > 0
          ? poolPositions.map((pos) => ({
              name: pos.ticker,
              value: pos.value_eur,
              pool: pool.name,
              poolColor: pc,
              /* v8 ignore next -- @preserve */
              pct: pool.current_value_eur > 0
                ? (pos.value_eur / dashboard.total_eur) * 100
                : 0,
            }))
          : [{ name: pool.name, value: pool.current_value_eur, pool: pool.name, poolColor: pc, pct: pool.current_pct }],
      };
    });

  const offPct = dashboard.total_eur > 0
    ? formatPct1(dashboard.offensive_eur / dashboard.total_eur * 100)
    : '0,0 %';
  const defPct = dashboard.total_eur > 0
    ? formatPct1(dashboard.defensive_eur / dashboard.total_eur * 100)
    : '0,0 %';

  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.5rem' }}>
        <Title headingLevel="h1" size="xl">{t('dashboard.title')}</Title>
        <SyncBadge />
      </div>
      {manuelProducts.length > 0 && <StalePriceWarning manuelProducts={manuelProducts} />}
      {dashboard.last_updated && (
        <Content style={{ marginBottom: '1rem' }}>
          <Content component={ContentVariants.small}>
            {t('dashboard.snapshotDate', { date: dashboard.last_updated })}
          </Content>
        </Content>
      )}

      {/* ── Row 1 : KPI cards ── */}
      <Grid hasGutter style={{ marginBottom: '1.5rem' }}>
        {[
          { label: t('dashboard.totalPortfolio'), val: formatEUR(dashboard.total_eur), sub: '', big: true },
          { label: t('dashboard.offensive'), val: formatEUR(dashboard.offensive_eur), sub: offPct, big: false },
          { label: t('dashboard.defensive'), val: formatEUR(dashboard.defensive_eur), sub: defPct, big: false },
          { label: t('dashboard.availableCash'), val: formatEUR(dashboard.liquidity_eur), sub: '', big: false },
        ].map(({ label, val, sub, big }) => (
          <GridItem span={3} key={label}>
            <Card>
              <CardTitle>{label}</CardTitle>
              <CardBody>
                <span style={{ fontSize: big ? '1.6rem' : '1.3rem', fontWeight: 'bold' }}>{val}</span>
                {sub && <span style={{ marginLeft: 8, color: '#6A6E73', fontSize: '0.9rem' }}>{sub}</span>}
              </CardBody>
            </Card>
          </GridItem>
        ))}
      </Grid>

      {/* ── Row 1b : PV KPI cards ── */}
      {cgLoading ? (
        <Grid hasGutter style={{ marginBottom: '1.5rem' }}>
          <GridItem span={3}>
            <Card>
              <CardTitle>{t('dashboard.unrealizedPV')}</CardTitle>
              <CardBody><Spinner size="sm" /></CardBody>
            </Card>
          </GridItem>
          <GridItem span={3}>
            <Card>
              <CardTitle>{t('dashboard.realizedPV')}</CardTitle>
              <CardBody><Spinner size="sm" /></CardBody>
            </Card>
          </GridItem>
        </Grid>
      ) : capitalGains ? (
        <Grid hasGutter style={{ marginBottom: '1.5rem' }}>
          <GridItem span={3}>
            <Card>
              <CardTitle>{t('dashboard.unrealizedPV')}</CardTitle>
              <CardBody>
                <span style={{
                  fontSize: '1.3rem', fontWeight: 'bold',
                  color: capitalGains.total_unrealized_pv > 0
                    ? 'var(--pf-t--global--text--color--status--success--default)'
                    : capitalGains.total_unrealized_pv < 0
                    ? 'var(--pf-t--global--text--color--status--danger--default)'
                    : undefined,
                }}>
                  {capitalGains.total_unrealized_pv > 0 ? '+' : ''}
                  {formatEUR(capitalGains.total_unrealized_pv)}
                </span>
              </CardBody>
            </Card>
          </GridItem>
          <GridItem span={3}>
            <Card>
              <CardTitle>{t('dashboard.realizedPV')}</CardTitle>
              <CardBody>
                <span style={{
                  fontSize: '1.3rem', fontWeight: 'bold',
                  color: capitalGains.total_realized_pv > 0
                    ? 'var(--pf-t--global--text--color--status--success--default)'
                    : capitalGains.total_realized_pv < 0
                    ? 'var(--pf-t--global--text--color--status--danger--default)'
                    : undefined,
                }}>
                  {capitalGains.total_realized_pv > 0 ? '+' : ''}
                  {formatEUR(capitalGains.total_realized_pv)}
                </span>
              </CardBody>
            </Card>
          </GridItem>
        </Grid>
      ) : null}

      {/* ── Row 2 : Donut + Treemap ── */}
      <Grid hasGutter style={{ marginBottom: '1.5rem' }}>

        {/* Donut — 4/12 */}
        <GridItem span={4}>
          <Card style={{ height: 320 }}>
            <CardTitle>{t('dashboard.allocationByStrategy')}</CardTitle>
            <CardBody style={{ display: 'flex', justifyContent: 'center' }}>
              <ChartDonut
                data={donutData}
                colorScale={donutColors}
                height={260}
                width={380}
                innerRadius={70}
                labels={({ datum }) => `${datum.x}\n${formatEUR(datum.y)}`}
                legendData={donutData.map((d, i) => ({
                  name: d.x,
                  symbol: { fill: donutColors[i] },
                }))}
                legendOrientation="vertical"
                legendPosition="right"
                padding={{ bottom: 10, left: 10, right: 140, top: 10 }}
                subTitle={t('dashboard.allocation')}
                title={`${activePools.length} ${t('dashboard.pools')}`}
                themeColor={ChartThemeColor.multi}
                events={[{
                  target: 'data',
                  eventHandlers: {
                    onClick: (_evt: React.SyntheticEvent, props: { datum?: { x?: string } }) => {
                      const poolName = props.datum?.x?.split(' (')[0];
                      if (poolName) setSelectedPool(poolName);
                      return [];
                    },
                    onMouseOver: () => [{ target: 'data', mutation: () => ({ style: { cursor: 'pointer', opacity: 0.8 } }) }],
                    onMouseOut: () => [{ target: 'data', mutation: () => ({}) }],
                  },
                }]}
              />
            </CardBody>
          </Card>
        </GridItem>

        {/* Treemap — 8/12 */}
        <GridItem span={8}>
          <Card style={{ height: 320 }}>
            <CardTitle>{t('dashboard.assetWeightByPool')}</CardTitle>
            <CardBody style={{ paddingTop: 4 }}>
              {treemapData.length === 0 ? (
                <Content>
                  <Content component={ContentVariants.p}>{t('common.loading')}</Content>
                </Content>
              ) : (
                <ResponsiveContainer width="100%" height={250}>
                  <Treemap
                    data={treemapData}
                    dataKey="value"
                    aspectRatio={4 / 3}
                    content={TreemapContent as any}
                    onClick={(data: { depth?: number; name?: string }) => {
                      /* v8 ignore next -- @preserve */
                      if (data.depth === 2 && data.name) setSelectedTicker(data.name);
                    }}
                  />
                </ResponsiveContainer>
              )}
            </CardBody>
          </Card>
        </GridItem>
      </Grid>

      {/* ── Row 3 : Table pools ── */}
      <Card>
        <CardTitle>{t('dashboard.detailByPool')}</CardTitle>
        <CardBody>
          <Table aria-label="Pools" variant="compact">
            <Thead>
              <Tr>
                <Th>{t('common.pool')}</Th>
                <Th>{t('common.strategy')}</Th>
                <Th>{t('common.value')}</Th>
                <Th>{t('common.current')}</Th>
                <Th>{t('common.target')}</Th>
                <Th>{t('common.gap')}</Th>
              </Tr>
            </Thead>
            <Tbody>
              {dashboard.pools
                .filter((p) => p.name !== 'Legacy' || p.current_value_eur > 0)
                .map((pool) => (
                  <Tr key={pool.id} style={{ cursor: 'pointer' }} onRowClick={() => setSelectedPool(pool.name)}>
                    <Td>
                      <span style={{
                        display: 'inline-block', width: 10, height: 10,
                        borderRadius: '50%',
                        backgroundColor: getPoolColor(pool.name, dashboard.pools),
                        marginRight: 6,
                      }} />
                      {pool.name}
                    </Td>
                    <Td>{pool.strategy}</Td>
                    <Td>{formatEUR(pool.current_value_eur)}</Td>
                    <Td>{formatPct1(pool.current_pct)}</Td>
                    <Td>{formatPct1(pool.target_pct * 100)}</Td>
                    <Td style={{
                      color: Math.abs(pool.gap_pct) <= 2 ? 'inherit'
                        : pool.gap_pct > 0
                          ? 'var(--pf-t--global--text--color--status--success--default)'
                          : 'var(--pf-t--global--text--color--status--danger--default)',
                      fontWeight: Math.abs(pool.gap_pct) > 5 ? 'bold' : 'normal',
                    }}>
                      {pool.gap_pct > 0 ? '+' : ''}{formatPct1(pool.gap_pct)}
                    </Td>
                  </Tr>
                ))}
            </Tbody>
          </Table>
        </CardBody>
      </Card>

      {/* ── Popup positions par pool ── */}
      {selectedPool && (() => {
        /* v8 ignore next -- @preserve */
        const poolPositions = (holdings ?? [])
          .filter(p => p.pool_name === selectedPool && p.value_eur > 0)
          .sort((a, b) => b.value_eur - a.value_eur);
        const poolInfo = dashboard?.pools.find(p => p.name === selectedPool);
        const poolTotal = poolPositions.reduce((s, p) => s + p.value_eur, 0);
        /* v8 ignore next -- @preserve */
        const poolInfoSuffix = poolInfo ? ` — ${poolInfo.strategy} — ${formatEUR(poolInfo.current_value_eur)}` : '';

        return (
          <Modal
            variant={ModalVariant.medium}
            isOpen
            onClose={() => setSelectedPool(null)}
          >
            <ModalHeader title={`${t('dashboard.poolPopupTitle', { name: selectedPool })}${poolInfoSuffix}`} />
            <ModalBody>
            {poolPositions.length === 0 ? (
              <Content><Content component="p">{t('dashboard.noPositionInPool')}</Content></Content>
            ) : (
              <>
                <Table variant="compact" aria-label={`Positions ${selectedPool}`}>
                  <Thead>
                    <Tr>
                      <Th>{t('common.ticker')}</Th>
                      <Th>{t('positions.productName')}</Th>
                      <Th modifier="nowrap">{t('positions.quantity')}</Th>
                      <Th modifier="nowrap">{t('positions.lastPrice')}</Th>
                      <Th modifier="nowrap">{t('positions.valueEur')}</Th>
                      <Th modifier="nowrap">{t('positions.percentPool')}</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {poolPositions.map((pos, idx) => (
                      <Tr key={pos.ticker} style={{ backgroundColor: idx % 2 === 0 ? '#fff' : '#f5f5f5' }}>
                        <Td><strong><TickerLink ticker={pos.ticker} instrumentType={pos.instrument_type} onClick={setCompositionTicker} /></strong></Td>
                        <Td>{pos.product_name}</Td>
                        <Td>{pos.quantity.toLocaleString('fr-FR', { maximumFractionDigits: 4 })}</Td>
                        <Td>
                          {formatUnitPrice(pos.last_price, pos.currency || 'EUR')}
                          {pos.last_price_date && (
                            <div style={{ fontSize: '0.75rem', color: '#6A6E73' }}>{pos.last_price_date}</div>
                          )}
                        </Td>
                        <Td>{formatEUR(pos.value_eur)}</Td>
                        <Td>{
                          /* v8 ignore next -- @preserve */
                          poolTotal > 0 ? `${(pos.value_eur / poolTotal * 100).toFixed(1)} %` : '—'
                        }</Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
                {poolInfo && (
                  <div style={{ marginTop: '1rem', fontSize: '0.85rem', color: '#6A6E73', display: 'flex', gap: '2rem' }}>
                    <span>{t('common.target')} : <strong>{formatPct1(poolInfo.target_pct * 100)}</strong></span>
                    <span>{t('common.current')} : <strong>{formatPct1(poolInfo.current_pct)}</strong></span>
                    <span>{t('common.gap')} : <strong style={{ color: Math.abs(poolInfo.gap_pct) <= 2 ? 'inherit' : poolInfo.gap_pct > 0 ? 'var(--pf-t--global--text--color--status--success--default)' : 'var(--pf-t--global--text--color--status--danger--default)' }}>
                      {poolInfo.gap_pct > 0 ? '+' : ''}{formatPct1(poolInfo.gap_pct)}
                    </strong></span>
                  </div>
                )}
              </>
            )}
            </ModalBody>
          </Modal>
        );
      })()}
      {/* ── Popup position individuelle (clic treemap) ── */}
      {selectedTicker && (() => {
        /* v8 ignore next -- @preserve */
        const pos = (holdings ?? []).find(p => p.ticker === selectedTicker);
        const gains = capitalGains?.tickers.find(t => t.ticker === selectedTicker);
        const poolInfo = pos?.pool_name ? dashboard?.pools.find(p => p.name === pos.pool_name) : undefined;
        const pvPct = gains && gains.cost_basis_eur !== 0
          ? (gains.unrealized_pv / gains.cost_basis_eur) * 100
          : null;
        const pvColor = gains && gains.unrealized_pv > 0
          ? 'var(--pf-t--global--text--color--status--success--default)'
          : gains && gains.unrealized_pv < 0
          ? 'var(--pf-t--global--text--color--status--danger--default)'
          : undefined;

        return (
          <Modal
            variant={ModalVariant.small}
            isOpen
            onClose={() => setSelectedTicker(null)}
          >
            <ModalHeader title={`${t('dashboard.tickerPopupTitle', { ticker: selectedTicker })}${pos ? ` — ${pos.product_name}` : ''}`} />
            <ModalBody>
            {!pos ? (
              <Content><Content component="p">{t('error.notFound')}</Content></Content>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem 2rem', fontSize: '0.9rem' }}>
                <div>
                  <div style={{ color: '#6A6E73', fontSize: '0.78rem', marginBottom: 2 }}>{t('common.ticker')}</div>
                  <strong><TickerLink ticker={pos.ticker} instrumentType={pos.instrument_type} onClick={setCompositionTicker} /></strong>
                </div>
                <div>
                  <div style={{ color: '#6A6E73', fontSize: '0.78rem', marginBottom: 2 }}>{t('common.pool')}</div>
                  <strong>{pos.pool_name ?? '—'}{poolInfo ? ` (${poolInfo.strategy})` : ''}</strong>
                </div>
                <div>
                  <div style={{ color: '#6A6E73', fontSize: '0.78rem', marginBottom: 2 }}>{t('positions.valueEur')}</div>
                  <strong>{formatEUR(pos.value_eur)}</strong>
                  {dashboard && dashboard.total_eur > 0 && (
                    <span style={{ marginLeft: 6, color: '#6A6E73', fontSize: '0.82rem' }}>
                      ({formatPct1(pos.value_eur / dashboard.total_eur * 100)} portefeuille)
                    </span>
                  )}
                </div>
                <div>
                  <div style={{ color: '#6A6E73', fontSize: '0.78rem', marginBottom: 2 }}>{t('common.quantity')}</div>
                  <strong>{pos.quantity.toLocaleString('fr-FR', { maximumFractionDigits: 6 })}</strong>
                </div>
                <div>
                  <div style={{ color: '#6A6E73', fontSize: '0.78rem', marginBottom: 2 }}>{t('positions.lastPrice')}</div>
                  <strong>{formatUnitPrice(pos.last_price, pos.currency || 'EUR')}</strong>
                  {pos.last_price_date && (
                    <span style={{ marginLeft: 4, color: '#6A6E73', fontSize: '0.78rem' }}>{pos.last_price_date}</span>
                  )}
                </div>
                {gains && (
                  <>
                    <div>
                      <div style={{ color: '#6A6E73', fontSize: '0.78rem', marginBottom: 2 }}>PRU (CUMP)</div>
                      <strong>{formatUnitPrice(gains.cump, 'EUR')}</strong>
                    </div>
                    <div>
                      <div style={{ color: '#6A6E73', fontSize: '0.78rem', marginBottom: 2 }}>{t('dashboard.unrealizedPV')}</div>
                      <strong style={{ color: pvColor }}>
                        {gains.unrealized_pv > 0 ? '+' : ''}{formatEUR(gains.unrealized_pv)}
                        {pvPct !== null && (
                          <span style={{ marginLeft: 4, fontSize: '0.82rem' }}>
                            ({pvPct > 0 ? '+' : ''}{pvPct.toFixed(1)} %)
                          </span>
                        )}
                      </strong>
                    </div>
                  </>
                )}
              </div>
            )}
            </ModalBody>
          </Modal>
        );
      })()}
      <EtfCompositionModal ticker={compositionTicker} onClose={() => setCompositionTicker(null)} />
    </PageSection>
  );
}
