import { Tooltip } from '@patternfly/react-core';
import { useTranslation } from 'react-i18next';
import { useSyncStatus, formatSyncDateTime } from '../hooks/useSyncStatus';

const STATUS_COLOR: Record<string, string> = {
  success: '#137333',
  partial: '#E65100',
  failed: '#C00',
  running: '#0066CC',
  never: '#6A6E73',
};

const STATUS_ICON: Record<string, string> = {
  success: '🟢',
  partial: '🟡',
  failed: '🔴',
  running: '🔄',
  never: '⚪',
};

export default function SyncBadge() {
  const { t } = useTranslation();
  const { data: sync } = useSyncStatus();

  if (!sync) return null;

  const color = STATUS_COLOR[sync.status] ?? '#6A6E73';
  const icon = STATUS_ICON[sync.status] ?? '⚪';
  const timeLabel = formatSyncDateTime(sync);

  const label = sync.status === 'running'
    ? t('syncBadge.syncing')
    : sync.status === 'never'
    ? 'Jamais synchronisé'
    : t('syncBadge.lastSync', { time: timeLabel });

  // Only the "success" tooltip gets the background-sync note: a stale-looking timestamp next
  // to "Prices up to date" is the one case that could otherwise read as broken rather than as
  // "the app just wasn't open" (issue #83's native-launcher trade-off — the bundled worker only
  // runs while the app itself is running). "partial"/"failed" already convey a real problem on
  // their own and shouldn't be diluted with an unrelated note.
  const tooltipContent = sync.status === 'partial' && sync.failed_tickers.length > 0
    ? `${t('syncBadge.failed')} : ${sync.failed_tickers.join(', ')}`
    : sync.status === 'failed'
    ? t('syncBadge.failed')
    : sync.status === 'success'
    ? `${t('syncBadge.synced')} (${t('syncBadge.backgroundNote')})`
    : label;

  return (
    <Tooltip content={tooltipContent}>
      <span
        data-testid="sync-badge"
        style={{ fontSize: '0.78rem', color, cursor: 'default', whiteSpace: 'nowrap' }}
      >
        {icon} {label}
      </span>
    </Tooltip>
  );
}
