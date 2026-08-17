import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Card, CardBody, CardTitle,
  Gallery, GalleryItem,
  PageSection, PageSectionVariants,
  Spinner,
  Content, ContentVariants, Title,
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td, SortByDirection } from '@patternfly/react-table';
import { useState, useMemo } from 'react';
import { formatEUR, formatPct1, formatDate } from '../utils/format';
import { useCapitalGains } from '../api/queries';
import type { TickerCapitalGains, CapitalGainsEvent } from '../types';

// ── Helpers ──────────────────────────────────────────────────────────────────

function pvColor(val: number): string {
  if (val > 0) return '#137333';
  if (val < 0) return '#D93025';
  return 'var(--pf-t--global--text--color--subtle)';
}

function PvCell({ val }: { val: number }) {
  return (
    <span style={{ color: pvColor(val), fontWeight: 500 }}>
      {val > 0 ? '+' : ''}{formatEUR(val)}
    </span>
  );
}

// ── Section A — Summary table ─────────────────────────────────────────────────

type SummarySortCol = 'ticker' | 'cump' | 'current_value_eur' | 'cost_basis_eur' | 'unrealized_pv' | 'unrealized_pv_pct' | 'realized_pv_total' | 'net_pv';

const SUMMARY_COLS: { key: SummarySortCol; label: string; index: number }[] = [
  { key: 'ticker',            label: 'Ticker',         index: 0 },
  { key: 'ticker',            label: 'Nom',            index: 1 },  // label only, sort same col
  { key: 'cump',              label: 'CUMP',           index: 2 },
  { key: 'current_value_eur', label: 'Valeur actuelle',index: 3 },
  { key: 'cost_basis_eur',    label: 'Coût de revient',index: 4 },
  { key: 'unrealized_pv',     label: 'PV latente',     index: 5 },
  { key: 'unrealized_pv_pct', label: 'PV latente %',   index: 6 },
  { key: 'realized_pv_total', label: 'PV réalisée',    index: 7 },
  { key: 'net_pv',            label: 'PV nette',       index: 8 },
];

// Sort key for column index
function summaryColKey(index: number): SummarySortCol {
  /* v8 ignore next -- @preserve */
  return (SUMMARY_COLS[index]?.key ?? 'net_pv') as SummarySortCol; // ?? fallback unreachable
}

function sortTickers(tickers: TickerCapitalGains[], col: SummarySortCol, dir: 'asc' | 'desc'): TickerCapitalGains[] {
  /* v8 ignore next -- @preserve */
  const sign = dir === 'asc' ? 1 : -1;
  return [...tickers].sort((a, b) => {
    const netA = a.unrealized_pv + a.realized_pv_total;
    const netB = b.unrealized_pv + b.realized_pv_total;
    /* v8 ignore next -- @preserve */
    const pctA = a.cost_basis_eur !== 0 ? a.unrealized_pv / a.cost_basis_eur : 0;
    /* v8 ignore next -- @preserve */
    const pctB = b.cost_basis_eur !== 0 ? b.unrealized_pv / b.cost_basis_eur : 0;
    switch (col) {
      case 'ticker':            return a.ticker.localeCompare(b.ticker) * sign;
      case 'cump':              return (a.cump - b.cump) * sign;
      case 'current_value_eur': return (a.current_value_eur - b.current_value_eur) * sign;
      case 'cost_basis_eur':    return (a.cost_basis_eur - b.cost_basis_eur) * sign;
      case 'unrealized_pv':     return (a.unrealized_pv - b.unrealized_pv) * sign;
      case 'unrealized_pv_pct': return (pctA - pctB) * sign;
      case 'realized_pv_total': return (a.realized_pv_total - b.realized_pv_total) * sign;
      case 'net_pv':            return (netA - netB) * sign;
      /* v8 ignore next -- @preserve */
      default:                  return 0; // TypeScript exhaustive switch — unreachable
    }
  });
}

