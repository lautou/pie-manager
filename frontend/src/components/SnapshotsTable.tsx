// SPDX-License-Identifier: AGPL-3.0-or-later
import React, { useCallback, useMemo, useState } from 'react';
import {
  Card, CardBody, CardTitle,
  Pagination,
  Content, ContentVariants,
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';
import { formatEUR } from '../utils/format';
import type { DailySnapshot } from '../types';

interface SnapshotsTableProps {
  sortedDaily: DailySnapshot[];
  snapPage: number;
  setSnapPage: (page: number) => void;
  onRowClick: (snap: DailySnapshot) => void;
}

const SnapshotRow = React.memo(function SnapshotRow({
  snap,
  onRowClick,
}: {
  snap: DailySnapshot;
  onRowClick: (snap: DailySnapshot) => void;
}) {
  const handleClick = useCallback(() => onRowClick(snap), [onRowClick, snap]);
  return (
    <Tr style={{ cursor: 'pointer' }} onRowClick={handleClick}>
      <Td>{snap.date}</Td>
      <Td>{formatEUR(snap.total_eur)}</Td>
      <Td>{formatEUR(snap.offensive_eur)}</Td>
      <Td>{formatEUR(snap.defensive_eur)}</Td>
    </Tr>
  );
});

function SnapshotsTable({
  sortedDaily,
  snapPage,
  setSnapPage,
  onRowClick,
}: SnapshotsTableProps) {
  const [perPage, setPerPage] = useState(15);

  const reversed = useMemo(() => [...sortedDaily].reverse(), [sortedDaily]);

  const totalPages = useMemo(
    () => Math.ceil(reversed.length / perPage),
    [reversed.length, perPage],
  );

  const page = Math.min(snapPage, totalPages || 1);

  const pageItems = useMemo(
    () => reversed.slice((page - 1) * perPage, page * perPage),
    [reversed, page, perPage],
  );

  const handleSetPage = useCallback(
    (_e: React.MouseEvent | React.KeyboardEvent | MouseEvent, p: number) =>
      setSnapPage(p),
    [setSnapPage],
  );

  const handlePerPageSelect = useCallback(
    (_e: React.MouseEvent | React.KeyboardEvent | MouseEvent, newPerPage: number) => {
      setPerPage(newPerPage);
      setSnapPage(1);
    },
    [setSnapPage],
  );

  return (
    <Card>
      <CardTitle>Snapshots journaliers ({sortedDaily.length})</CardTitle>
      <CardBody>
        {sortedDaily.length === 0 ? (
          <Content>
            <Content component={ContentVariants.p}>Aucun snapshot disponible.</Content>
          </Content>
        ) : (
          <>
            <Table aria-label="Snapshots journaliers" variant="compact">
              <Thead>
                <Tr>
                  <Th>Date</Th>
                  <Th>Total EUR</Th>
                  <Th>Offensif EUR</Th>
                  <Th>Défensif EUR</Th>
                </Tr>
              </Thead>
              <Tbody>
                {pageItems.map((s) => (
                  <SnapshotRow key={s.id} snap={s} onRowClick={onRowClick} />
                ))}
              </Tbody>
            </Table>
            <Pagination
              itemCount={reversed.length}
              perPage={perPage}
              page={page}
              onSetPage={handleSetPage}
              onPerPageSelect={handlePerPageSelect}
              perPageOptions={[
                { title: '15', value: 15 },
                { title: '25', value: 25 },
                { title: '50', value: 50 },
              ]}
              isCompact
              style={{ marginTop: '0.5rem' }}
            />
          </>
        )}
      </CardBody>
    </Card>
  );
}

export default React.memo(SnapshotsTable);
