// SPDX-License-Identifier: AGPL-3.0-or-later
import { useTranslation } from 'react-i18next';
import { Label, Tooltip } from '@patternfly/react-core';
import { ExclamationTriangleIcon } from '@patternfly/react-icons';

/** Badge naming the source of a position's last known price ("manual" or a sync provider). */
export function PriceSourceBadge({ source }: { source: string }) {
  const { t } = useTranslation();
  if (source === 'manual') {
    return (
      <Label color="orange" style={{ gap: '0.25rem' }}>
        <Tooltip content={t('positions.manualPriceTooltip')}>
          <ExclamationTriangleIcon style={{ cursor: 'pointer' }} />
        </Tooltip>
        manual
      </Label>
    );
  }
  return <Label color="blue">{source}</Label>;
}

/** Badge warning that a position's last known price is missing or more than 2 days old. */
export function StalePriceBadge({ lastPriceDate, source }: { lastPriceDate: string | null; source: string }) {
  const { t } = useTranslation();
  if (source === 'manuel' || source === 'manual') return null;
  if (lastPriceDate === null) {
    return (
      <Label color="orange" isCompact style={{ marginLeft: '0.25rem', verticalAlign: 'middle' }}>
        {t('positions.priceUnknown')}
      </Label>
    );
  }
  const diffDays = Math.floor(
    (Date.now() - new Date(lastPriceDate).getTime()) / (1000 * 60 * 60 * 24),
  );
  if (diffDays <= 2) return null;
  return (
    <Label color="orange" isCompact style={{ marginLeft: '0.25rem', verticalAlign: 'middle' }}>
      {t('positions.priceDaysOld', { days: diffDays })}
    </Label>
  );
}