function SummaryTable({ tickers }: { tickers: TickerCapitalGains[] }) {
  const { t } = useTranslation();
  const [sortIndex, setSortIndex] = useState(0); // default: Ticker ASC
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const onSort = (_: React.MouseEvent, index: number, direction: SortByDirection) => {
    setSortIndex(index);
    setSortDir(direction as 'asc' | 'desc');
  };
  const sortBy = { index: sortIndex, direction: sortDir as SortByDirection };

  const sorted = useMemo(
    () => sortTickers(tickers, summaryColKey(sortIndex), sortDir),
    [tickers, sortIndex, sortDir],
  );

  const summaryColLabels = [
    t('capitalGains.ticker'),
    t('capitalGains.productName'),
    t('capitalGains.cump'),
    t('capitalGains.currentValue'),
    t('capitalGains.costBasis'),
    t('capitalGains.unrealizedPV'),
    t('capitalGains.unrealizedPVPct'),
    t('capitalGains.realizedPV'),
    t('capitalGains.netPV'),
  ];

  return (
    <Table aria-label="Résumé plus-values" variant="compact">
      <Thead>
        <Tr>
          {SUMMARY_COLS.map((col) => (
            <Th key={col.index} modifier="nowrap" sort={{ sortBy, onSort, columnIndex: col.index }}>
              {summaryColLabels[col.index]}
            </Th>
          ))}
        </Tr>
      </Thead>
      <Tbody>
        {sorted.map((t, idx) => {
          const netPv = t.unrealized_pv + t.realized_pv_total;
          const pvPct = t.cost_basis_eur !== 0 ? (t.unrealized_pv / t.cost_basis_eur) * 100 : undefined;
          return (
            <Tr key={t.ticker} style={{ backgroundColor: idx % 2 === 0 ? '#fff' : '#f5f5f5' }}>
              <Td><strong>{t.ticker}</strong></Td>
              <Td>{t.product_name}</Td>
              <Td style={{ color: 'var(--pf-t--global--text--color--subtle)' }}>{formatEUR(t.cump)}</Td>
              <Td>{formatEUR(t.current_value_eur)}</Td>
              <Td>{formatEUR(t.cost_basis_eur)}</Td>
              <Td><PvCell val={t.unrealized_pv} /></Td>
              <Td>
                {pvPct !== undefined
                  ? <span style={{ color: pvColor(pvPct) }}>{formatPct1(pvPct, true)}</span>
                  : <span style={{ color: 'var(--pf-t--global--text--color--subtle)' }}>—</span>}
              </Td>
              <Td><PvCell val={t.realized_pv_total} /></Td>
              <Td><PvCell val={netPv} /></Td>
            </Tr>
          );
        })}
      </Tbody>
    </Table>
  );
}

// ── Section B — KPI cards ─────────────────────────────────────────────────────

function KpiCards({ totalUnrealized, totalRealized, totalCost, earliestEventDate }: {
  totalUnrealized: number;
  totalRealized: number;
  totalCost: number;
  earliestEventDate: string | null;
}) {
  const { t } = useTranslation();
  const pct = totalCost !== 0 ? (totalUnrealized / totalCost) * 100 : undefined;
  return (
    <Gallery hasGutter minWidths={{ default: '220px' }} style={{ marginBottom: '2rem' }}>
      <GalleryItem>
        <Card style={{ borderLeft: '4px solid #1967D2' }}>
          <CardTitle>{t('capitalGains.totalUnrealizedPV')}</CardTitle>
          <CardBody>
            <div style={{ fontSize: '1.4rem', fontWeight: 'bold', color: pvColor(totalUnrealized) }}>
              {totalUnrealized > 0 ? '+' : ''}{formatEUR(totalUnrealized)}
            </div>
            {pct !== undefined && (
              <div style={{ fontSize: '0.9rem', color: pvColor(pct), marginTop: '0.25rem' }}>
                {formatPct1(pct, true)} {t('capitalGains.onCostBasis')}
              </div>
            )}
          </CardBody>
        </Card>
      </GalleryItem>
      <GalleryItem>
        <Card style={{ borderLeft: '4px solid #6A6E73' }}>
          <CardTitle>{t('capitalGains.totalRealizedPV')}</CardTitle>
          <CardBody>
            <div style={{ fontSize: '1.4rem', fontWeight: 'bold', color: pvColor(totalRealized) }}>
              {totalRealized > 0 ? '+' : ''}{formatEUR(totalRealized)}
            </div>
            {earliestEventDate && (
              <div style={{ fontSize: '0.85rem', color: '#6A6E73', marginTop: '0.25rem' }}>
                {t('capitalGains.sinceDate', { date: formatDate(earliestEventDate) })}
              </div>
            )}
          </CardBody>
        </Card>
      </GalleryItem>
    </Gallery>
  );
}

