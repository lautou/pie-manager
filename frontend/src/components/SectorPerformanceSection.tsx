// SPDX-License-Identifier: AGPL-3.0-or-later
import { useTranslation } from 'react-i18next';
import { useSectorPerformance } from '../api/queries';
import { useSectorPerfSyncStatus } from '../hooks/useMacroSyncStatus';
import { useSyncStatusInvalidation } from '../hooks/useSyncStatusInvalidation';
import { formatSyncDateTime } from '../hooks/useSyncStatus';
import PerformanceBarChart from './PerformanceBarChart';

/**
 * Sector/commodity performance bar chart tab (trailing 1 year, EUR-adjusted, fixed 4-row
 * universe by default) — full CRUD mirror of MarketPerformanceSection.tsx/
 * country_performance, reusing the same generic PerformanceBarChart.
 */
export default function SectorPerformanceSection() {
  const { t } = useTranslation();
  const { data: sectorPerf, isLoading } = useSectorPerformance();
  const { data: syncStatus } = useSectorPerfSyncStatus();

  useSyncStatusInvalidation(syncStatus?.finished_at, [['sector-performance']]);

  const chartData = sectorPerf?.map((s) => ({
    label: s.label, value: s.perf_pct, tooltipLabel: s.index_label,
  }));

  return (
    <div>
      {syncStatus && syncStatus.status !== 'never' && (
        <div style={{ marginBottom: '1rem', fontSize: '0.85rem', color: 'var(--pf-t--global--text--color--subtle)' }}>
          {t('indicators.lastSync', { time: formatSyncDateTime(syncStatus) })}
        </div>
      )}
      <PerformanceBarChart
        title={t('sectorPerformance.chartTitle')}
        data={chartData}
        isLoading={isLoading}
      />
    </div>
  );
}
