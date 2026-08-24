// SPDX-License-Identifier: AGPL-3.0-or-later
import { useTranslation } from 'react-i18next';
import { useCountryPerformance } from '../api/queries';
import { useCountryPerfSyncStatus } from '../hooks/useMacroSyncStatus';
import { useSyncStatusInvalidation } from '../hooks/useSyncStatusInvalidation';
import { formatSyncDateTime } from '../hooks/useSyncStatus';
import PerformanceBarChart from './PerformanceBarChart';

/**
 * Country stock-market performance leaderboard tab (Top N, trailing 1 year, EUR-adjusted)
 * — kept on its own tab from GrowthInflationSection.tsx since it's a static ranking, not a
 * region-scoped ratio, and the two shouldn't be visually mixed.
 */
export default function MarketPerformanceSection() {
  const { t } = useTranslation();
  const { data: countryPerf, isLoading } = useCountryPerformance();
  const { data: syncStatus } = useCountryPerfSyncStatus();

  useSyncStatusInvalidation(syncStatus?.finished_at, [['country-performance']]);

  const chartData = countryPerf?.map((c) => ({
    label: c.label, value: c.perf_pct, tooltipLabel: c.index_label,
  }));

  return (
    <div>
      {syncStatus && syncStatus.status !== 'never' && (
        <div style={{ marginBottom: '1rem', fontSize: '0.85rem', color: 'var(--pf-t--global--text--color--subtle)' }}>
          {t('indicators.lastSync', { time: formatSyncDateTime(syncStatus) })}
        </div>
      )}
      <PerformanceBarChart
        title={t('marketPerformance.chartTitle')}
        data={chartData}
        isLoading={isLoading}
      />
    </div>
  );
}
