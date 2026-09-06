// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  PageSection, PageSectionVariants, Tab, Tabs, TabTitleText, Title,
} from '@patternfly/react-core';
import GrowthInflationSection from '../components/GrowthInflationSection';
import MarketPerformanceSection from '../components/MarketPerformanceSection';
import SectorPerformanceSection from '../components/SectorPerformanceSection';
import EquityPremiumSection from '../components/EquityPremiumSection';
import BondPerformanceSection from '../components/BondPerformanceSection';

type IndicatorsTab =
  | 'growth-inflation' | 'market-performance' | 'sector-performance' | 'equity-premium' | 'bond-performance';

/**
 * Global, portfolio-independent macro indicators page. Five deliberately separate tabs —
 * region-scoped growth/inflation ratio charts, the "Performance des actions" country
 * leaderboard, the "Performance des classes d'actifs" chart (commodities, currencies, bonds,
 * private equity, crypto...), "Premium action" (implied equity risk premium, one bar per
 * country), and "Performance obligataire" (trailing-1-year sovereign bond market performance,
 * one bar per country) — so the unrelated chart types (time-series ratio vs. static ranked bar
 * chart) are never visually mixed on the same view. The four leaderboard/premium tabs share
 * the same PerformanceBarChart component, differing only in their data universe and (for
 * Premium action) sign-based bar coloring — internal identifiers (component/table/route names)
 * still say "country"/"sector" for the first two, even though the visible tab labels moved to
 * "actions"/"classes d'actifs" (a display-only rename, not worth the churn of renaming
 * already-populated live tables/routes).
 */
export default function IndicatorsPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<IndicatorsTab>('growth-inflation');

  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
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
        <Tab eventKey="sector-performance" title={<TabTitleText>{t('indicators.tabSectorPerformance')}</TabTitleText>}>
          <SectorPerformanceSection />
        </Tab>
        <Tab eventKey="equity-premium" title={<TabTitleText>{t('indicators.tabEquityPremium')}</TabTitleText>}>
          <EquityPremiumSection />
        </Tab>
        <Tab eventKey="bond-performance" title={<TabTitleText>{t('indicators.tabBondPerformance')}</TabTitleText>}>
          <BondPerformanceSection />
        </Tab>
      </Tabs>
    </PageSection>
  );
}
