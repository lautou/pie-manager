---
paths:
  - "backend/app/api/routers/transaction_import.py"
  - "backend/app/services/import_service.py"
  - "backend/app/api/routers/transactions.py"
  - "backend/app/api/routers/holdings.py"
  - "backend/tests/test_transactions_crud.py"
  - "backend/tests/test_transactions_cash_balance.py"
  - "backend/tests/test_transactions_balance_branches.py"
  - "backend/tests/test_transactions_fees.py"
  - "backend/tests/test_transactions_fractional.py"
  - "backend/tests/test_pv_service.py"
  - "backend/tests/test_accounts_router.py"
  - "frontend/src/pages/TransactionImportPage.tsx"
  - "frontend/src/pages/PortfolioSelectPage.tsx"
  - "frontend/src/pages/TransactionsPage.tsx"
---

## Bulk transaction import (Excel)

`POST/GET /api/transactions/import/{template,validate,commit}`
(`backend/app/api/routers/transaction_import.py`,
`backend/app/services/import_service.py`) — a recurring-use import for reloading a broker
statement without re-keying every row in the UI. This is a deliberate, narrow exception to
"all data entry goes through the UI": the import **always** funnels through
`create_transaction_core` (see below), never a parallel write path, so every existing
sign/fee/balance rule and its existing test coverage apply unchanged.

**Frontend entry points**: `TransactionImportPage.tsx`, routed at
`/portfolio/:portfolioId/import`, reachable via the "Importer" sidebar nav item (between
Transactions and Performance) **and** a shortcut button directly on each portfolio's card on
`PortfolioSelectPage.tsx` (next to Ouvrir/Renommer/Supprimer) — added since new users landing
on the portfolio-selection screen otherwise had no visible path to bulk import without first
opening a portfolio and finding the nav item.

**`create_transaction_core` extraction.** `create_transaction` (the `POST /api/transactions/`
route) used to `await db.commit()` at the end of its own body. Importing N rows by calling
that route function N times would commit each row individually, making an all-or-nothing
rollback impossible once row N+1 fails. Everything up to (not including) commit/refresh/
snapshot-trigger was extracted into `create_transaction_core(body, db) -> Transaction`; the
route is now a 3-line wrapper around it. The import commit endpoint calls this core function
once per row inside a single DB transaction, and only commits/triggers-snapshot once at the
end if every row succeeded.

