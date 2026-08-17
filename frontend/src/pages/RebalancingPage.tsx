import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Card, CardBody, CardTitle,
  PageSection, PageSectionVariants,
  Spinner,
  Content, ContentVariants, Title,
  ToggleGroup, ToggleGroupItem,
  Tooltip,
} from '@patternfly/react-core';
import { useState, useRef, useEffect } from 'react';
import { formatEUR } from '../utils/format';
import { useDashboard, useSystemSetting } from '../api/queries';
import apiClient from '../api/client';
import SyncBadge from '../components/SyncBadge';

const DEFAULT_TOLERANCE_OK_PCT = 1;
const DEFAULT_TOLERANCE_WARNING_PCT = 2;
const SEVERITY_BAR_COLOR = { ok: '#34A853', warning: '#E65100', danger: '#D93025' } as const;
const SEVERITY_TEXT_COLOR = { ok: '#137333', warning: '#E65100', danger: '#D93025' } as const;

type SeverityLevel = keyof typeof SEVERITY_BAR_COLOR;

function severityLevel(gapPct: number, okPct: number, warningPct: number): SeverityLevel {
  const abs = Math.abs(gapPct);
  if (abs < okPct) return 'ok';
  if (abs < warningPct) return 'warning';
  return 'danger';
}

export default function RebalancingPage() {
  const { t } = useTranslation();
  const { portfolioId } = useParams<{ portfolioId: string }>();
  const [rebalMode, setRebalMode] = useState<'contribution' | 'hybrid' | 'hard'>('contribution');
  const [injection, setInjection] = useState(0);
  const [commissionPct, setCommissionPct] = useState(0);
  const [commissionMin, setCommissionMin] = useState(0);
  const [rebalData, setRebalData] = useState<any>(null);
  const [rebalLoading, setRebalLoading] = useState(false);
  const rebalTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const {
    data: dashboard,
    isLoading: dashLoading,
    isError: dashError,
  } = useDashboard(portfolioId!);

  const { data: toleranceOkSetting } = useSystemSetting('rebalancing.tolerance_ok_pct');
  const { data: toleranceWarningSetting } = useSystemSetting('rebalancing.tolerance_warning_pct');
  const toleranceOkPct = parseFloat(toleranceOkSetting?.value ?? '') || DEFAULT_TOLERANCE_OK_PCT;
  const toleranceWarningPct = parseFloat(toleranceWarningSetting?.value ?? '') || DEFAULT_TOLERANCE_WARNING_PCT;

  const fetchRebalancing = async (inj: number, commPct: number, commMin: number) => {
    setRebalLoading(true);
    try {
      const r = await apiClient.post('/api/dashboard/rebalancing', {
        portfolio_id: Number(portfolioId),
        external_injection: inj,
        commission_pct: commPct,
        commission_min: commMin,
      });
      setRebalData(r.data);
    } catch { /* ignore */ } finally { setRebalLoading(false); }
  };

  const handleInjectionChange = (val: number) => {
    setInjection(val);
    if (rebalTimerRef.current) clearTimeout(rebalTimerRef.current);
    rebalTimerRef.current = setTimeout(() => fetchRebalancing(val, commissionPct, commissionMin), 600);
  };

  // Automatically trigger the "Cash only" simulation as soon as the dashboard is loaded
  useEffect(() => {
    if (dashboard) {
      fetchRebalancing(injection, commissionPct, commissionMin);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboard?.total_eur]);

  const handleCommissionChange = (commPct: number, commMin: number) => {
    setCommissionPct(commPct);
    setCommissionMin(commMin);
    if (rebalData !== null) {
      if (rebalTimerRef.current) clearTimeout(rebalTimerRef.current);
      rebalTimerRef.current = setTimeout(() => fetchRebalancing(injection, commPct, commMin), 600);
    }
  };

  useEffect(() => {
    return () => {
      if (rebalTimerRef.current) clearTimeout(rebalTimerRef.current);
    };
  }, []);

  if (dashLoading) {
    return (
      <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
          <Spinner size="xl" aria-label={t('rebalancing.loadingSimulator')} />
        </div>
      </PageSection>
    );
  }

  if (dashError || !dashboard) {
    return (
      <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
        <Content>
          <Content
            component={ContentVariants.p}
            style={{ color: 'var(--pf-t--global--text--color--status--danger--default)' }}
          >
            {t('error.loadingRebalancing')}
          </Content>
        </Content>
      </PageSection>
    );
  }

  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
        <Title headingLevel="h1" size="xl">{t('rebalancing.title')}</Title>
        <SyncBadge />
      </div>

      <Card style={{ marginBottom: '1.5rem', borderTop: '3px solid #0066CC' }}>
        <CardTitle>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
            <span>{t('rebalancing.simulator')}</span>
            <ToggleGroup aria-label="Rebalancing mode">
              <ToggleGroupItem text={t('rebalancing.modes.contribution')} isSelected={rebalMode === 'contribution'}
                onChange={() => setRebalMode('contribution')} />
              <ToggleGroupItem text={t('rebalancing.modes.hybrid')} isSelected={rebalMode === 'hybrid'}
                onChange={() => setRebalMode('hybrid')} />
              <ToggleGroupItem text={t('rebalancing.modes.hard')} isSelected={rebalMode === 'hard'}
                onChange={() => setRebalMode('hard')} />
            </ToggleGroup>
          </div>
        </CardTitle>
        <CardBody>
          {/* Strategy description */}
          <div style={{ padding: '0.6rem 0.9rem', borderRadius: 6, marginBottom: '1rem',
            background: rebalMode === 'contribution' ? '#E8F4FD' : '#FFF3E0',
            borderLeft: `4px solid ${rebalMode === 'contribution' ? '#0066CC' : '#E65100'}`,
            fontSize: '0.85rem', color: '#444' }}>
            {rebalMode === 'contribution'
              ? t('rebalancing.modeDesc.contribution')
              : rebalMode === 'hybrid'
              ? t('rebalancing.modeDesc.hybrid')
              : t('rebalancing.modeDesc.hard')}
          </div>

          {/* Capital input + presets — hidden for Hard Rebalancing (no injection) */}
          {rebalMode !== 'hard' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
              <span style={{ fontSize: '0.8rem', color: '#6A6E73', fontWeight: 600 }}>{t('rebalancing.capitalToInject')}</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input
                  type="number"
                  min={0}
                  step={500}
                  value={injection || ''}
                  onFocus={(e) => e.target.select()}
                  onChange={(e) => handleInjectionChange(Number(e.target.value) || 0)}
                  style={{ width: 120, padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, fontSize: '0.9rem' }}
                />
                <span style={{ fontSize: '0.8rem', color: '#6A6E73' }}>+ {formatEUR(dashboard?.liquidity_eur ?? 0)} liquidités</span>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', alignItems: 'flex-end', paddingBottom: '2px' }}>
              {[0, 1000, 5000, 10000, 20000, 50000].map(v => (
                <button key={v} onClick={() => handleInjectionChange(v)} style={{
                  padding: '4px 10px', borderRadius: 4, fontSize: '0.78rem', cursor: 'pointer',
                  border: injection === v ? '2px solid #0066CC' : '1px solid #ccc',
                  background: injection === v ? '#E8F0FE' : '#f5f5f5',
                  color: injection === v ? '#0066CC' : '#444', fontWeight: injection === v ? 'bold' : 'normal',
                }}>
                  {v === 0 ? t('rebalancing.cashOnly') : `+${v >= 1000 ? v/1000 + 'k' : /* v8 ignore next -- @preserve */ v}€`}
                </button>
              ))}
            </div>
            {rebalLoading && <span style={{ fontSize: '0.8rem', color: '#6A6E73' }}>{t('rebalancing.calculating')}</span>}
          </div>
          )}
          {rebalMode === 'hard' && rebalLoading && (
            <div style={{ marginBottom: '1rem' }}>
              <span style={{ fontSize: '0.8rem', color: '#6A6E73' }}>{t('rebalancing.calculating')}</span>
            </div>
          )}

          {/* Commission inputs */}
          <details style={{ marginBottom: '1rem' }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.85rem', color: '#6A6E73', userSelect: 'none' }}>
              {t('rebalancing.brokerage')}
            </summary>
            <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '0.6rem', alignItems: 'flex-end' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                <label style={{ fontSize: '0.78rem', color: '#6A6E73', fontWeight: 600 }} htmlFor="commission-pct">
                  {t('rebalancing.commissionPct')}
                </label>
                <input
                  id="commission-pct"
                  type="number"
                  min={0}
                  step={0.01}
                  value={commissionPct || ''}
                  placeholder="ex: 0.1"
                  onChange={(e) => {
                    const v = parseFloat(e.target.value) || 0;
                    handleCommissionChange(v, commissionMin);
                  }}
                  style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc', fontSize: '0.9rem', width: 110 }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                <label style={{ fontSize: '0.78rem', color: '#6A6E73', fontWeight: 600 }} htmlFor="commission-min">
                  {t('rebalancing.commissionMin')}
                </label>
                <input
                  id="commission-min"
                  type="number"
                  min={0}
                  step={0.01}
                  value={commissionMin || ''}
                  placeholder="ex: 1.00"
                  onChange={(e) => {
                    const v = parseFloat(e.target.value) || 0;
                    handleCommissionChange(commissionPct, v);
                  }}
                  style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #ccc', fontSize: '0.9rem', width: 110 }}
                />
              </div>
              <div style={{ fontSize: '0.78rem', color: '#6A6E73', paddingBottom: '6px' }}>
                {t('rebalancing.commissionFormula')}
              </div>
            </div>
          </details>

          {rebalData && (() => {
            const pools = (rebalData.pools ?? []).filter((p: any) => p.target_pct > 0);
            const budget = (rebalData.total_apport ?? 0);
            const totalCurrent = rebalData.total_current ?? 0;
            const showFees = commissionPct > 0 || commissionMin > 0;

            // injection_total_needed is computed server-side (single source of truth,
            // shared with the actual "injection seule" allocation algorithm) — see
            // compute_injection_total_needed in rebalancing_service.py. null means even
            // an unlimited injection can't reach every target without selling.
            const totalNeeded: number | null = rebalData.injection_total_needed ?? null;
            const isFullyRebalanced = totalNeeded !== null && budget >= totalNeeded - 0.5;

            // Always name the total capital being distributed on its own line — liquidity
            // already sitting on the account plus whatever was typed into "Capital à injecter".
            const liquidityNote = t('rebalancing.liquidityIncluded', { liquidity: formatEUR(budget) });

            // Pools with target_pct≈0 that still hold real value (e.g. a "Legacy" pool) —
            // see find_untargeted_pools_with_value in rebalancing_service.py. Their presence
            // is *why* injection_total_needed can be null; name them instead of a vague
            // "even with unlimited capital" message.
            const blockingPools = rebalData.injection_blocking_pools ?? [];
            const blockingAmount = blockingPools.reduce((s: number, p: any) => s + p.current_value, 0);
            const blockingNames = blockingPools.map((p: any) => p.name).join(', ');

            return (
              <>
                {/* Sufficiency banner */}
                {rebalMode === 'contribution' && budget > 0 && (
                  <div style={{ padding: '0.5rem 1rem', borderRadius: 6, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.75rem',
                    background: isFullyRebalanced ? '#E6F4EA' : '#FFF3E0',
                    border: `1px solid ${isFullyRebalanced ? '#34A853' : '#E65100'}` }}>
                    <span style={{ fontSize: '1.2rem' }}>{isFullyRebalanced ? '✅' : '⚠️'}</span>
                    <div style={{ fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
                      {isFullyRebalanced ? (
                        <>
                          <div><strong style={{ color: '#137333' }}>{t('rebalancing.sufficientCapital')}</strong></div>
                          <div>{liquidityNote}</div>
                        </>
                      ) : totalNeeded === null ? (
                        <>
                          <div>
                            <strong style={{ color: '#E65100' }}>
                              {blockingPools.length > 0
                                ? t('rebalancing.insufficientImpossibleWithCause', { amount: formatEUR(blockingAmount), pools: blockingNames })
                                : t('rebalancing.insufficientImpossible')}
                            </strong>
                          </div>
                          <div style={{ color: '#E65100' }}>{t('rebalancing.switchModeHint')}</div>
                          <div>{liquidityNote}</div>
                        </>
                      ) : (
                        <>
                          <div>
                            <strong style={{ color: '#E65100' }}>{t('rebalancing.insufficientCapital')}</strong>
                            {' '}{t('rebalancing.insufficientDetail', { gap: formatEUR(totalNeeded - budget), available: formatEUR(budget), needed: formatEUR(totalNeeded) })}
                          </div>
                          <div>{liquidityNote}</div>
                        </>
                      )}
                    </div>
                  </div>
                )}

                {/* Banner Hybrid */}
                {rebalMode === 'hybrid' && (() => {
                  const residualGap = pools.reduce((sum: number, p: any) => {
                    const afterValue = p.current_value + p.hybrid_amount;
                    const targetValue = rebalData.total_after * p.target_pct;
                    return sum + Math.max(0, targetValue - afterValue);
                  }, 0.0);
                  const isHybridSufficient = residualGap < 0.50;

                  return (
                    <div style={{ padding: '0.5rem 1rem', borderRadius: 6, marginBottom: '1rem',
                      display: 'flex', alignItems: 'center', gap: '0.75rem',
                      background: isHybridSufficient ? '#E6F4EA' : '#FFF3E0',
                      border: `1px solid ${isHybridSufficient ? '#34A853' : '#E65100'}` }}>
                      <span style={{ fontSize: '1.2rem' }}>{isHybridSufficient ? '✅' : '⚠️'}</span>
                      <div style={{ fontSize: '0.85rem', display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
                        {isHybridSufficient ? (
                          <>
                            <div><strong style={{ color: '#137333' }}>{t('rebalancing.hybridSufficient')}</strong></div>
                            <div>{liquidityNote}</div>
                          </>
                        ) : (
                          <>
                            <div><strong style={{ color: '#E65100' }}>{t('rebalancing.hybridPartial', { gap: formatEUR(residualGap) })}</strong></div>
                            <div style={{ color: '#E65100' }}>{t('rebalancing.hybridPartialHint')}</div>
                            <div>{liquidityNote}</div>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })()}

                {/* Pool simulation grid */}
                <div style={{ display: 'grid', gap: '0.75rem' }}>
                  {pools.map((p: any) => {
                    const amount = rebalMode === 'contribution' ? p.injection_amount
                    : rebalMode === 'hybrid' ? p.hybrid_amount
                    : p.rebalance_amount;
                    const fee = rebalMode === 'contribution' ? (p.injection_fee ?? 0)
                    : rebalMode === 'hybrid' ? (p.hybrid_fee ?? 0)
                    : (p.rebalance_fee ?? 0);
                    const net = rebalMode === 'contribution' ? (p.injection_net ?? 0)
                    : rebalMode === 'hybrid' ? (p.hybrid_net ?? 0)
                    : (p.rebalance_net ?? 0);
                    const afterValue = p.current_value + amount;
                    // "hard" (Rééquilibrage complet) never injects liquidity — rebalance_amount
                    // is computed against total_current, so the resulting % must be too.
                    // total_after (which includes uninvested cash) only applies when this
                    // mode's amount actually grows the total (contribution/hybrid).
                    const afterTotal = rebalMode === 'hard' ? totalCurrent : rebalData.total_after;
                    const afterPct = afterTotal > 0 ? afterValue / afterTotal * 100 : 0;
                    const targetPct = p.target_pct * 100;
                    const currentPct = p.current_pct;
                    const isSell = amount < -0.01;
                    const gapBefore = currentPct - targetPct;
                    const gapAfter = afterPct - targetPct;
                    const levelBefore = severityLevel(gapBefore, toleranceOkPct, toleranceWarningPct);
                    const levelAfter = severityLevel(gapAfter, toleranceOkPct, toleranceWarningPct);
                    // Self-explanatory label text — severity only, no over/under direction (a
                    // pool with no action could be overweight or under-funded; that distinction
                    // still surfaces via underweightTooltip below, just not in the label itself).
                    const severityLabelKey = levelBefore === 'ok' ? 'onTargetLabel'
                      : levelBefore === 'warning' ? 'warningLabel' : 'dangerLabel';
                    const severityLabelText = t(`rebalancing.${severityLabelKey}`, { ok: toleranceOkPct, warning: toleranceWarningPct });

                    return (
                      <div key={p.id} style={{ border: '1px solid #e8e8e8', borderRadius: 8, padding: '0.75rem 1rem',
                        background: '#fafafa', borderLeft: `4px solid ${p.strategy === 'Offensive' ? '#0066CC' : '#3E8635'}` }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                          <div>
                            <strong>{p.name}</strong>
                            <span style={{ marginLeft: '0.5rem', fontSize: '0.75rem', padding: '1px 6px', borderRadius: 3,
                              background: p.strategy === 'Offensive' ? '#E8F0FE' : '#E6F4EA',
                              color: p.strategy === 'Offensive' ? '#1967D2' : '#137333' }}>
                              {p.strategy}
                            </span>
                          </div>
                          <div style={{ textAlign: 'right' }}>
                            {Math.abs(amount) > 0.01 ? (
                              <div style={{ textAlign: 'right' }}>
                                <span style={{ fontSize: '1rem', fontWeight: 'bold',
                                  color: isSell ? '#D93025' : '#137333' }}>
                                  {isSell ? `🔴 ${t('rebalancing.actions.sell')} ` : `🟢 ${t('rebalancing.actions.buy')} `}
                                  <strong>{formatEUR(Math.abs(amount))}</strong>
                                </span>
                                {showFees && fee > 0 && (
                                  <div style={{ fontSize: '0.75rem', color: '#6A6E73', marginTop: '2px' }}>
                                    {t('rebalancing.fees')} <strong style={{ color: '#E65100' }}>{formatEUR(fee)}</strong>
                                    {' '}— {t('rebalancing.net')} <strong>{formatEUR(Math.abs(net))}</strong>
                                  </div>
                                )}
                              </div>
                            ) : levelBefore !== 'ok' && gapBefore < 0 ? (
                              <Tooltip content={t('rebalancing.underweightTooltip')}>
                                <span style={{ color: SEVERITY_TEXT_COLOR[levelBefore], fontSize: '0.85rem', cursor: 'help', textDecoration: 'underline dotted' }}>
                                  {severityLabelText}
                                </span>
                              </Tooltip>
                            ) : (
                              <span style={{ color: SEVERITY_TEXT_COLOR[levelBefore], fontSize: '0.85rem' }}>{severityLabelText}</span>
                            )}
                          </div>
                        </div>

                        {/* Target label, shown once above both bars since it's shared by Actuel/Après */}
                        <div style={{ fontSize: '0.72rem', color: '#6A6E73', textAlign: 'right', marginBottom: '0.25rem' }}>
                          {t('common.target')} : {targetPct.toFixed(1)}%
                        </div>

                        {/* Before / After bars, each with its own inline gap label */}
                        <div style={{ display: 'grid', gridTemplateColumns: '60px 1fr 50px 120px', gap: '0.4rem', alignItems: 'center', fontSize: '0.75rem' }}>
                          <span style={{ color: '#6A6E73', textAlign: 'right' }}>{t('common.current')}</span>
                          {/* targetPct > 0 guaranteed by filter(p.target_pct > 0) — scale is always targetPct * 1.5 */}
                          {(() => { const scale = targetPct * 1.5; return (
                          <div style={{ position: 'relative', height: 14, background: '#e8e8e8', borderRadius: 7 }}>
                            <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', borderRadius: 7,
                              background: SEVERITY_BAR_COLOR[levelBefore],
                              width: `${Math.min(100, currentPct / scale * 100)}%`, transition: 'width 0.3s' }} />
                            <div style={{ position: 'absolute', top: 0, height: '100%', width: 2, background: '#444',
                              left: `${Math.min(100, targetPct / scale * 100)}%` }} />
                          </div>
                          ); })()}
                          <span style={{ color: SEVERITY_TEXT_COLOR[levelBefore], fontWeight: 'bold' }}>
                            {currentPct.toFixed(1)}%
                          </span>
                          <span style={{ color: SEVERITY_TEXT_COLOR[levelBefore], fontSize: '0.7rem' }}>
                            {t('rebalancing.gapCurrent')} : <strong>{gapBefore > 0 ? '+' : ''}{gapBefore.toFixed(1)}%</strong>
                          </span>

                          <span style={{ color: '#6A6E73', textAlign: 'right' }}>{t('rebalancing.after')}</span>
                          {(() => { const scale = targetPct * 1.5; return (
                          <div style={{ position: 'relative', height: 14, background: '#e8e8e8', borderRadius: 7 }}>
                            <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', borderRadius: 7,
                              background: SEVERITY_BAR_COLOR[levelAfter],
                              width: `${Math.min(100, afterPct / scale * 100)}%`, transition: 'width 0.4s' }} />
                            <div style={{ position: 'absolute', top: 0, height: '100%', width: 2, background: '#444',
                              left: `${Math.min(100, targetPct / scale * 100)}%` }} />
                          </div>
                          ); })()}
                          <span style={{ color: SEVERITY_TEXT_COLOR[levelAfter], fontWeight: 'bold' }}>
                            {afterPct.toFixed(1)}%
                          </span>
                          <span style={{ color: SEVERITY_TEXT_COLOR[levelAfter], fontSize: '0.7rem' }}>
                            {t('rebalancing.gapTarget')} : <strong>{gapAfter > 0 ? '+' : ''}{gapAfter.toFixed(1)}%</strong>
                          </span>
                        </div>

                        <div style={{ marginTop: '0.4rem', fontSize: '0.75rem', color: '#6A6E73' }}>
                          {formatEUR(p.current_value)} → {formatEUR(afterValue)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            );
          })()}

          {!rebalData && (
            <div style={{ textAlign: 'center', color: '#6A6E73', padding: '1.5rem', fontSize: '0.9rem',
              border: '2px dashed #e0e0e0', borderRadius: 8 }}>
              {t('rebalancing.noDataHint')}
            </div>
          )}
        </CardBody>
      </Card>
    </PageSection>
  );
}
