import { useTranslation } from 'react-i18next';
import {
	Spinner,
	Content,
	ContentVariants,
	Modal,
	ModalBody,
	ModalHeader,
	ModalVariant
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';
import { useEtfComposition } from '../api/queries';
import { formatPct1, formatDate } from '../utils/format';

interface EtfCompositionModalProps {
  ticker: string | null;
  onClose: () => void;
}

export default function EtfCompositionModal({ ticker, onClose }: EtfCompositionModalProps) {
  const { t } = useTranslation();
  const { data, isLoading } = useEtfComposition(ticker ?? undefined);
  const hasComposition = !!data && (data.top_holdings.length > 0 || data.sector_weightings.length > 0);

  return (
    <Modal
      variant={ModalVariant.medium}
      isOpen={ticker !== null}
      onClose={onClose}
    >
      <ModalHeader title={ticker ? t('etfComposition.modalTitle', { ticker }) : ''} />
      <ModalBody>
      {isLoading && <Spinner size="md" />}

      {!isLoading && data && !hasComposition && (
        <Content>
          <Content component={ContentVariants.p}>{t('etfComposition.noData')}</Content>
        </Content>
      )}

      {!isLoading && data && hasComposition && (
        <>
          {data.top_holdings.length > 0 && (
            <>
              <Content>
                <Content component={ContentVariants.h4}>
                  {t('etfComposition.topHoldings')} —{' '}
                  {t('etfComposition.coverageNote', {
                    count: data.top_holdings.length,
                    pct: formatPct1(data.top_holdings_coverage_pct).replace(' %', ''),
                  })}
                </Content>
              </Content>
              <Table variant="compact" aria-label={t('etfComposition.topHoldings')}>
                <Thead>
                  <Tr>
                    <Th>{t('common.ticker')}</Th>
                    <Th>{t('common.name')}</Th>
                    <Th>{t('common.percentage')}</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {data.top_holdings.map((h) => (
                    <Tr key={h.ticker}>
                      <Td>{h.ticker}</Td>
                      <Td>{h.name}</Td>
                      <Td>{formatPct1(h.weight_pct * 100)}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </>
          )}

          {data.sector_weightings.length > 0 && (
            <>
              <Content style={{ marginTop: '1rem' }}>
                <Content component={ContentVariants.h4}>{t('etfComposition.sectorWeightings')}</Content>
              </Content>
              <Table variant="compact" aria-label={t('etfComposition.sectorWeightings')}>
                <Thead>
                  <Tr>
                    <Th>{t('common.sector')}</Th>
                    <Th>{t('common.percentage')}</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {data.sector_weightings.map((s) => (
                    <Tr key={s.sector}>
                      <Td>{t(`sectors.${s.sector}`, s.sector)}</Td>
                      <Td>{formatPct1(s.weight_pct * 100)}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </>
          )}

          {(data.bond_duration !== null || data.bond_maturity !== null) && (
            <Content style={{ marginTop: '1rem' }}>
              {data.bond_duration !== null && (
                <Content component={ContentVariants.p}>
                  {t('etfComposition.bondDuration')}: {data.bond_duration}
                </Content>
              )}
              {data.bond_maturity !== null && (
                <Content component={ContentVariants.p}>
                  {t('etfComposition.bondMaturity')}: {data.bond_maturity}
                </Content>
              )}
            </Content>
          )}

          <Content style={{ marginTop: '1rem' }}>
            <Content component={ContentVariants.small}>
              {data.holdings_updated_at
                ? t('etfComposition.lastUpdated', { date: formatDate(data.holdings_updated_at.slice(0, 10)) })
                : t('etfComposition.neverUpdated')}
            </Content>
          </Content>
        </>
      )}
      </ModalBody>
    </Modal>
  );
}
