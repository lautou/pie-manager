// SPDX-License-Identifier: AGPL-3.0-or-later
import { useTranslation } from 'react-i18next';
import { useBondPerformance } from '../api/queries';
import { useBondPerfSyncStatus } from '../hooks/useMacroSyncStatus';
import { useSyncStatusInvalidation } from '../hooks/useSyncStatusInvalidation';
import { formatSyncDateTime } from '../hooks/useSyncStatus';
import PerformanceBarChart from './PerformanceBarChart';

// Countries whose bond-market ticker doesn't track a pure single-country sovereign product
// (see the zz99aa00bb11 migration's own docstring for the full research trail) — flagged
// rather than excluded, since a directionally-informative bar still beats no bar at all.
const CAVEAT_CODES = new Set(['se', 'mx']);

/**
 * Sovereign bond market performance bar chart tab (trailing 1 year, EUR-adjusted) — full CRUD
 * mirror of SectorPerformanceSection.tsx/sector_performance, reusing the same generic
 * PerformanceBarChart.
 */
export default function BondPerformanceSection() {
  const { t } = useTranslation();
  const { data: bondPerf, isLoading } = useBondPerformance();
  const { data: syncStatus } = useBondPerfSyncStatus();

  useSyncStatusInvalidation(syncStatus?.finished_at, [['bond-performance']]);

  const chartData = bondPerf?.map((c) => ({
    label: c.label, value: c.perf_pct, tooltipLabel: c.index_label,
  }));

  const caveatCountries = bondPerf?.filter((c) => CAVEAT_CODES.has(c.code)) ?? [];

  return (
    <div>
      {syncStatus && syncStatus.status !== 'never' && (
        <div style={{ marginBottom: '1rem', fontSize: '0.85rem', color: 'var(--pf-t--global--text--color--subtle)' }}>
          {t('indicators.lastSync', { time: formatSyncDateTime(syncStatus) })}
        </div>
      )}
      <PerformanceBarChart
        title={t('bondPerformance.chartTitle')}
        data={chartData}
        isLoading={isLoading}
      />
      {caveatCountries.length > 0 && (
        <p style={{ fontSize: '0.78rem', color: '#6A6E73', marginTop: '0.75rem' }}>
          {t('bondPerformance.caveatNote', {
            countries: caveatCountries.map((c) => c.label).join(', '),
          })}
        </p>
      )}
    </div>
  );
}