// ── Section C — Historique des cessions ───────────────────────────────────────

type EventSortCol = 'date' | 'ticker' | 'qty_sold' | 'cump_at_sell' | 'sell_price_eur' | 'realized_pv';

const EVENT_COLS: { key: EventSortCol; label: string }[] = [
  { key: 'date',           label: 'Date' },
  { key: 'ticker',         label: 'Ticker' },
  { key: 'ticker',         label: 'Nom produit' },
  { key: 'qty_sold',       label: 'Qté vendue' },
  { key: 'cump_at_sell',   label: 'CUMP à la vente' },
  { key: 'sell_price_eur', label: 'Prix de cession' },
  { key: 'realized_pv',   label: 'PV réalisée' },
];

function sortEvents(events: CapitalGainsEvent[], col: EventSortCol, dir: 'asc' | 'desc'): CapitalGainsEvent[] {
  const sign = dir === 'asc' ? 1 : -1;
  return [...events].sort((a, b) => {
    switch (col) {
      case 'date':           return a.date.localeCompare(b.date) * sign;
      case 'ticker':         return a.ticker.localeCompare(b.ticker) * sign;
      case 'qty_sold':       return (a.qty_sold - b.qty_sold) * sign;
      case 'cump_at_sell':   return (a.cump_at_sell - b.cump_at_sell) * sign;
      case 'sell_price_eur': return (a.sell_price_eur - b.sell_price_eur) * sign;
      case 'realized_pv':   return (a.realized_pv - b.realized_pv) * sign;
      /* v8 ignore next -- @preserve */
      default:               return 0; // TypeScript exhaustive switch — unreachable
    }
  });
}

