import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import {
  FormSelect, FormSelectOption,
  PageSection, PageSectionVariants, Title,
} from '@patternfly/react-core';
import RatioIndicatorChart from '../components/RatioIndicatorChart';
import { useGrowthIndicator, useInflationIndicator, useMacroRegions } from '../api/queries';
import { useMacroSyncStatus } from '../hooks/useMacroSyncStatus';
import { formatSyncDateTime } from '../hooks/useSyncStatus';

export default function IndicatorsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
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

  // As soon as a daily sync actually completes (detected via sync-status polling), invalidate
  // the two indicator queries — mirrors useAutoRefresh.ts's finished_at-change detection,
  // skipping the first observed value on mount.
  const lastSyncRef = useRef<string | null>(null);
  useEffect(() => {
    const finishedAt = syncStatus?.finished_at ?? null;
    if (finishedAt === null) return;
    if (lastSyncRef.current === null) {
      lastSyncRef.current = finishedAt;
      return;
    }
    if (finishedAt !== lastSyncRef.current) {
      lastSyncRef.current = finishedAt;
      qc.invalidateQueries({ queryKey: ['macro-growth'] });
      qc.invalidateQueries({ queryKey: ['macro-inflation'] });
    }
  }, [qc, syncStatus?.finished_at]);

  return (
    <PageSection variant={PageSectionVariants.default}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
        <Title headingLevel="h1" size="xl">{t('indicators.title')}</Title>
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
          <span style={{ fontSize: '0.85rem', color: 'var(--pf-v5-global--Color--200)' }}>
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
    </PageSection>
  );
}
