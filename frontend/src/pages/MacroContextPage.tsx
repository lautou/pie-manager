// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  FormGroup,
  FormSelect,
  FormSelectOption,
  PageSection,
  Title,
} from '@patternfly/react-core';
import { useMacroRegions } from '../api/queries';
import QuadrantCard from '../components/QuadrantCard';

/**
 * Portfolio-scoped macro context: region selector + QuadrantCard with its
 * "Ton allocation" column (portfolioId passed explicitly) — extracted from
 * RebalancingPage.tsx into its own nav section so it isn't visually tied to
 * the rebalancing simulator below it. See .claude/rules/macro-indicators.md's
 * "Growth/inflation quadrant classifier" section for the full feature.
 */
export default function MacroContextPage() {
  const { t } = useTranslation();
  const { portfolioId } = useParams<{ portfolioId: string }>();
  const { data: macroRegions = [] } = useMacroRegions();
  const [macroRegion, setMacroRegion] = useState<string>('');

  // Default to the first available region once the list loads, same convention as
  // GrowthInflationSection.tsx (regions are user-managed, no hardcoded default).
  useEffect(() => {
    if (!macroRegion && macroRegions.length > 0) setMacroRegion(macroRegions[0].code);
  }, [macroRegion, macroRegions]);

  const currentMacroRegion = macroRegions.find((r) => r.code === macroRegion);
  const macroRegionLabel = currentMacroRegion?.label ?? macroRegion;

  return (
    <PageSection hasBodyWrapper={false}>
      <Title headingLevel="h1" size="xl" style={{ marginBottom: '1rem' }}>
        {t('macroContext.title')}
      </Title>

      <div style={{ width: 220, marginBottom: '1rem' }}>
        <FormGroup label={t('macroContext.regionLabel')} fieldId="macro-context-region">
          <FormSelect
            id="macro-context-region"
            value={macroRegion}
            onChange={(_e, val) => setMacroRegion(val)}
          >
            {macroRegions.map((r) => (
              <FormSelectOption key={r.code} value={r.code} label={r.label} />
            ))}
          </FormSelect>
        </FormGroup>
      </div>

      {macroRegion && (
        <QuadrantCard region={macroRegion} regionLabel={macroRegionLabel} portfolioId={portfolioId} />
      )}
    </PageSection>
  );
}
