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
import {
	Modal,
	ModalVariant
} from '@patternfly/react-core/deprecated';
import { ImportIcon, PencilAltIcon, PlusCircleIcon, TrashIcon } from '@patternfly/react-icons';
import { usePortfolios, useCreatePortfolio, useRenamePortfolio, useDeletePortfolio } from '../api/queries';

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

  const [createOpen, setCreateOpen] = useState(false);
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
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Erreur');
    }
  };

  const handleRename = async () => {
    if (!renameTarget || !renameTarget.name.trim()) return;
    setError('');
    try {
      await renamePortfolio.mutateAsync({ id: renameTarget.id, name: renameTarget.name });
      setRenameTarget(null);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Erreur');
    }
  };

  const handleDelete = async () => {
    /* v8 ignore next -- @preserve */
    if (!deleteTarget || deleteConfirmName !== deleteTarget.name) return;
    await deletePortfolio.mutateAsync(deleteTarget.id);
    setDeleteTarget(null);
    setDeleteConfirmName('');
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
        <Content style={{ textAlign: 'center', color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--danger-color--100 */ }}>
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
                      style={{ cursor: 'pointer', color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--link--Color */, fontSize: '1.1rem', fontWeight: 'bold' }}
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

          <div style={{ textAlign: 'center' }}>
            <Button variant="secondary" icon={<PlusCircleIcon />} onClick={() => { setCreateOpen(true); setError(''); setNewName(''); }}>
              {t('portfolioSelect.newPortfolio')}
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
      <Modal variant={ModalVariant.small} title={t('portfolioSelect.newPortfolio')} isOpen={createOpen}
        onClose={() => { setCreateOpen(false); setError(''); }}
        actions={[
          <Button key="ok" variant="primary" onClick={handleCreate} isLoading={createPortfolio.isPending}>{t('common.create')}</Button>,
          <Button key="cancel" variant="link" onClick={() => setCreateOpen(false)}>{t('common.cancel')}</Button>,
        ]}>
        <TextInput placeholder="Nom du portefeuille" value={newName}
          onChange={(_e, v) => setNewName(v)}
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()} />
        {error && <div style={{ color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--danger-color--100 */, marginTop: '0.5rem', fontSize: '0.85rem' }}>{error}</div>}
      </Modal>

      {/* Rename modal */}
      <Modal variant={ModalVariant.small} title={t('portfolioSelect.editPortfolio')} isOpen={!!renameTarget}
        onClose={() => { setRenameTarget(null); setError(''); }}
        actions={[
          <Button key="ok" variant="primary" onClick={handleRename} isLoading={renamePortfolio.isPending}>{t('portfolioSelect.rename')}</Button>,
          <Button key="cancel" variant="link" onClick={() => setRenameTarget(null)}>{t('common.cancel')}</Button>,
        ]}>
        <TextInput value={renameTarget?.name ?? ''}
          onChange={(_e, v) => setRenameTarget(
            /* v8 ignore next -- @preserve */
            t => t ? { ...t, name: v } : t,
          )}
          onKeyDown={(e) => e.key === 'Enter' && handleRename()} />
        {error && <div style={{ color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--danger-color--100 */, marginTop: '0.5rem', fontSize: '0.85rem' }}>{error}</div>}
      </Modal>

      {/* Delete confirmation modal — GitHub-style name confirmation */}
      <Modal variant={ModalVariant.small}
        title={<span style={{ color: "var(--pf-t--temp--dev--tbd)"/* CODEMODS: original v5 color was --pf-v5-global--danger-color--100 */ }}>⚠ Supprimer le portefeuille</span>}
        isOpen={!!deleteTarget}
        onClose={() => { setDeleteTarget(null); setDeleteConfirmName(''); }}
        actions={[
          <Button key="ok" variant="danger"
            isDisabled={deleteConfirmName !== deleteTarget?.name}
            onClick={handleDelete}
            isLoading={deletePortfolio.isPending}>
            {t('portfolioSelect.deleteConfirmButton')}
          </Button>,
          <Button key="cancel" variant="link" onClick={() => { setDeleteTarget(null); setDeleteConfirmName(''); }}>{t('common.cancel')}</Button>,
        ]}>
        <div>
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
        </div>
      </Modal>
    </PageSection>
  );
}
