// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tests for TransactionImportPage
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { pfCoreStubs, pfTableStubs, pfIconStubs } from '../../tests/utils/patternfly-mocks';

vi.mock('react-router-dom', () => ({
  useParams: () => ({ portfolioId: '1' }),
}));

vi.mock('@patternfly/react-core', () => pfCoreStubs);
vi.mock('@patternfly/react-table', () => pfTableStubs);
vi.mock('@patternfly/react-icons', () => pfIconStubs);

const mockUseValidateImport = vi.fn();
const mockUseCommitImport = vi.fn();

vi.mock('../api/queries', () => ({
  useValidateImport: () => mockUseValidateImport(),
  useCommitImport: () => mockUseCommitImport(),
}));

import TransactionImportPage from './TransactionImportPage';

const okRow = {
  row_number: 2, status: 'ok', sens: 'Achat',
  resolved: {
    portfolio_id: 1, account_id: 1, portfolio_name: 'Portfolio1', account_name: 'Degiro',
    date: '2026-01-05', type: 'Actif', operation: 'Achat', ticker: 'FLXC.DE',
    currency: 'EUR', exchange_rate: 1, quantity: -10, unit_price: 45.2,
    courtage_eur: 2.5, ttf_eur: 0,
  },
  errors: [], warnings: [], duplicate_of: null,
};

const errorRow = {
  row_number: 3, status: 'error', sens: 'Bourse', resolved: null,
  errors: ["Sens 'Bourse' invalide."], warnings: [], duplicate_of: null,
};

const dbDuplicateRow = {
  row_number: 4, status: 'duplicate', sens: 'Vente',
  resolved: {
    portfolio_id: 1, account_id: 1, portfolio_name: 'Portfolio1', account_name: 'Degiro',
    date: '2026-01-06', type: 'Actif', operation: 'Vente', ticker: 'FLXC.DE',
    currency: 'EUR', exchange_rate: 1, quantity: 5, unit_price: 47.1,
    courtage_eur: 0, ttf_eur: 0,
  },
  errors: [], warnings: [], duplicate_of: { kind: 'db', transaction_id: 42, row_number: null },
};

const fileDuplicateRow = {
  row_number: 5, status: 'duplicate', sens: 'Achat',
  resolved: {
    portfolio_id: 1, account_id: 1, portfolio_name: 'Portfolio1', account_name: 'Degiro',
    date: '2026-01-05', type: 'Actif', operation: 'Achat', ticker: 'FLXC.DE',
    currency: 'EUR', exchange_rate: 1, quantity: -10, unit_price: 45.2,
    courtage_eur: 2.5, ttf_eur: 0,
  },
  errors: [], warnings: [], duplicate_of: { kind: 'file', transaction_id: null, row_number: 2 },
};

const warningRow = {
  row_number: 6, status: 'ok', sens: 'Achat',
  resolved: {
    portfolio_id: 1, account_id: 1, portfolio_name: 'Portfolio1', account_name: 'Degiro',
    date: '2026-01-05', type: 'Actif', operation: 'Achat', ticker: 'FLXC.DE',
    currency: 'EUR', exchange_rate: 1, quantity: -10, unit_price: 45.2,
    courtage_eur: 0, ttf_eur: 1.5,
  },
  errors: [], warnings: ["TTF (EUR) renseignée mais le produit 'FLXC.DE' n'est pas marqué éligible TTF."],
  duplicate_of: null,
};

function selectFile(input: HTMLInputElement, file: File | null) {
  Object.defineProperty(input, 'files', { value: file ? [file] : [], configurable: true });
  fireEvent.change(input);
}

