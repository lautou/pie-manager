import { Navigate, Route, Routes, useNavigate, useParams, useSearchParams, NavLink as RouterNavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Button,
  FormSelect, FormSelectOption,
  Masthead,
  MastheadLogo,
  MastheadMain,
  MastheadToggle, MastheadBrand,
  Nav,
  NavItem,
  NavList,
  Page,
  PageSection, PageSectionVariants,
  PageSidebar,
  PageSidebarBody,
  SkipToContent,
  Content, ContentVariants,
} from '@patternfly/react-core';
import { BarsIcon } from '@patternfly/react-icons';
import { Component, useState } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

import { useQuery } from '@tanstack/react-query';
import apiClient from './api/client';

function AppVersion() {
  const { data } = useQuery<{ version: string }>({
    queryKey: ['app-version'],
    queryFn: /* v8 ignore next -- @preserve */ async () => (await apiClient.get<{ version: string }>('/api/admin/version')).data,
    staleTime: Infinity,
  });
  if (!data?.version) return null;
  return (
    <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: '0.78rem', fontFamily: 'monospace', marginLeft: '0.5rem' }}>
      v{data.version}
    </span>
  );
}

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(_error: Error, _info: ErrorInfo) { /* captured by getDerivedStateFromError */ }
  render() {
    if (this.state.error) {
      return (
        <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
          <Content>
            <Content component={ContentVariants.h2}>Une erreur est survenue</Content>
            <Content component={ContentVariants.p} style={{ color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--danger-color--100 */ }}>
              {this.state.error.message}
            </Content>
            <Button variant="primary" onClick={() => this.setState({ error: null })}>
              Réessayer
            </Button>
          </Content>
        </PageSection>
      );
    }
    return this.props.children;
  }
}
import { usePortfolios, useGitHubUpdateStatus } from './api/queries';
import { useAutoRefresh } from './hooks/useAutoRefresh';
import RefreshBanner from './components/RefreshBanner';
import PortfolioSelectPage from './pages/PortfolioSelectPage';
import DashboardPage from './pages/DashboardPage';
import TransactionsPage from './pages/TransactionsPage';
import TransactionImportPage from './pages/TransactionImportPage';
import PerformancePage from './pages/PerformancePage';
import HoldingsPage from './pages/HoldingsPage';
import ManualPricePage from './pages/ManualPricePage';
import AccountsSummaryPage from './pages/AccountsSummaryPage';
import AdminPage from './pages/AdminPage';
import SystemAdminPage from './pages/SystemAdminPage';
import GlobalConfigPage from './pages/GlobalConfigPage';
import CapitalGainsPage from './pages/CapitalGainsPage';
import RebalancingPage from './pages/RebalancingPage';
import TaxPage from './pages/TaxPage';
import IndicatorsPage from './pages/IndicatorsPage';