**`_trigger_snapshot_recompute(portfolio_id, from_date, queries)` ignores its `portfolio_id`
parameter** — it only enqueues PgQueuer's `compute_daily_snapshots_all_users` (`payload=
from_date.isoformat().encode()`, see `.claude/rules/background-jobs.md`), which recomputes
every portfolio from that date forward regardless of which one is passed. The import commit
endpoint exploits this: it calls this once after the batch commit, with `from_date = min(date
across all imported rows)`, regardless of how many portfolios/accounts the batch touched — no
need to trigger once per portfolio.

**The "Sens" column is the whole design** — the Excel template never asks the user to type a
signed quantity or pick an internal `type`/`operation`; a single human-friendly "Sens" column
drives all three, per `SENS_RULES` in `import_service.py`:

| Sens | `type` | `operation` | Ticker requis | Quantité | Prix unitaire | Courtage | TTF |
|---|---|---|---|---|---|---|---|
| Achat | Actif | Achat | ETF/SICAV-FCP/Action/Obligation | signe `-` | tel quel | ✓ | ✓ (achat seul) |
| Vente | Actif | Vente | idem | signe `+` | tel quel | ✓ | ✗ |
| Achat/Vente Or physique | Actif | Achat/Vente | Or physique | forcé `∓1` | **valeur totale**, pas un prix unitaire | ✓ | achat seul |
| Attribution | Actif | Attribution | idem Achat | signe `-` | optionnel (0 par défaut) | ✗ (rejet si >0) | ✗ |
| Dépôt/Retrait | Actif | `None` | Cash (`LIQUIDITE.*`, `*EUR=X`) | signe `+`/`-` | forcé `1.0` | Retrait seul (frais de retrait broker réel) | ✗ |
| Revenu | Revenu | `None` | idem Achat | signe `+` | tel quel | ✗ | ✗ |
| Frais | Frais | `None` | `category='Frais'` | forcé `-1` | montant du frais | n/a | n/a |

Confirmed against real code/tests before writing this table (not assumed): Attribution's
`quantity` sign matches Achat's (`test_transactions_cash_balance.py:440-481`, `quantity=-3.0`); Revenu's
`quantity`/`unit_price` are positive (`test_transactions_cash_balance.py:701-707`,
`test_pv_service.py:255-264`); Or physique's `quantity` is always `±1` with `unit_price`
holding the total transaction value, never a per-unit price (`test_accounts_router.py:
209-217`, `holdings.py:122`'s `value_eur = price if instrument_type == "Or physique" else
qty * price`). Retrait allows a non-zero Courtage (a real broker withdrawal fee, already
supported by the manual UI via `TransactionsPage.tsx`'s `withdrawalFee` — excluding it from
import would silently drop real relevé data) while every other non-Achat/Vente Sens rejects
the row with a validation error if Courtage/TTF is entered non-zero (not silently forced to 0
— an omitted/blank cell is what defaults to 0).

**Forex-ticker Devise special case**: for a ticker matching `^[A-Z]{3}[A-Z]{3}=X$` (e.g.
`JPYEUR=X`), the expected Devise is the ticker's own 3-letter prefix (`JPY`), never
`Product.currency` (stored as `EUR`, the reference currency, for these tickers) — a naive
"Devise must equal Product.currency" rule would reject every legitimate Dépôt/Retrait row on
a forex position.

**Duplicate detection key** (both in-DB and in-file):
`(portfolio_id, account_id, date, ticker, operation, quantity, unit_price, currency)`
with a `0.005` float tolerance, deliberately excluding `courtage_eur`/`ttf_eur`/
`exchange_rate` — the question is "does this exact trade already exist", not "with identical
fees", so re-importing the same trade with a corrected fee still flags as a duplicate for the
user to review rather than silently creating a second transaction.

**Validate/commit are two independent HTTP calls, not a stateful session.** `/validate`
parses+checks the uploaded file and returns a full per-row preview (`status: "ok"|"error"|
"duplicate"`) without ever writing to the DB. `/commit` takes the **same file re-uploaded**
(never trusts client-echoed resolved data) plus an explicit `include_rows` array of row
numbers to actually import — this is also how a flagged duplicate gets force-included:
put its row number in `include_rows`. Commit re-validates from scratch against the fresh
upload; if any included row comes back `"error"` on this second pass (e.g. a broker was
deleted between the two calls), the whole commit is rejected before a single row is
inserted. If a row fails mid-loop for any other reason, the whole batch is rolled back —
verified with a test that mocks `create_transaction_core` to fail on the second of two rows
and asserts zero transactions exist afterward.

**Rows are always reordered chronologically before commit** (`(portfolio_id, account_id,
date, original_row_number)`) — the file is never required to be pre-sorted, and an unsorted
file is never rejected. This matters because `create_transaction_core`'s running-balance
chain (`balance_eur`) is computed incrementally from the previous row's balance at insertion
time; inserting out of date order would corrupt that chain.

**The downloadable template is generated from live DB data, not fake placeholders** — this
is a personal, local single-user app, so the file never leaves the machine. Example rows are
built by querying real portfolios/brokers/products (`_build_example_rows` in
`import_service.py`), one row per Sens value that has a matching product available; a Sens
with no matching product in the current DB (e.g. a fresh install with no Or physique
holding) is simply skipped, never a crash. The single highest-value test for this feature
(`test_template_example_rows_pass_self_consistency_validation`) generates the template and
immediately re-submits its own example rows through `/validate`, asserting every one comes
back `status="ok"` — a structural guard against the template ever drifting out of sync with
the validation rules in `resolve_row`.

**Bugs found only by live QA testing against real cloned data, not by the unit test suite**
(each fixed, each now has a regression test):
- A non-`.xlsx` upload (wrong file, corrupted file) raises `zipfile.BadZipFile`/
  `openpyxl.utils.exceptions.InvalidFileException` — neither is a `ValueError` subclass, so a
  bare `except ValueError` around the parse call let it escape as a raw 500.
  `parse_uploaded_workbook` now catches these explicitly and re-raises `ValueError` with a
  clean message.
- A blank Portefeuille/Compte/Devise cell reads as Python `None`; interpolating it directly
  into an error message produced the literal text `Portefeuille 'None' introuvable`. Fixed
  with a `_display()` helper rendering `(vide)` instead.
- Text cells (Portefeuille, Compte, Ticker, Devise, Sens, **and the header row itself**) were
  never `.strip()`'d — a trailing space from copy-pasting a broker statement into Excel
  (`"Portfolio 1 "`) or from manually retyping a column header (`"Portefeuille "`) silently failed
  the exact-match dict lookup, rejecting a row that referenced a perfectly real entity. Fixed
  with a `_clean_str()` helper applied to every text field read from a row **and** to the
  header row read in `parse_uploaded_workbook`.
- The "Télécharger le modèle" download could be saved under a random UUID filename instead of
  `modele_import_transactions.xlsx` — some WebKit-based browsers (Epiphany, this app's
  fallback native-window mode on Linux, see `.claude/rules/distribution.md`'s "Native window
  integration" section) ignore
  `Content-Disposition` for a download triggered via a synthetic `<a download>` click. Fixed
  by putting the filename in the URL path itself (`GET /template/{filename}`, the segment is
  otherwise unused) — the one download-naming signal virtually every browser/webview respects.

Deliberately-injected garbage (SQL-injection-style strings in Sens/Portefeuille, 300-character
tickers, emoji/unicode portfolio names, unevaluated Excel formula cells, rows with fewer cells
than the header, quantities of 1,000,000+) all degrade to a clean per-row validation error with
zero crashes — confirmed live, not just by reasoning about the code. No new handling was needed
for these; they're listed here as evidence the existing validation/error-accumulation design
already covers them, in case a future change is tempted to add defensive code that isn't needed.

