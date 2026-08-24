// SPDX-License-Identifier: AGPL-3.0-or-later
// Shared between TransactionsPage.tsx (main page + TransactionModal JSX) and
// useTransactionForm.ts (TransactionModal's extracted logic) — kept in its own
// module to avoid a circular import between the page and the hook.
/* v8 ignore next -- @preserve */
export const TRANSACTION_TYPES = ['Dépôt/Retrait', 'Actif', 'Frais', 'Revenu'] as const;
/* v8 ignore next -- @preserve */
export const LIQUIDITE_TICKER = 'LIQUIDITE.EURO';