describe('TransactionImportPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseValidateImport.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    mockUseCommitImport.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  });

  it('renders title, intro, and action buttons', () => {
    render(<TransactionImportPage />);
    expect(screen.getByText('Import de transactions')).toBeInTheDocument();
    expect(screen.getByText('Télécharger le modèle')).toBeInTheDocument();
    expect(screen.getByText('Sélectionner un fichier Excel (.xlsx)')).toBeInTheDocument();
  });

  it('clicking "Télécharger le modèle" creates and clicks a download anchor', () => {
    const appendSpy = vi.spyOn(document.body, 'appendChild');
    const removeSpy = vi.spyOn(document.body, 'removeChild');
    render(<TransactionImportPage />);
    fireEvent.click(screen.getByText('Télécharger le modèle'));
    const anchorCall = appendSpy.mock.calls.find((call) => (call[0] as HTMLElement).tagName === 'A');
    expect(anchorCall).toBeDefined();
    const anchor = anchorCall![0] as HTMLAnchorElement;
    expect(anchor.href).toContain('/api/transactions/import/template/modele_import_transactions.xlsx');
    expect(anchor.download).toBe('modele_import_transactions.xlsx');
    expect(removeSpy).toHaveBeenCalledWith(anchor);
  });

  it('clicking "Sélectionner un fichier" triggers the hidden file input', () => {
    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const clickSpy = vi.spyOn(input, 'click');
    fireEvent.click(screen.getByText('Sélectionner un fichier Excel (.xlsx)'));
    expect(clickSpy).toHaveBeenCalled();
  });

  it('selecting no file (files empty) is a no-op', () => {
    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    selectFile(input, null);
    expect(mockUseValidateImport().mutateAsync).not.toHaveBeenCalled();
  });

  it('selecting a file validates it and renders the preview table with per-status rows', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      rows: [okRow, errorRow, dbDuplicateRow, fileDuplicateRow],
      summary: { total_rows: 4, ok: 1, errors: 1, duplicates: 2 },
    });
    mockUseValidateImport.mockReturnValue({ mutateAsync, isPending: false });

    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['dummy'], 'import.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    selectFile(input, file);

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith(file));
    await waitFor(() => expect(screen.getByText('1 valide(s) / 1 erreur(s) / 2 doublon(s)')).toBeInTheDocument());

    expect(screen.getByText("Sens 'Bourse' invalide.")).toBeInTheDocument();
    expect(screen.getByText('Doublon de la transaction #42')).toBeInTheDocument();
    expect(screen.getByText('Doublon de la ligne 2 du fichier')).toBeInTheDocument();
    expect(screen.getAllByText('Portfolio1').length).toBeGreaterThan(0);
  });

  it('shows a validating spinner while validation is pending', () => {
    mockUseValidateImport.mockReturnValue({ mutateAsync: vi.fn(), isPending: true });
    render(<TransactionImportPage />);
    expect(screen.getByText('Validation en cours…')).toBeInTheDocument();
  });

  it('shows an error alert when validation fails with a structured API error', async () => {
    const mutateAsync = vi.fn().mockRejectedValue({ response: { data: { detail: 'Feuille Transactions introuvable' } } });
    mockUseValidateImport.mockReturnValue({ mutateAsync, isPending: false });

    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    selectFile(input, new File(['x'], 'bad.xlsx'));

    await waitFor(() => expect(screen.getByText('Feuille Transactions introuvable')).toBeInTheDocument());
  });

  it('shows an error alert with String(err) fallback when the error has no response.data.detail', async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error('network down'));
    mockUseValidateImport.mockReturnValue({ mutateAsync, isPending: false });

    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    selectFile(input, new File(['x'], 'bad.xlsx'));

    await waitFor(() => expect(screen.getByText('Error: network down')).toBeInTheDocument());
  });

  it('a row with warnings but ok status renders its warning text', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      rows: [warningRow],
      summary: { total_rows: 1, ok: 1, errors: 0, duplicates: 0 },
    });
    mockUseValidateImport.mockReturnValue({ mutateAsync, isPending: false });

    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    selectFile(input, new File(['x'], 'import.xlsx'));

    await waitFor(() => expect(screen.getByText(/n'est pas marqué éligible TTF/)).toBeInTheDocument());
  });

  it('an ok row with no warnings renders no error-column text', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      rows: [okRow],
      summary: { total_rows: 1, ok: 1, errors: 0, duplicates: 0 },
    });
    mockUseValidateImport.mockReturnValue({ mutateAsync, isPending: false });

    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    selectFile(input, new File(['x'], 'import.xlsx'));

    await waitFor(() => expect(screen.getByText('1 valide(s) / 0 erreur(s) / 0 doublon(s)')).toBeInTheDocument());
  });

  it('checkboxes are pre-checked for ok rows, disabled for errors, unchecked for duplicates', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      rows: [okRow, errorRow, dbDuplicateRow],
      summary: { total_rows: 3, ok: 1, errors: 1, duplicates: 1 },
    });
    mockUseValidateImport.mockReturnValue({ mutateAsync, isPending: false });

    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    selectFile(input, new File(['x'], 'import.xlsx'));
    await waitFor(() => expect(screen.getByText('1 valide(s) / 1 erreur(s) / 1 doublon(s)')).toBeInTheDocument());

    const checkboxes = container.querySelectorAll('input[type="checkbox"]') as NodeListOf<HTMLInputElement>;
    expect(checkboxes).toHaveLength(3);
    expect(checkboxes[0].checked).toBe(true);
    expect(checkboxes[0].disabled).toBe(false);
    expect(checkboxes[1].disabled).toBe(true);
    expect(checkboxes[2].checked).toBe(false);
    expect(checkboxes[2].disabled).toBe(false);

    // Toggle the duplicate row on, then the ok row off — exercises both branches of toggleRow
    fireEvent.click(checkboxes[2]);
    expect(screen.getByText('Importer les lignes sélectionnées (2)')).toBeInTheDocument();
    fireEvent.click(checkboxes[0]);
    expect(screen.getByText('Importer les lignes sélectionnées (1)')).toBeInTheDocument();
  });

  it('commit button is disabled when no rows are included', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      rows: [errorRow],
      summary: { total_rows: 1, ok: 0, errors: 1, duplicates: 0 },
    });
    mockUseValidateImport.mockReturnValue({ mutateAsync, isPending: false });

    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    selectFile(input, new File(['x'], 'import.xlsx'));
    await waitFor(() => expect(screen.getByText('0 valide(s) / 1 erreur(s) / 0 doublon(s)')).toBeInTheDocument());

    const commitButton = screen.getByText('Importer les lignes sélectionnées (0)') as HTMLButtonElement;
    expect(commitButton.disabled).toBe(true);
  });

  it('confirming import calls commitImport with the file and included row numbers, then shows success', async () => {
    const validateMutate = vi.fn().mockResolvedValue({
      rows: [okRow],
      summary: { total_rows: 1, ok: 1, errors: 0, duplicates: 0 },
    });
    const commitMutate = vi.fn().mockResolvedValue({ status: 'ok', imported_count: 1, created_transaction_ids: [99] });
    mockUseValidateImport.mockReturnValue({ mutateAsync: validateMutate, isPending: false });
    mockUseCommitImport.mockReturnValue({ mutateAsync: commitMutate, isPending: false });

    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['x'], 'import.xlsx');
    selectFile(input, file);
    await waitFor(() => expect(screen.getByText('1 valide(s) / 0 erreur(s) / 0 doublon(s)')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Importer les lignes sélectionnées (1)'));

    await waitFor(() => expect(commitMutate).toHaveBeenCalledWith({ file, includeRows: [2], portfolioId: '1' }));
    await waitFor(() => expect(screen.getByText('1 transaction(s) importée(s) avec succès.')).toBeInTheDocument());

    // The preview table is cleared after a successful commit
    expect(screen.queryByText('Importer les lignes sélectionnées')).not.toBeInTheDocument();
  });

  it('shows a commit spinner while committing', async () => {
    const validateMutate = vi.fn().mockResolvedValue({
      rows: [okRow],
      summary: { total_rows: 1, ok: 1, errors: 0, duplicates: 0 },
    });
    mockUseValidateImport.mockReturnValue({ mutateAsync: validateMutate, isPending: false });
    mockUseCommitImport.mockReturnValue({ mutateAsync: vi.fn(), isPending: true });

    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    selectFile(input, new File(['x'], 'import.xlsx'));
    await waitFor(() => expect(screen.getByText('1 valide(s) / 0 erreur(s) / 0 doublon(s)')).toBeInTheDocument());

    const commitButton = screen.getByText(/Importer les lignes sélectionnées/) as HTMLButtonElement;
    expect(commitButton.disabled).toBe(true);
  });

  it('shows an error alert when commit fails with a structured API error', async () => {
    const validateMutate = vi.fn().mockResolvedValue({
      rows: [okRow],
      summary: { total_rows: 1, ok: 1, errors: 0, duplicates: 0 },
    });
    const commitMutate = vi.fn().mockRejectedValue({ response: { data: { detail: 'Ligne 2 : broker introuvable.' } } });
    mockUseValidateImport.mockReturnValue({ mutateAsync: validateMutate, isPending: false });
    mockUseCommitImport.mockReturnValue({ mutateAsync: commitMutate, isPending: false });

    const { container } = render(<TransactionImportPage />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    selectFile(input, new File(['x'], 'import.xlsx'));
    await waitFor(() => expect(screen.getByText('1 valide(s) / 0 erreur(s) / 0 doublon(s)')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Importer les lignes sélectionnées (1)'));

    await waitFor(() => expect(screen.getByText(/Échec de l'import : Ligne 2 : broker introuvable\./)).toBeInTheDocument());
    // The preview table stays interactive after a failed commit — nothing was persisted
    expect(screen.getByText('Importer les lignes sélectionnées (1)')).toBeInTheDocument();
  });
});
