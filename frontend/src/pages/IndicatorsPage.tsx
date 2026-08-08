import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  PageSection, PageSectionVariants, Tab, Tabs, TabTitleText, Title,
} from '@patternfly/react-core';
import GrowthInflationSection from '../components/GrowthInflationSection';
import MarketPerformanceSection from '../components/MarketPerformanceSection';

type IndicatorsTab = 'growth-inflation' | 'market-performance';

/**
 * Global, portfolio-independent macro indicators page. Two deliberately separate tabs —
 * region-scoped growth/inflation ratio charts vs. the country performance leaderboard —
 * so the two unrelated chart types (time-series ratio vs. static ranked bar chart) are
 * never visually mixed on the same view.
 */
export default function IndicatorsPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<IndicatorsTab>('growth-inflation');

  return (
    <PageSection variant={PageSectionVariants.default}>
      <Title headingLevel="h1" size="xl" style={{ marginBottom: '1rem' }}>{t('indicators.title')}</Title>
      <Tabs
        activeKey={activeTab}
        onSelect={(_evt, key) => setActiveTab(key as IndicatorsTab)}
      >
        <Tab eventKey="growth-inflation" title={<TabTitleText>{t('indicators.tabGrowthInflation')}</TabTitleText>}>
          <GrowthInflationSection />
        </Tab>
        <Tab eventKey="market-performance" title={<TabTitleText>{t('indicators.tabMarketPerformance')}</TabTitleText>}>
          <MarketPerformanceSection />
        </Tab>
      </Tabs>
    </PageSection>
  );
}
