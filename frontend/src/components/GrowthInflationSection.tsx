// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FormSelect, FormSelectOption } from '@patternfly/react-core';
import RatioIndicatorChart from './RatioIndicatorChart';
import QuadrantCard from './QuadrantCard';
import { useGrowthIndicator, useInflationIndicator, useMacroRegions } from '../api/queries';
import { useMacroSyncStatus } from '../hooks/useMacroSyncStatus';
import { useSyncStatusInvalidation } from '../hooks/useSyncStatusInvalidation';
import { formatSyncDateTime } from '../hooks/useSyncStatus';

/**
 * Region-scoped growth (equity/oil) and inflation (bond/gold) ratio charts — extracted
 * verbatim (behavior unchanged) from IndicatorsPage.tsx when that page grew a second,
 * unrelated tab (see MarketPerformanceSection.tsx) so the two aren't visually mixed.
 */
export default function GrowthInflationSection() {
  const { t } = useTranslation();
  const { data: regions = [] } = useMacroRegions();
  const [region, setRegion] = useState<string>('');

  // Default to the first available region once the list loads — regions are user-managed
  // (Configuration générale), so there's no hardcoded default to fall back to.
  useEffect(() => {
    if (!region && regions.length > 0) setRegion(regions[0].code);
  }, [region, regions]);

  const currentRegion = regions.find((r) => r.code === region);
  const regionLabel = currentRegion?.label ?? region;

  const { data: growth, isLoading: growthLoading } = useGrowthIndicator(region);
  const { data: inflation, isLoading: inflationLoading } = useInflationIndicator(region);
  const { data: syncStatus } = useMacroSyncStatus();

  useSyncStatusInvalidation(syncStatus?.finished_at, [['macro-growth'], ['macro-inflation']]);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
        <div style={{ width: 220 }}>
          <FormSelect
            value={region}
            onChange={(_e, val) => setRegion(val)}
            aria-label={t('indicators.regionSelectLabel')}
          >
            {regions.map((r) => (
              <FormSelectOption key={r.code} value={r.code} label={r.label} />
            ))}
          </FormSelect>
        </div>
        {syncStatus && syncStatus.status !== 'never' && (
          <span style={{ fontSize: '0.85rem', color: 'var(--pf-t--global--text--color--subtle)' }}>
            {t('indicators.lastSync', { time: formatSyncDateTime(syncStatus) })}
          </span>
        )}
      </div>

      <RatioIndicatorChart
        title={t('indicators.growthTitle', { region: regionLabel })}
        data={growth}
        isLoading={growthLoading}
        aboveLabel={t('indicators.growthAbove')}
        belowLabel={t('indicators.growthBelow')}
        interpretationAbove={t('indicators.growthInterpretationAbove')}
        interpretationBelow={t('indicators.growthInterpretationBelow')}
      />
      <RatioIndicatorChart
        title={t('indicators.inflationTitle', { region: regionLabel })}
        data={inflation}
        isLoading={inflationLoading}
        aboveLabel={t('indicators.inflationAbove')}
        belowLabel={t('indicators.inflationBelow')}
        interpretationAbove={t('indicators.inflationInterpretationAbove')}
        interpretationBelow={t('indicators.inflationInterpretationBelow')}
      />
      {region && <QuadrantCard region={region} regionLabel={regionLabel} />}
    </div>
  );
}