function HistoryTable({ events }: { events: CapitalGainsEvent[] }) {
  const { t } = useTranslation();
  const [sortIndex, setSortIndex] = useState(0); // default: date
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const onSort = (_: React.MouseEvent, index: number, direction: SortByDirection) => {
    setSortIndex(index);
    setSortDir(direction as 'asc' | 'desc');
  };
  const sortBy = { index: sortIndex, direction: sortDir as SortByDirection };

  /* v8 ignore next -- @preserve */
  const colKey = (index: number): EventSortCol => (EVENT_COLS[index]?.key ?? 'date') as EventSortCol; // ?? fallback unreachable

  const sorted = useMemo(
    () => sortEvents(events, colKey(sortIndex), sortDir),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [events, sortIndex, sortDir],
  );

  const eventColLabels = [
    t('capitalGains.eventDate'),
    t('capitalGains.ticker'),
    t('capitalGains.productNameHistory'),
    t('capitalGains.eventQtySold'),
    t('capitalGains.eventCumpAtSell'),
    t('capitalGains.eventSellPrice'),
    t('capitalGains.realizedPV'),
  ];

  if (events.length === 0) {
    return (
      <div style={{ textAlign: 'center', color: '#6A6E73', padding: '1.5rem',
        border: '2px dashed #e0e0e0', borderRadius: 8, fontSize: '0.9rem' }}>
        {t('capitalGains.noDisposals')}
      </div>
    );
  }

  return (
    <Table aria-label="Historique des cessions" variant="compact">
      <Thead>
        <Tr>
          {EVENT_COLS.map((_col, idx) => (
            <Th key={idx} modifier="nowrap" sort={{ sortBy, onSort, columnIndex: idx }}>
              {eventColLabels[idx]}
            </Th>
          ))}
        </Tr>
      </Thead>
      <Tbody>
        {sorted.map((ev, idx) => (
          <Tr key={`${ev.date}-${ev.ticker}-${idx}`} style={{ backgroundColor: idx % 2 === 0 ? '#fff' : '#f5f5f5' }}>
            <Td>{formatDate(ev.date)}</Td>
            <Td><strong>{ev.ticker}</strong></Td>
            <Td>{ev.product_name}</Td>
            <Td>
              {ev.qty_sold.toLocaleString('fr-FR', { maximumFractionDigits: 4 })}
            </Td>
            <Td style={{ color: 'var(--pf-t--global--text--color--subtle)' }}>{formatEUR(ev.cump_at_sell)}</Td>
            <Td>{formatEUR(ev.sell_price_eur)}</Td>
            <Td><PvCell val={ev.realized_pv} /></Td>
          </Tr>
        ))}
      </Tbody>
    </Table>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CapitalGainsPage() {
  const { t } = useTranslation();
  const { portfolioId } = useParams<{ portfolioId: string }>();
  const { data, isLoading, isError } = useCapitalGains(portfolioId!);

  if (isLoading) {
    return (
      <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
          <Spinner size="xl" aria-label={t('common.loading')} />
        </div>
      </PageSection>
    );
  }

  if (isError || !data) {
    return (
      <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
        <Content>
          <Content component={ContentVariants.p} style={{ color: 'var(--pf-t--global--text--color--status--danger--default)' }}>
            {t('error.loadingCapitalGains')}
          </Content>
        </Content>
      </PageSection>
    );
  }

  // Filter: show tickers with open position or with realized events
  const visibleTickers = data.tickers.filter(
    (t) => t.qty_held > 0 || t.realized_pv_total !== 0,
  );

  // Flatten all sell events, sorted by date DESC by default
  const allEvents: CapitalGainsEvent[] = data.tickers.flatMap((t) => t.events);

  // Earliest realized event date — shown as "depuis" on the KPI card
  const earliestEventDate = allEvents.length > 0
    ? allEvents.map((e) => e.date).sort()[0]
    : null;

  // Total cost basis for percentage on unrealized card
  const totalCost = visibleTickers.reduce((sum, t) => sum + t.cost_basis_eur, 0);

  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
      <Title headingLevel="h1" size="xl" style={{ marginBottom: '1.5rem' }}>
        {t('capitalGains.title')}
      </Title>

      {/* Section B — KPI cards (above table for quick overview) */}
      <KpiCards
        totalUnrealized={data.total_unrealized_pv}
        totalRealized={data.total_realized_pv}
        totalCost={totalCost}
        earliestEventDate={earliestEventDate}
      />

      {/* Section A — Summary table */}
      <Card style={{ marginBottom: '1.5rem' }}>
        <CardTitle>{t('capitalGains.summaryByTicker')}</CardTitle>
        <CardBody>
          {visibleTickers.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#6A6E73', padding: '1.5rem',
              border: '2px dashed #e0e0e0', borderRadius: 8, fontSize: '0.9rem' }}>
              {t('capitalGains.noPositionsOrDisposals')}
            </div>
          ) : (
            <SummaryTable tickers={visibleTickers} />
          )}
        </CardBody>
      </Card>

      {/* Section C — Historique des cessions */}
      <Card>
        <CardTitle>{t('capitalGains.historyTitle')}</CardTitle>
        <CardBody>
          <HistoryTable events={allEvents} />
        </CardBody>
      </Card>
    </PageSection>
  );
}
