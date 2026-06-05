import { useIsFetching } from '@tanstack/react-query';
import { Spinner } from '@patternfly/react-core';
import { useTranslation } from 'react-i18next';

// Background polling queries that run silently on their own interval —
// they should not trigger the visible refresh banner.
const BACKGROUND_QUERY_KEYS = new Set(['github-update-status', 'sync-status']);

export default function RefreshBanner() {
  const { t } = useTranslation();
  const isFetching = useIsFetching({
    predicate: (query) => !BACKGROUND_QUERY_KEYS.has(query.queryKey[0] as string),
  });
  if (!isFetching) return null;

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 9999,
      backgroundColor: 'var(--pf-v5-global--palette--blue-100)',
      borderBottom: '2px solid var(--pf-v5-global--palette--blue-300)',
      padding: '4px 16px',
      display: 'flex', alignItems: 'center', gap: '8px',
      fontSize: '0.8rem', color: 'var(--pf-v5-global--palette--blue-700)',
    }}>
      <Spinner size="sm" />
      {t('refreshBanner.newDataAvailable')}
    </div>
  );
}
