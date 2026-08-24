// SPDX-License-Identifier: AGPL-3.0-or-later
import { useTranslation } from 'react-i18next';
import { useEquityPremium } from '../api/queries';
import { useEquityPremiumSyncStatus } from '../hooks/useMacroSyncStatus';
import { useSyncStatusInvalidation } from '../hooks/useSyncStatusInvalidation';
import { formatSyncDateTime } from '../hooks/useSyncStatus';
import PerformanceBarChart from './PerformanceBarChart';

/**
 * Equity risk premium bar chart tab (Fed Model/Damodaran: earnings yield minus the 10-year
 * government bond yield, one bar per country) — a point-in-time snapshot, not a
 * trailing-window return like MarketPerformanceSection.tsx/SectorPerformanceSection.tsx, but
 * reuses the same generic PerformanceBarChart with colorBySign for the green/red convention.
 */
export default function EquityPremiumSection() {
  const { t } = useTranslation();
  const { data: premiums, isLoading } = useEquityPremium();
  const { data: syncStatus } = useEquityPremiumSyncStatus();

  useSyncStatusInvalidation(syncStatus?.finished_at, [['equity-premium']]);

  const chartData = premiums?.map((p) => ({
    label: p.label,
    value: p.premium_pct,
    tooltipLabel: `${p.equity_label} (${p.equity_yield_pct.toFixed(1)}%) vs ${p.bond_label} (${p.bond_yield_pct.toFixed(1)}%)`,
  }));

  return (
    <div>
      {syncStatus && syncStatus.status !== 'never' && (
        <div style={{ marginBottom: '1rem', fontSize: '0.85rem', color: 'var(--pf-t--global--text--color--subtle)' }}>
          {t('indicators.lastSync', { time: formatSyncDateTime(syncStatus) })}
        </div>
      )}
      <PerformanceBarChart
        title={t('equityPremium.chartTitle')}
        data={chartData}
        isLoading={isLoading}
        colorBySign
      />
      <p style={{ fontSize: '0.8rem', color: '#6A6E73', marginTop: '-1rem', marginBottom: '1.5rem' }}>
        {t('equityPremium.legend')}
      </p>
    </div>
  );
}
