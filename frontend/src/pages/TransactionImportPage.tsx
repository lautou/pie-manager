import { useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Checkbox,
  Label,
  PageSection,
  PageSectionVariants,
  Spinner,
  Text,
  TextContent,
  TextVariants,
  Title,
} from '@patternfly/react-core';
import { Table, Thead, Tbody, Tr, Th, Td } from '@patternfly/react-table';
import { DownloadIcon, UploadIcon } from '@patternfly/react-icons';
import { useValidateImport, useCommitImport } from '../api/queries';
import type { ImportRowResult } from '../api/queries';

function extractErrorMessage(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail ?? String(err);
}

function StatusLabel({ status }: { status: ImportRowResult['status'] }) {
  const { t } = useTranslation();
  if (status === 'ok') return <Label color="green" isCompact>{t('import.status.ok')}</Label>;
  if (status === 'duplicate') return <Label color="orange" isCompact>{t('import.status.duplicate')}</Label>;
  return <Label color="red" isCompact>{t('import.status.error')}</Label>;
}

function RowDetail({ row }: { row: ImportRowResult }) {
  const { t } = useTranslation();
  if (row.status === 'error') {
    return <span style={{ color: 'var(--pf-v5-global--danger-color--100)' }}>{row.errors.join(' ')}</span>;
  }
  if (row.status === 'duplicate' && row.duplicate_of) {
    return row.duplicate_of.kind === 'db'
      ? <span>{t('import.duplicateOfDb', { id: row.duplicate_of.transaction_id })}</span>
      : <span>{t('import.duplicateOfFile', { row: row.duplicate_of.row_number })}</span>;
  }
  return row.warnings.length > 0 ? <span>{row.warnings.join(' ')}</span> : null;
}

