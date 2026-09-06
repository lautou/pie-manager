// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
	Button,
	Card,
	CardBody,
	CardTitle,
	EmptyState,
	EmptyStateBody,
	PageSection,
	PageSectionVariants,
	Spinner,
	Content,
	TextInput,
	ContentVariants,
	Title
} from '@patternfly/react-core';
import { ImportIcon, MagicIcon, PencilAltIcon, PlusCircleIcon, TrashIcon } from '@patternfly/react-icons';
import {
  usePortfolios, useCreatePortfolio, useRenamePortfolio, useDeletePortfolio, useCreateDemoPortfolio,
} from '../api/queries';
import { extractApiErrorMessage } from '../utils/errors';
import ConfirmModal from '../components/ConfirmModal';

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' });
}

export default function PortfolioSelectPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data: portfolios, isLoading, isError } = usePortfolios();
  const createPortfolio = useCreatePortfolio();
  const renamePortfolio = useRenamePortfolio();
  const deletePortfolio = useDeletePortfolio();
  const createDemoPortfolio = useCreateDemoPortfolio();

  const [createOpen, setCreateOpen] = useState(false);
  const [demoOpen, setDemoOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [deleteConfirmName, setDeleteConfirmName] = useState('');
  const [renameTarget, setRenameTarget] = useState<{ id: number; name: string } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; name: string } | null>(null);
  const [error, setError] = useState('');

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setError('');
    try {
      await createPortfolio.mutateAsync({ name: newName.trim() });
      setCreateOpen(false);
      setNewName('');
    } catch (e) {
      setError(extractApiErrorMessage(e, 'Erreur'));
    }
  };

  const handleRename = async () => {
    if (!renameTarget || !renameTarget.name.trim()) return;
    setError('');
    try {
      await renamePortfolio.mutateAsync({ id: renameTarget.id, name: renameTarget.name });
      setRenameTarget(null);
    } catch (e) {
      setError(extractApiErrorMessage(e, 'Erreur'));
    }
  };

  const handleDelete = async () => {
    /* v8 ignore next -- @preserve */
    if (!deleteTarget || deleteConfirmName !== deleteTarget.name) return;
    await deletePortfolio.mutateAsync(deleteTarget.id);
    setDeleteTarget(null);
    setDeleteConfirmName('');
  };

  const handleGenerateDemo = async () => {
    setError('');
    try {
      const demo = await createDemoPortfolio.mutateAsync();
      setDemoOpen(false);
      navigate(`/portfolio/${demo.id}/dashboard`);
    } catch (e) {
      setError(extractApiErrorMessage(e, 'Erreur'));
    }
  };

  return (
    <PageSection hasBodyWrapper={false} variant={PageSectionVariants.default}>
      <Content style={{ marginBottom: '2rem', textAlign: 'center' }}>
        <Title headingLevel="h1" size="2xl">{t('app.name')}</Title>
        <Content component={ContentVariants.p}>{t('portfolioSelect.title')}</Content>
      </Content>

      {isLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
          <Spinner size="xl" />
        </div>
      )}

      {isError && (
        <Content style={{ textAlign: 'center', color: 'var(--pf-t--global--text--color--status--danger--default)' }}>
          <Content component="p">Erreur lors du chargement.</Content>
        </Content>
      )}

      {/* Empty state */}
      {!isLoading && !isError && portfolios?.length === 0 && (
        <EmptyState titleText={<Title headingLevel="h2" size="lg">{t('portfolioSelect.noPortfolios')}</Title>}>
          <EmptyStateBody>
            Commencez par créer votre premier portefeuille,<br />
            ou restaurez une sauvegarde depuis Administration système.
          </EmptyStateBody>
          <Button variant="primary" icon={<PlusCircleIcon />} onClick={() => setCreateOpen(true)}>
            {t('portfolioSelect.createPortfolio')}
          </Button>
          <div style={{ marginTop: '1rem' }}>
            <Button variant="secondary" icon={<MagicIcon />} onClick={() => { setDemoOpen(true); setError(''); }}>
              {t('portfolioSelect.generateDemo')}
            </Button>
          </div>
          <div style={{ marginTop: '1rem' }}>
            <Button variant="link" component="a" href="/system">
              Administration système (restaurer une sauvegarde)
            </Button>
          </div>
        </EmptyState>
      )}

      {/* Portfolio list */}
      {portfolios && portfolios.length > 0 && (
        <>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1.5rem', justifyContent: 'center', marginBottom: '2rem' }}>
            {portfolios.map((portfolio) => (
              <div key={portfolio.id} style={{ width: '300px', flexShrink: 0 }}>
                <Card  style={{ cursor: 'default', height: '100%' }}>
                  <CardTitle>
                    <span
                      style={{ cursor: 'pointer', color: 'var(--pf-t--global--text--color--link--default)', fontSize: '1.1rem', fontWeight: 'bold' }}
                      onClick={() => navigate(`/portfolio/${portfolio.id}/dashboard`)}
                    >
                      {portfolio.name}
                    </span>
                  </CardTitle>
                  <CardBody>
                    {fmtDate(portfolio.created_at) && (
                      <div style={{ fontSize: '0.8rem', color: '#6A6E73', marginBottom: '1rem' }}>
                        Créé le {fmtDate(portfolio.created_at)}
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                      <Button variant="primary" size="sm"
                        onClick={() => navigate(`/portfolio/${portfolio.id}/dashboard`)}>
                        {t('portfolioSelect.open')}
                      </Button>
                      <Button variant="secondary" size="sm" icon={<ImportIcon />}
                        onClick={() => navigate(`/portfolio/${portfolio.id}/import`)}>
                        {t('common.import')}
                      </Button>
                      <Button variant="secondary" size="sm" icon={<PencilAltIcon />}
                        onClick={() => { setRenameTarget({ id: portfolio.id, name: portfolio.name }); setError(''); }}>
                        {t('portfolioSelect.rename')}
                      </Button>
                      <Button variant="danger" size="sm" icon={<TrashIcon />}
                        onClick={() => setDeleteTarget({ id: portfolio.id, name: portfolio.name })}>
                        {t('common.delete')}
                      </Button>
                    </div>
                  </CardBody>
                </Card>
              </div>
            ))}
          </div>

          <div style={{ textAlign: 'center', display: 'flex', gap: '0.5rem', justifyContent: 'center' }}>
            <Button variant="secondary" icon={<PlusCircleIcon />} onClick={() => { setCreateOpen(true); setError(''); setNewName(''); }}>
              {t('portfolioSelect.newPortfolio')}
            </Button>
            <Button variant="secondary" icon={<MagicIcon />} onClick={() => { setDemoOpen(true); setError(''); }}>
              {t('portfolioSelect.generateDemo')}
            </Button>
          </div>
          <div style={{ textAlign: 'center' }}>
            <Button variant="tertiary" onClick={() => navigate('/system')} style={{ marginTop: '1rem' }}>
              ⚙️ Administration système
            </Button>
          </div>
        </>
      )}

      {/* Create modal */}
      <ConfirmModal
        isOpen={createOpen}
        title={t('portfolioSelect.newPortfolio')}
        variant="primary"
        confirmLabel={t('common.create')}
        isLoading={createPortfolio.isPending}
        onConfirm={handleCreate}
        onCancel={() => { setCreateOpen(false); setError(''); }}
      >
        <TextInput placeholder="Nom du portefeuille" value={newName}
          onChange={(_e, v) => setNewName(v)}
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()} />
        {error && <div style={{ color: 'var(--pf-t--global--text--color--status--danger--default)', marginTop: '0.5rem', fontSize: '0.85rem' }}>{error}</div>}
      </ConfirmModal>

      {/* Rename modal */}
      <ConfirmModal
        isOpen={!!renameTarget}
        title={t('portfolioSelect.editPortfolio')}
        variant="primary"
        confirmLabel={t('portfolioSelect.rename')}
        isLoading={renamePortfolio.isPending}
        onConfirm={handleRename}
        onCancel={() => { setRenameTarget(null); setError(''); }}
      >
        <TextInput value={renameTarget?.name ?? ''}
          onChange={(_e, v) => setRenameTarget(
            /* v8 ignore next -- @preserve */
            t => t ? { ...t, name: v } : t,
          )}
          onKeyDown={(e) => e.key === 'Enter' && handleRename()} />
        {error && <div style={{ color: 'var(--pf-t--global--text--color--status--danger--default)', marginTop: '0.5rem', fontSize: '0.85rem' }}>{error}</div>}
      </ConfirmModal>

      {/* Delete confirmation modal — GitHub-style name confirmation */}
      <ConfirmModal
        isOpen={!!deleteTarget}
        title="Supprimer le portefeuille"
        variant="danger"
        confirmLabel={t('portfolioSelect.deleteConfirmButton')}
        isLoading={deletePortfolio.isPending}
        isConfirmDisabled={deleteConfirmName !== deleteTarget?.name}
        onConfirm={handleDelete}
        onCancel={() => { setDeleteTarget(null); setDeleteConfirmName(''); }}
      >
        <Content component={ContentVariants.p}>
          Cette action est <strong>irréversible</strong>. Toutes les transactions,
          snapshots et données associées au portefeuille{' '}
          <strong>{deleteTarget?.name}</strong> seront définitivement supprimés.
        </Content>
        <div style={{ marginTop: '1.25rem' }}>
          <div style={{ fontSize: '0.85rem', marginBottom: '0.4rem', color: '#6A6E73' }}>
            Saisissez <strong>{deleteTarget?.name}</strong> pour confirmer :
          </div>
          <TextInput
            value={deleteConfirmName}
            onChange={(_e, v) => setDeleteConfirmName(v)}
            onPaste={(e) => e.preventDefault()}
            placeholder={deleteTarget?.name}
            validated={deleteConfirmName === deleteTarget?.name ? 'success' : deleteConfirmName ? 'error' : 'default'}
            aria-label="Confirmer le nom du portefeuille"
            autoComplete="off"
          />
          <div style={{ fontSize: '0.75rem', color: '#6A6E73', marginTop: '0.3rem' }}>
            Le copier-coller est désactivé dans ce champ.
          </div>
        </div>
      </ConfirmModal>

      {/* Generate demo portfolio confirmation modal */}
      <ConfirmModal
        isOpen={demoOpen}
        title={t('portfolioSelect.generateDemoTitle')}
        variant="primary"
        confirmLabel={t('portfolioSelect.generateDemoConfirm')}
        isLoading={createDemoPortfolio.isPending}
        onConfirm={handleGenerateDemo}
        onCancel={() => { setDemoOpen(false); setError(''); }}
      >
        <Content component={ContentVariants.p}>{t('portfolioSelect.generateDemoBody')}</Content>
        {error && <div style={{ color: 'var(--pf-t--global--text--color--status--danger--default)', marginTop: '0.5rem', fontSize: '0.85rem' }}>{error}</div>}
      </ConfirmModal>
    </PageSection>
  );
}
