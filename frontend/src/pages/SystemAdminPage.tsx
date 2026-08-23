// SPDX-License-Identifier: AGPL-3.0-or-later
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Alert, Button, Card, CardBody, CardTitle,
  PageSection, PageSectionVariants,
  Progress, ProgressMeasureLocation,
  Content, ContentVariants,
} from '@patternfly/react-core';
import { DatabaseIcon, DownloadIcon, SyncAltIcon, UploadIcon } from '@patternfly/react-icons';
import { useQueryClient } from '@tanstack/react-query';
import FrDatePicker from '../components/FrDatePicker';
import ConfirmModal from '../components/ConfirmModal';
import {
  triggerRecompute, getTaskStatus,
} from '../api/queries';
import { REFRESH_KEYS } from '../hooks/useAutoRefresh';
import { useSyncStatus, formatSyncDateTime } from '../hooks/useSyncStatus';
import { localDateStr } from '../utils/format';
import apiClient from '../api/client';
import type { TaskStatus } from '../api/queries';

const yesterday = () => localDateStr(-1);

// ── Product Management sub-component ──────────────────────────────────────

// ── GitHub Update section ──────────────────────────────────────────────────


// ── System Admin page ──────────────────────────────────────────────────────

export default function SystemAdminPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState(yesterday());
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);

  // Backup / Restore
  const [isBackingUp, setIsBackingUp] = useState(false);
  const [isRestoring, setIsRestoring] = useState(false);
  const [restoreMsg, setRestoreMsg] = useState<{ type: 'success' | 'danger'; text: string } | null>(null);
  const [pendingRestoreFile, setPendingRestoreFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { data: syncStatus } = useSyncStatus();

  const handleManualSync = async () => {
    setIsSyncing(true);
    try {
      await apiClient.post('/api/admin/refresh-prices');
      // Give the worker a few seconds then refresh status + data
      setTimeout(() => {
        REFRESH_KEYS.forEach((key) => qc.invalidateQueries({ queryKey: [key] }));
        setIsSyncing(false);
      }, 4000);
    } catch {
      setIsSyncing(false);
    }
  };

  const handleBackup = async () => {
    setIsBackingUp(true);
    try {
      // Use a relative URL so the request goes through Nginx (which proxies
      // /api/ to the backend). WebKit2 intercepts the binary response via the
      // RESPONSE policy handler and saves it to ~/Downloads/.
      const filename = `pie_backup_${new Date().toISOString().slice(0, 10)}.dump`;
      const a = document.createElement('a');
      a.href = '/api/admin/backup';
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (e) {
      /* v8 ignore next -- @preserve */
      alert(t('admin.backup') + ' : ' + String(e));
    } finally {
      setIsBackingUp(false);
    }
  };

  const handleRestoreFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPendingRestoreFile(file);
  };

  const handleCancelRestore = () => {
    setPendingRestoreFile(null);
    /* v8 ignore next -- @preserve */
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleConfirmRestore = async () => {
    const file = pendingRestoreFile;
    /* v8 ignore next -- @preserve */
    if (!file) return;
    setPendingRestoreFile(null);
    setIsRestoring(true);
    setRestoreMsg(null);
    try {
      const form = new FormData();
      form.append('file', file);
      await apiClient.post('/api/admin/restore', form, { headers: { 'Content-Type': 'multipart/form-data' } });
      setRestoreMsg({ type: 'success', text: 'Restauration réussie. Rechargez la page pour voir les données mises à jour.' });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? String(err);
      setRestoreMsg({ type: 'danger', text: msg });
    } finally {
      setIsRestoring(false);
      /* v8 ignore next -- @preserve */
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleRun = async () => {
    setError(null);
    setTaskStatus(null);
    setIsRunning(true);

    try {
      const taskId = await triggerRecompute(startDate, endDate);
      // Poll every 2 seconds
      const poll = async () => {
        const status = await getTaskStatus(taskId);
        setTaskStatus(status);
        if (status.state === 'PROGRESS' || status.state === 'PENDING') {
          setTimeout(poll, 2000);
        } else {
          setIsRunning(false);
        }
      };
      setTimeout(poll, 1000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
      setIsRunning(false);
    }
  };

  const pct = taskStatus?.total
    ? Math.round((taskStatus.current / taskStatus.total) * 100)
    : 0;

  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
      <Content style={{ marginBottom: '1.5rem' }}>
        <Content component={ContentVariants.h1}>{t('systemAdmin.title')}</Content>
      </Content>

      {/* ── Synchronisation manuelle ── */}
      <Card style={{ maxWidth: 640, marginBottom: '1.5rem' }}>
        <CardTitle><SyncAltIcon style={{ marginRight: '0.5rem' }} />Synchronisation des prix</CardTitle>
        <CardBody>
          <Content style={{ marginBottom: '1rem' }}>
            <Content component={ContentVariants.p}>
              Les prix sont automatiquement récupérés toutes les 15 minutes via PgQueuer.
              Utilisez ce bouton uniquement pour forcer une synchronisation immédiate.
            </Content>
            {syncStatus && syncStatus.status !== 'never' && (
              <Content component={ContentVariants.small} style={{ color: '#6A6E73' }}>
                Dernière synchro : {formatSyncDateTime(syncStatus)}
                {syncStatus.failed_tickers.length > 0 && (
                  <span style={{ color: '#E65100', marginLeft: '0.5rem' }}>
                    — Échec : {syncStatus.failed_tickers.join(', ')}
                  </span>
                )}
              </Content>
            )}
          </Content>
          <Button
            variant="secondary"
            icon={<SyncAltIcon />}
            isLoading={isSyncing || syncStatus?.status === 'running'}
            isDisabled={isSyncing || syncStatus?.status === 'running'}
            onClick={handleManualSync}
          >
            {isSyncing || syncStatus?.status === 'running' ? t('syncBadge.syncing') : t('admin.syncNow')}
          </Button>
        </CardBody>
      </Card>

      {/* ── Sauvegarde / Restauration ── */}
      <Card style={{ maxWidth: 640, marginBottom: '1.5rem' }}>
        <CardTitle><DatabaseIcon style={{ marginRight: '0.5rem' }} />{t('admin.backup')}</CardTitle>
        <CardBody>
          <Content style={{ marginBottom: '1rem' }}>
            <Content component={ContentVariants.p}>
              La sauvegarde génère un dump SQL complet de la base de données. La restauration est
              <strong> transactionnelle</strong> : si une seule instruction échoue, toute l'opération
              est annulée et la base reste intacte.
            </Content>
          </Content>

          <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <Button
              variant="primary"
              icon={<DownloadIcon />}
              isLoading={isBackingUp}
              isDisabled={isBackingUp}
              onClick={handleBackup}
            >
              {t('admin.backupDownload')}
            </Button>

            <input
              ref={fileInputRef}
              type="file"
              accept=".dump"
              style={{ display: 'none' }}
              onChange={handleRestoreFile}
            />
            <Button
              variant="danger"
              icon={<UploadIcon />}
              isLoading={isRestoring}
              isDisabled={isRestoring}
              onClick={() => fileInputRef.current?.click()}
            >
              {t('admin.restore')}
            </Button>
          </div>

          {restoreMsg && (
            <Alert
              variant={restoreMsg.type}
              isInline
              title={restoreMsg.type === 'success' ? t('admin.restore') : t('error.generic')}
              style={{ marginTop: '1rem' }}
            >
              {restoreMsg.text}
            </Alert>
          )}
        </CardBody>
      </Card>

      <ConfirmModal
        isOpen={!!pendingRestoreFile}
        title={t('admin.restore')}
        message={[
          `Restaurer la base depuis "${pendingRestoreFile?.name ?? ''}" ?`,
          "ATTENTION : toutes les données actuelles seront remplacées si la restauration réussit. L'opération est transactionnelle : en cas d'erreur, rien n'est modifié.",
        ]}
        confirmLabel={t('common.confirm')}
        isLoading={isRestoring}
        onConfirm={handleConfirmRestore}
        onCancel={handleCancelRestore}
      />

      <Card style={{ maxWidth: 640 }}>
        <CardTitle>{t('admin.regenerateSnapshots')}</CardTitle>
        <CardBody>
          <Content style={{ marginBottom: '1rem' }}>
            <Content component={ContentVariants.p}>
              Recalcule les snapshots de performance pour tous les utilisateurs
              sur la plage de dates sélectionnée, en utilisant les prix disponibles
              dans la base (yfinance + prix manuels). Les prix de l'or saisis
              manuellement sont préservés.
            </Content>
          </Content>

          <Alert
            variant="info"
            isInline
            title="Or physique (auCoffre)"
            style={{ marginBottom: '1rem' }}
          >
            Les prix de l'or non disponibles via Yahoo Finance sont ignorés pour
            les dates sans prix manuel. Le dernier prix connu est utilisé.
          </Alert>

          <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
            <div>
              <div style={{ marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>{t('admin.from')}</div>
              <FrDatePicker value={startDate} onChange={setStartDate} />
            </div>
            <div>
              <div style={{ marginBottom: '0.25rem', fontSize: '0.85rem', fontWeight: 600 }}>
                {t('admin.to')}
              </div>
              <FrDatePicker
                value={endDate}
                onChange={(iso) => {
                  if (iso <= yesterday()) setEndDate(iso);
                }}
              />
            </div>
            <Button
              variant="primary"
              icon={<SyncAltIcon />}
              isLoading={isRunning}
              isDisabled={isRunning || !startDate || !endDate}
              onClick={handleRun}
            >
              {isRunning ? t('common.loading') : t('admin.runRecompute')}
            </Button>
          </div>

          {error && (
            <Alert variant="danger" isInline title={t('error.generic')} style={{ marginBottom: '1rem' }}>
              {error}
            </Alert>
          )}

          {taskStatus && (
            <div>
              {(taskStatus.state === 'PENDING' || taskStatus.state === 'PROGRESS') && (
                <>
                  <div style={{ marginBottom: '0.5rem', fontSize: '0.85rem', color: '#6A6E73' }}>
                    {taskStatus.state === 'PENDING'
                      ? 'En attente de démarrage…'
                      : (() => {
                          /* v8 ignore next -- @preserve */
                          const d = taskStatus.date ?? '';
                          return `Traitement : ${d} (${taskStatus.current}/${taskStatus.total})`;
                        })()}
                  </div>
                  <Progress
                    value={pct}
                    measureLocation={ProgressMeasureLocation.outside}
                    aria-label="Progression du recalcul"
                  />
                </>
              )}
              {taskStatus.state === 'SUCCESS' && (
                <Alert variant="success" isInline title={t('admin.snapshotsRegenerated')} />
              )}
              {taskStatus.state === 'FAILURE' && (
                <Alert variant="danger" isInline title={`Erreur : ${taskStatus.error}`} />
              )}
            </div>
          )}
        </CardBody>
      </Card>
    </PageSection>
  );
}