function AppNav({ portfolioId }: { portfolioId: string }) {
  const { t } = useTranslation();
  const { data: updateStatus } = useGitHubUpdateStatus();
  const hasUpdate = updateStatus?.status === 'update_available';

  return (
    <Nav>
      <NavList>
        <NavItem>
          <RouterNavLink to={`/portfolio/${portfolioId}/dashboard`}>{t('nav.dashboard')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/portfolio/${portfolioId}/positions`}>{t('nav.positions')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/portfolio/${portfolioId}/rebalancing`}>{t('nav.rebalancing')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/portfolio/${portfolioId}/synthese`}>{t('nav.accounts')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/portfolio/${portfolioId}/transactions`}>{t('nav.transactions')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/portfolio/${portfolioId}/import`}>{t('nav.import')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/portfolio/${portfolioId}/performance`}>{t('nav.performance')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/portfolio/${portfolioId}/prices`}>{t('nav.manualPrices')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/portfolio/${portfolioId}/pv`}>{t('nav.capitalGains')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/portfolio/${portfolioId}/fiscalite`}>{t('nav.taxation')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/portfolio/${portfolioId}/admin`}>{t('nav.portfolioConfig')}</RouterNavLink>
        </NavItem>

        {/* ── Séparateur : configuration globale & administration ── */}
        <li aria-hidden="true" style={{
          margin: '0.5rem 0',
          borderTop: '1px solid rgba(255,255,255,0.15)',
          listStyle: 'none',
        }}>
          <span style={{
            display: 'block', textAlign: 'center', fontSize: '0.65rem',
            color: 'rgba(255,255,255,0.35)', letterSpacing: '0.08em',
            padding: '0.2rem 0', userSelect: 'none',
          }}>{t('nav.global')}</span>
        </li>

        <NavItem>
          <RouterNavLink to={`/config?from=${portfolioId}`}>{t('nav.globalConfig')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/indicators?from=${portfolioId}`}>{t('nav.indicators')}</RouterNavLink>
        </NavItem>
        <NavItem>
          <RouterNavLink to={`/system?from=${portfolioId}`}>
            {t('nav.systemAdmin')}
            {hasUpdate && (
              <span
                data-testid="update-badge"
                style={{
                  display: 'inline-block',
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: '#C9190B',
                  marginLeft: 6,
                  verticalAlign: 'middle',
                }}
              />
            )}
          </RouterNavLink>
        </NavItem>
      </NavList>
    </Nav>
  );
}

function PortfolioLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const { portfolioId } = useParams<{ portfolioId: string }>();
  const navigate = useNavigate();
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const { data: allPortfolios = [] } = usePortfolios();
  useAutoRefresh(portfolioId);

  const masthead = (
    <Masthead>
      
      <MastheadMain><MastheadToggle>
        <Button
          variant="plain"
          onClick={() => setIsSidebarOpen((o) => !o)}
          aria-label="Toggle sidebar"
          icon={<BarsIcon />}
        />
      </MastheadToggle>
        <MastheadBrand data-codemods><MastheadBrand data-codemods><MastheadBrand data-codemods><MastheadLogo data-codemods style={{ color: 'white', fontWeight: 'bold', fontSize: '1.2rem' }}>
          PIE Manager
        </MastheadLogo></MastheadBrand></MastheadBrand></MastheadBrand>
        <AppVersion />
      </MastheadMain>
    </Masthead>
  );

  return (
    <>
      <RefreshBanner />
    <Page
      masthead={masthead}
      sidebar={
        <PageSidebar isSidebarOpen={isSidebarOpen}>
          <PageSidebarBody>
            {/* Portfolio switcher at top of sidebar */}
            <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid rgba(255,255,255,0.15)' }}>
              <div style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.5)', marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                {t('nav.portfolio')}
              </div>
              <FormSelect
                value={portfolioId}
                onChange={(_e, val) => val !== portfolioId && navigate(`/portfolio/${val}/dashboard`)}
                aria-label="Changer de portefeuille"
                style={{ background: '#1b1d21', color: 'white', border: '1px solid rgba(255,255,255,0.3)', borderRadius: 4, width: '100%' }}
              >
                {allPortfolios.map(p => (
                  <FormSelectOption key={p.id} value={String(p.id)} label={p.name}
                    style={{ background: '#1b1d21', color: 'white' }} />
                ))}
              </FormSelect>
              <Button variant="link" size="sm" style={{ color: 'rgba(255,255,255,0.6)', padding: '0.25rem 0', fontSize: '0.75rem' }}
                onClick={() => navigate('/portfolios')}>
                {t('nav.managePortfolios')}
              </Button>
            </div>
            <AppNav portfolioId={portfolioId!} />
          </PageSidebarBody>
        </PageSidebar>
      }
      skipToContent={<SkipToContent href="#main-content">{t('app.skipToContent')}</SkipToContent>}
    >
      {children}
    </Page>
    </>
  );
}

function RootLayout() {
  const masthead = (
    <Masthead>
      <MastheadMain>
        <MastheadBrand data-codemods><MastheadLogo data-codemods style={{ color: 'white', fontWeight: 'bold', fontSize: '1.2rem' }}>
          PIE Manager
        </MastheadLogo></MastheadBrand>
        <AppVersion />
      </MastheadMain>
    </Masthead>
  );
  return (
    <Page masthead={masthead}>
      <PortfolioSelectPage />
    </Page>
  );
}

function GlobalLayout({ title, children }: { title: string; children: React.ReactNode }) {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const fromPortfolioId = searchParams.get('from');
  const navigate = useNavigate();

  const masthead = (
    <Masthead>
      <MastheadMain>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', width: '100%' }}>
          <button
            onClick={() => fromPortfolioId
              ? navigate(`/portfolio/${fromPortfolioId}/dashboard`)
              : navigate('/')}
            style={{
              background: 'transparent', border: '1px solid rgba(255,255,255,0.4)',
              color: 'white', borderRadius: 4, padding: '4px 12px', cursor: 'pointer',
              fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 6,
              transition: 'background 0.15s', flexShrink: 0,
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.12)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            title={fromPortfolioId ? t('app.backToPortfolio') : t('app.backToHome')}
          >
            {t('app.back')}
          </button>
          <MastheadBrand data-codemods><MastheadLogo data-codemods style={{ color: 'white', fontWeight: 'bold', fontSize: '1.1rem', flexShrink: 0 }}>
            PIE Manager
          </MastheadLogo></MastheadBrand>
          <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: '0.85rem', flexShrink: 0 }}>
            — {title}
          </span>
          <div style={{ flex: 1 }} />
          <AppVersion />
        </div>
      </MastheadMain>
    </Masthead>
  );
  return <Page masthead={masthead}>{children}</Page>;
}

function SystemLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  return <GlobalLayout title={t('nav.systemAdmin')}>{children}</GlobalLayout>;
}

function PortfolioRoutes() {
  const { portfolioId } = useParams<{ portfolioId: string }>();
  return (
    <PortfolioLayout>
      <Routes>
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="positions" element={<HoldingsPage />} />
        <Route path="rebalancing" element={<RebalancingPage />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="import" element={<TransactionImportPage />} />
        <Route path="performance" element={<PerformancePage />} />
        <Route path="prices" element={<ManualPricePage />} />
        <Route path="synthese" element={<AccountsSummaryPage />} />
        <Route path="pv" element={<CapitalGainsPage />} />
        <Route path="fiscalite" element={<TaxPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="*" element={<Navigate to={`/portfolio/${portfolioId}/dashboard`} replace />} />
      </Routes>
    </PortfolioLayout>
  );
}

function ConfigLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  return <GlobalLayout title={t('nav.globalConfig')}>{children}</GlobalLayout>;
}

function IndicatorsLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  return <GlobalLayout title={t('nav.indicators')}>{children}</GlobalLayout>;
}

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<Navigate to="/portfolios" replace />} />
        <Route path="/portfolios" element={<RootLayout />} />
        <Route path="/portfolio/:portfolioId/*" element={<PortfolioRoutes />} />
        <Route path="/config" element={<ConfigLayout><GlobalConfigPage /></ConfigLayout>} />
        <Route path="/indicators" element={<IndicatorsLayout><IndicatorsPage /></IndicatorsLayout>} />
        <Route path="/system" element={<SystemLayout><SystemAdminPage /></SystemLayout>} />
      </Routes>
    </ErrorBoundary>
  );
}
