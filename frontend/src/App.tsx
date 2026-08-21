import { Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams, NavLink as RouterNavLink } from 'react-router-dom';
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
  PageToggleButton,
  SkipToContent,
  Content, ContentVariants,
} from '@patternfly/react-core';
import { Component, useCallback, useEffect, useState } from 'react';
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
            <Content component={ContentVariants.p} style={{ color: 'var(--pf-t--global--text--color--status--danger--default)' }}>
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
  const location = useLocation();
  const { data: updateStatus } = useGitHubUpdateStatus();
  const hasUpdate = updateStatus?.status === 'update_available';
  const isPath = (path: string) => location.pathname === path;

  return (
    <Nav className="dark-sidebar-nav">
      <NavList>
        <NavItem isActive={isPath(`/portfolio/${portfolioId}/dashboard`)}>
          <RouterNavLink to={`/portfolio/${portfolioId}/dashboard`}>{t('nav.dashboard')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath(`/portfolio/${portfolioId}/positions`)}>
          <RouterNavLink to={`/portfolio/${portfolioId}/positions`}>{t('nav.positions')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath(`/portfolio/${portfolioId}/rebalancing`)}>
          <RouterNavLink to={`/portfolio/${portfolioId}/rebalancing`}>{t('nav.rebalancing')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath(`/portfolio/${portfolioId}/synthese`)}>
          <RouterNavLink to={`/portfolio/${portfolioId}/synthese`}>{t('nav.accounts')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath(`/portfolio/${portfolioId}/transactions`)}>
          <RouterNavLink to={`/portfolio/${portfolioId}/transactions`}>{t('nav.transactions')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath(`/portfolio/${portfolioId}/import`)}>
          <RouterNavLink to={`/portfolio/${portfolioId}/import`}>{t('nav.import')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath(`/portfolio/${portfolioId}/performance`)}>
          <RouterNavLink to={`/portfolio/${portfolioId}/performance`}>{t('nav.performance')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath(`/portfolio/${portfolioId}/prices`)}>
          <RouterNavLink to={`/portfolio/${portfolioId}/prices`}>{t('nav.manualPrices')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath(`/portfolio/${portfolioId}/pv`)}>
          <RouterNavLink to={`/portfolio/${portfolioId}/pv`}>{t('nav.capitalGains')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath(`/portfolio/${portfolioId}/fiscalite`)}>
          <RouterNavLink to={`/portfolio/${portfolioId}/fiscalite`}>{t('nav.taxation')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath(`/portfolio/${portfolioId}/admin`)}>
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

        <NavItem isActive={isPath('/config')}>
          <RouterNavLink to={`/config?from=${portfolioId}`}>{t('nav.globalConfig')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath('/indicators')}>
          <RouterNavLink to={`/indicators?from=${portfolioId}`}>{t('nav.indicators')}</RouterNavLink>
        </NavItem>
        <NavItem isActive={isPath('/system')}>
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

// PatternFly's own `xl` breakpoint (--pf-v6-global--breakpoint--xl: 75rem).
const SIDEBAR_NARROW_BREAKPOINT_PX = 1200;

/**
 * PatternFly's Page component (isManagedSidebar) tracks "mobile" via a ResizeObserver
 * on its own container, measured once near mount — this races the native WebView2
 * launcher's asynchronous initial window-bounds call and never self-corrects if the
 * window isn't resized again after launch (issue #118: confirmed live that PatternFly's
 * internal isMobile flag stayed false even though window.innerWidth was genuinely
 * narrow). Track narrowness ourselves from window.innerWidth instead, with a deferred
 * re-check to absorb that startup race, and drive the sidebar's visibility via a direct
 * inline style (higher specificity than PatternFly's own CSS, so it doesn't matter
 * whether PatternFly's own isMobile ever gets detected correctly).
 */
function useNarrowViewport(): boolean {
  const [isNarrow, setIsNarrow] = useState(() => window.innerWidth < SIDEBAR_NARROW_BREAKPOINT_PX);
  useEffect(() => {
    const check = () => setIsNarrow(window.innerWidth < SIDEBAR_NARROW_BREAKPOINT_PX);
    check();
    const recheckId = window.setTimeout(check, 500);
    window.addEventListener('resize', check);
    return () => {
      window.clearTimeout(recheckId);
      window.removeEventListener('resize', check);
    };
  }, []);
  return isNarrow;
}

function PortfolioLayout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const { portfolioId } = useParams<{ portfolioId: string }>();
  const navigate = useNavigate();
  const { data: allPortfolios = [] } = usePortfolios();
  useAutoRefresh(portfolioId);
  const isNarrow = useNarrowViewport();
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const toggleSidebar = useCallback(() => setIsSidebarOpen((open) => !open), []);

  const masthead = (
    <Masthead style={{ backgroundColor: '#1b1d21' }}>
      <MastheadMain>
        <MastheadToggle>
          <PageToggleButton
            isHamburgerButton
            aria-label="Toggle sidebar"
            className="sidebar-toggle-button"
            isSidebarOpen={isSidebarOpen}
            onSidebarToggle={toggleSidebar}
          />
        </MastheadToggle>
        <MastheadBrand><MastheadLogo style={{ color: 'white', fontWeight: 'bold', fontSize: '1.2rem' }}>
          PIE Manager
        </MastheadLogo></MastheadBrand>
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
        <PageSidebar
          className="dark-sidebar-container"
          isSidebarOpen={isNarrow ? isSidebarOpen : true}
          style={isNarrow ? {
            transform: isSidebarOpen ? 'translateX(0)' : 'translateX(-100%)',
            opacity: isSidebarOpen ? 1 : 0,
            transition: 'transform 0.25s ease, opacity 0.25s ease',
          } : undefined}
        >
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
                className="portfolio-switcher-select"
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
    <Masthead style={{ backgroundColor: '#1b1d21' }}>
      <MastheadMain>
        <MastheadBrand><MastheadLogo style={{ color: 'white', fontWeight: 'bold', fontSize: '1.2rem' }}>
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
    <Masthead style={{ backgroundColor: '#1b1d21' }}>
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
          <MastheadBrand><MastheadLogo style={{ color: 'white', fontWeight: 'bold', fontSize: '1.1rem', flexShrink: 0 }}>
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
