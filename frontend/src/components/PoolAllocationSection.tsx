// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Tabs, Tab, TabTitleText } from '@patternfly/react-core';
import {
	ChartDonut,
	ChartThemeColor
} from '@patternfly/react-charts';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';
import { usePoolAllocation } from '../api/queries';
import { formatEUR, formatPct1 } from '../utils/format';

const DONUT_COLORS = [
  '#0066CC', '#F0AB00', '#3E8635', '#8A8D90', '#C9190B',
  '#009596', '#6753AC', '#EC7A08', '#4CB140', '#003737', '#B8860B',
];

interface PoolAllocationSectionProps {
  portfolioId: number | string;
  poolId: number;
}

export default function PoolAllocationSection({ portfolioId, poolId }: PoolAllocationSectionProps) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<'sector' | 'company'>('sector');
  const { data } = usePoolAllocation(portfolioId, poolId);

  if (!data || (data.by_sector.length === 0 && data.by_company.length === 0)) {
    return null;
  }

  const sectorDonutData = data.by_sector.map((e) => ({
    x: `${t(`sectors.${e.key}`, e.label)} (${formatPct1(e.pct)})`,
    y: e.value_eur,
  }));

  return (
    <div style={{ marginTop: '1rem' }}>
      <Tabs
        activeKey={activeTab}
        onSelect={(_evt, key) => setActiveTab(key as 'sector' | 'company')}
      >
        <Tab eventKey="sector" title={<TabTitleText>{t('holdings.allocationBySector')}</TabTitleText>}>
          <div style={{ display: 'flex', justifyContent: 'center', padding: '1rem 0' }}>
            <ChartDonut
              data={sectorDonutData}
              colorScale={DONUT_COLORS}
              height={220}
              width={420}
              innerRadius={60}
              labels={({ datum }: { datum: { x: string; y: number } }) => `${datum.x}\n${formatEUR(datum.y)}`}
              legendData={sectorDonutData.map((d, i) => ({
                name: d.x,
                symbol: { fill: DONUT_COLORS[i % DONUT_COLORS.length] },
              }))}
              legendOrientation="vertical"
              legendPosition="right"
              padding={{ bottom: 10, left: 10, right: 180, top: 10 }}
              themeColor={ChartThemeColor.multi}
            />
          </div>
        </Tab>
        <Tab eventKey="company" title={<TabTitleText>{t('holdings.allocationByCompany')}</TabTitleText>}>
          <Table variant="compact" aria-label={t('holdings.allocationByCompany')}>
            <Thead>
              <Tr>
                <Th>{t('common.company')}</Th>
                <Th modifier="nowrap">{t('positions.valueEur')}</Th>
                <Th modifier="nowrap">{t('common.percentage')}</Th>
              </Tr>
            </Thead>
            <Tbody>
              {data.by_company.map((e) => (
                <Tr key={e.key}>
                  {/* '__OTHER__' matches OTHER_KEY in etf_holdings_service.py — the backend
                      always sorts it last regardless of value, we only translate its label. */}
                  <Td>{e.key === '__OTHER__' ? t('holdings.allocationOther') : e.label}</Td>
                  <Td>{formatEUR(e.value_eur)}</Td>
                  <Td>{formatPct1(e.pct)}</Td>
                </Tr>
              ))}
              {data.unclassified_eur > 0 && (
                <Tr>
                  <Td style={{ color: 'var(--pf-t--global--text--color--subtle)', fontStyle: 'italic' }}>
                    {t('holdings.allocationUnclassified')}
                  </Td>
                  <Td>{formatEUR(data.unclassified_eur)}</Td>
                  <Td>{formatPct1(data.unclassified_pct)}</Td>
                </Tr>
              )}
            </Tbody>
          </Table>
        </Tab>
      </Tabs>
    </div>
  );
}
