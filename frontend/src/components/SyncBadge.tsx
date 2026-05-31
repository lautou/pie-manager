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

  const tooltipContent = sync.status === 'partial' && sync.failed_tickers.length > 0
    ? `${t('syncBadge.failed')} : ${sync.failed_tickers.join(', ')}`
    : sync.status === 'failed'
    ? t('syncBadge.failed')
    : sync.status === 'success'
    ? t('syncBadge.synced')
    : label;

  return (
    <Tooltip content={tooltipContent}>
      <span style={{ fontSize: '0.78rem', color, cursor: 'default', whiteSpace: 'nowrap' }}>
        {icon} {label}
      </span>
    </Tooltip>
  );
}
