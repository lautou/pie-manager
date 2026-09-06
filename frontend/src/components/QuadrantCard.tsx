// SPDX-License-Identifier: AGPL-3.0-or-later
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Card, CardBody, CardTitle, Label, Spinner,
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';
import { useQuadrant, useHoldings } from '../api/queries';
import { computeAllocationByCategory } from '../utils/portfolioAllocation';
import { QUADRANT_FAVORABILITY, QUADRANT_ORDER, CATEGORY_ORDER } from '../utils/quadrantContent';
import type { MacroQuadrant } from '../types';
import type { AllocationCategory } from '../utils/portfolioAllocation';

/**
 * Growth/inflation quadrant classifier — see docs/ROADMAP.md's "Quadrant macro-économique"
 * entry for the full design brief. Purely informational: never writes to Pool.target_pct,
 * never suggests a rebalancing action. Rendered as a card alongside the existing growth/
 * inflation ratio charts in GrowthInflationSection.tsx, sharing its region selection.
 */
export default function QuadrantCard({ region, regionLabel }: { region: string; regionLabel: string }) {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const fromPortfolioId = searchParams.get('from');

  const { data: quadrant, isLoading } = useQuadrant(region);
  const { data: holdings } = useHoldings(fromPortfolioId ?? undefined);

  const allocation = holdings ? computeAllocationByCategory(holdings) : null;

  if (isLoading) {
    return (
      <Card style={{ marginBottom: '1.5rem' }}>
        <CardBody><Spinner size="md" /></CardBody>
      </Card>
    );
  }

  const activeQuadrant = quadrant?.quadrant ?? null;

  return (
    <Card style={{ marginBottom: '1.5rem' }}>
      <CardTitle>{t('indicators.quadrantTitle', { region: regionLabel })}</CardTitle>
      <CardBody>
        {activeQuadrant === null ? (
          <p>{t('indicators.quadrantNoData')}</p>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
              <Label color="blue" style={{ fontSize: '1rem', padding: '0.4rem 0.8rem' }}>
                {t(`indicators.quadrant.${activeQuadrant}`)}
              </Label>
              {quadrant?.overall_confidence != null && (
                <span style={{ fontSize: '0.85rem', color: 'var(--pf-t--global--text--color--subtle)' }}>
                  {t('indicators.quadrantConfidence', { value: quadrant.overall_confidence.toFixed(2) })}
                </span>
              )}
            </div>

            <Table aria-label={t('indicators.quadrantFavorabilityTableLabel')} variant="compact">
              <Thead>
                <Tr>
                  <Th>{t('indicators.quadrantAssetColumn')}</Th>
                  <Th>{t('indicators.quadrantFavorabilityColumn')}</Th>
                  {fromPortfolioId && <Th>{t('indicators.quadrantAllocationColumn')}</Th>}
                </Tr>
              </Thead>
              <Tbody>
                {CATEGORY_ORDER.map((category: AllocationCategory) => {
                  const favorability = QUADRANT_FAVORABILITY[activeQuadrant as MacroQuadrant][category];
                  return (
                    <Tr key={category}>
                      <Td>{t(`indicators.quadrantCategory.${category}`)}</Td>
                      <Td>
                        <Label color={favorability === 'favorable' ? 'green' : 'red'}>
                          {t(`indicators.quadrantFavorability.${favorability}`)}
                        </Label>
                      </Td>
                      {fromPortfolioId && (
                        <Td>{allocation ? `${allocation[category].toFixed(1)} %` : '—'}</Td>
                      )}
                    </Tr>
                  );
                })}
              </Tbody>
            </Table>

            {!fromPortfolioId && (
              <p style={{ fontSize: '0.8rem', color: 'var(--pf-t--global--text--color--subtle)', marginTop: '0.75rem' }}>
                {t('indicators.quadrantNoPortfolioContext')}
              </p>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}

// Exported for tests that want to assert on the full quadrant list without importing internals.
export { QUADRANT_ORDER };