export default function TransactionImportPage() {
  const { t } = useTranslation();
  const { portfolioId } = useParams<{ portfolioId: string }>();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [rows, setRows] = useState<ImportRowResult[] | null>(null);
  const [included, setIncluded] = useState<Set<number>>(new Set());
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const validateImport = useValidateImport();
  const commitImport = useCommitImport();

  const handleDownloadTemplate = () => {
    // The filename is part of the URL path itself (not just Content-Disposition/the
    // download attribute) — some WebKit-based browsers (e.g. Epiphany, this app's
    // fallback native-window mode on Linux) otherwise name the downloaded file with a
    // random UUID instead of respecting either.
    const filename = 'modele_import_transactions.xlsx';
    const a = document.createElement('a');
    a.href = `/api/transactions/import/template/${filename}`;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    /* v8 ignore next -- @preserve */
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (!selected) return;
    setFile(selected);
    setSuccessMsg(null);
    setErrorMsg(null);
    setRows(null);
    try {
      const result = await validateImport.mutateAsync(selected);
      setRows(result.rows);
      setIncluded(new Set(result.rows.filter((r) => r.status === 'ok').map((r) => r.row_number)));
    } catch (err: unknown) {
      setErrorMsg(extractErrorMessage(err));
    }
  };

  const toggleRow = (rowNumber: number, checked: boolean) => {
    setIncluded((prev) => {
      const next = new Set(prev);
      if (checked) next.add(rowNumber); else next.delete(rowNumber);
      return next;
    });
  };

  const handleCommit = async () => {
    /* v8 ignore next -- @preserve */
    if (!file || !portfolioId) return;
    setSuccessMsg(null);
    setErrorMsg(null);
    try {
      const result = await commitImport.mutateAsync({ file, includeRows: Array.from(included), portfolioId });
      setSuccessMsg(t('import.successMessage', { count: result.imported_count }));
      setRows(null);
      setFile(null);
      setIncluded(new Set());
    } catch (err: unknown) {
      setErrorMsg(t('import.errorMessage', { message: extractErrorMessage(err) }));
    }
  };

  const summary = rows ? {
    ok: rows.filter((r) => r.status === 'ok').length,
    errors: rows.filter((r) => r.status === 'error').length,
    duplicates: rows.filter((r) => r.status === 'duplicate').length,
  } : null;

  return (
    <PageSection variant={PageSectionVariants.default}>
      <Title headingLevel="h1" size="xl" style={{ marginBottom: '0.5rem' }}>
        {t('import.title')}
      </Title>
      <TextContent style={{ marginBottom: '1rem' }}>
        <Text component={TextVariants.p}>{t('import.intro')}</Text>
      </TextContent>

      <Card style={{ marginBottom: '1.5rem' }}>
        <CardBody>
          <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <Button variant="secondary" icon={<DownloadIcon />} onClick={handleDownloadTemplate}>
              {t('import.downloadTemplate')}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx"
              data-testid="import-file-input"
              style={{ display: 'none' }}
              onChange={handleFileChange}
            />
            <Button
              variant="primary"
              icon={<UploadIcon />}
              isLoading={validateImport.isPending}
              isDisabled={validateImport.isPending}
              onClick={() => fileInputRef.current?.click()}
            >
              {t('import.chooseFile')}
            </Button>
          </div>
        </CardBody>
      </Card>

      {validateImport.isPending && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
          <Spinner size="md" aria-label={t('import.validating')} />
          <span>{t('import.validating')}</span>
        </div>
      )}

      {errorMsg && (
        <Alert variant="danger" isInline title={t('error.generic')} style={{ marginBottom: '1rem' }}>
          {errorMsg}
        </Alert>
      )}

      {successMsg && (
        <Alert variant="success" isInline title={t('import.title')} style={{ marginBottom: '1rem' }}>
          {successMsg}
        </Alert>
      )}

      {rows && summary && (
        <Card>
          <CardTitle>{t('import.summary', summary)}</CardTitle>
          <CardBody>
            <div style={{ overflowX: 'auto', marginBottom: '1rem' }}>
              <Table aria-label={t('import.title')} variant="compact">
                <Thead>
                  <Tr>
                    <Th>{t('import.columns.include')}</Th>
                    <Th>{t('import.columns.rowNumber')}</Th>
                    <Th>{t('import.columns.status')}</Th>
                    <Th>{t('import.columns.sens')}</Th>
                    <Th>{t('import.columns.portfolio')}</Th>
                    <Th>{t('import.columns.account')}</Th>
                    <Th>{t('import.columns.ticker')}</Th>
                    <Th>{t('import.columns.date')}</Th>
                    <Th>{t('import.columns.quantity')}</Th>
                    <Th>{t('import.columns.unitPrice')}</Th>
                    <Th>{t('import.columns.currency')}</Th>
                    <Th>{t('import.columns.brokerage')}</Th>
                    <Th>{t('import.columns.ttf')}</Th>
                    <Th>{t('import.columns.error')}</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {rows.map((row) => (
                    <Tr key={row.row_number}>
                      <Td dataLabel={t('import.columns.include')}>
                        <Checkbox
                          id={`import-include-${row.row_number}`}
                          aria-label={t('import.columns.include')}
                          isChecked={included.has(row.row_number)}
                          isDisabled={row.status === 'error'}
                          onChange={(_e, checked) => toggleRow(row.row_number, checked)}
                        />
                      </Td>
                      <Td dataLabel={t('import.columns.rowNumber')}>{row.row_number}</Td>
                      <Td dataLabel={t('import.columns.status')}><StatusLabel status={row.status} /></Td>
                      <Td dataLabel={t('import.columns.sens')}>{row.sens}</Td>
                      <Td dataLabel={t('import.columns.portfolio')}>{row.resolved?.portfolio_name ?? '—'}</Td>
                      <Td dataLabel={t('import.columns.account')}>{row.resolved?.account_name ?? '—'}</Td>
                      <Td dataLabel={t('import.columns.ticker')}>{row.resolved?.ticker ?? '—'}</Td>
                      <Td dataLabel={t('import.columns.date')}>{row.resolved?.date ?? '—'}</Td>
                      <Td dataLabel={t('import.columns.quantity')}>{row.resolved?.quantity ?? '—'}</Td>
                      <Td dataLabel={t('import.columns.unitPrice')}>{row.resolved?.unit_price ?? '—'}</Td>
                      <Td dataLabel={t('import.columns.currency')}>{row.resolved?.currency ?? '—'}</Td>
                      <Td dataLabel={t('import.columns.brokerage')}>{row.resolved?.courtage_eur ?? '—'}</Td>
                      <Td dataLabel={t('import.columns.ttf')}>{row.resolved?.ttf_eur ?? '—'}</Td>
                      <Td dataLabel={t('import.columns.error')}><RowDetail row={row} /></Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </div>

            <Button
              variant="primary"
              isLoading={commitImport.isPending}
              isDisabled={commitImport.isPending || included.size === 0}
              onClick={handleCommit}
            >
              {t('import.confirmImport', { count: included.size })}
            </Button>
          </CardBody>
        </Card>
      )}
    </PageSection>
  );
}
