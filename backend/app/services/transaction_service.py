# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Transaction ledger business logic: create/update/delete core mutations, running-balance
(balance_eur/balance_currency) computation and propagation, account cash-balance updates, and
auto-linked courtage/TTF fee handling.

Extracted from app.api.routers.transactions, which used to hold this ~450-line ledger engine
directly — every other domain in this app (pv_service, rebalancing_service, snapshot_service,
macro_indicators_service...) already has a dedicated service module; transactions, the most
business-critical, highest-risk domain, was the one exception. The router now only does
request validation (via Depends/get_or_404), calls the *_core functions below, and owns
commit/refresh/snapshot-trigger — the same split create_transaction_core already established
for the bulk-import feature (app.services.import_service), now applied consistently to
update/delete too.
"""
from __future__ import annotations

from typing import Optional
from datetime import date as Date

from fastapi import HTTPException
from pgqueuer import Queries
from pydantic import BaseModel, model_validator
from sqlalchemy import select, func as sa_func, cast, Numeric, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, Broker, PortfolioAccount
from app.services.price_service import r2


class ExecutionItem(BaseModel):
    """One execution of a fractional order (additional executions beyond the first)."""
    date: Date
    quantity: float
    unit_price: float
    exchange_rate: float = 1.0


class TransactionCreate(BaseModel):
    portfolio_id: int
    account_id: int
    date: Date
    type: str
    ticker: str
    currency: str
    exchange_rate: float = 1.0
    quantity: float
    unit_price: float
    balance_currency: Optional[float] = None
    balance_eur: Optional[float] = None
    linked_transaction_id: Optional[int] = None
    # Sub-classification for type='Actif': Achat / Vente / Attribution (free grant)
    operation: Optional[str] = None
    # Auto-created linked fee transactions (brokerage + TTF); ignored for non-Actif types
    courtage_eur: float = 0.0
    ttf_eur: float = 0.0
    # Fractional order: additional executions after the first
    additional_executions: list[ExecutionItem] = []

    # Derived fields are auto-computed in validator
    unit_price_eur: Optional[float] = None
    total_amount: Optional[float] = None
    total_amount_eur: Optional[float] = None

    @model_validator(mode="after")
    def compute_derived(self):
        self.unit_price_eur = self.unit_price * self.exchange_rate
        self.total_amount = self.quantity * self.unit_price
        self.total_amount_eur = self.total_amount * self.exchange_rate
        return self


class TransactionUpdate(BaseModel):
    date: Optional[Date] = None
    type: Optional[str] = None
    ticker: Optional[str] = None
    currency: Optional[str] = None
    exchange_rate: Optional[float] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    balance_currency: Optional[float] = None
    balance_eur: Optional[float] = None
    linked_transaction_id: Optional[int] = None
    # Sub-classification for type='Actif': Achat / Vente / Attribution (free grant)
    operation: Optional[str] = None
    # When provided, linked fee transactions (brokerage + TTF) are replaced with new values
    courtage_eur: Optional[float] = None
    ttf_eur: Optional[float] = None


def _no_neg_zero(v: float) -> float:
    """Normalize IEEE 754 negative zero (-0.0) to positive zero."""
    return v + 0.0


async def trigger_snapshot_recompute(portfolio_id: int, from_date: Date, queries: Queries) -> None:
    """portfolio_id is intentionally unused — compute_daily_snapshots_all_users recomputes
    ALL portfolios regardless (unchanged behavior, not addressed in this step)."""
    await queries.enqueue("compute_daily_snapshots_all_users", payload=from_date.isoformat().encode())


def _is_forex_position(tx_type: str, ticker: str) -> bool:
    """True for a currency-pair position transaction (JPYEUR=X, USDEUR=X, ...) that is
    NOT a fee. These track a forex position's EUR-equivalent value for WACOP/PV purposes
    (see pv_service.py's instrument_type='Cash' AND ticker not LIKE 'LIQUIDITE.%'
    distinction), not a real EUR cash flow — the EUR side of a conversion is captured separately by a
    manually-entered LIQUIDITE.EUR transaction. Fee transactions are excluded from this
    check even when they share the parent's forex ticker (e.g. a EUR-denominated Revolut
    FX commission), since fees are always a real cash cost. See CLAUDE.md's
    "Transaction running-balance display" section for the full history of this bug.
    """
    return ticker.endswith("EUR=X") and tx_type != "Frais"


def _contributes_to_ledger(operation: Optional[str]) -> bool:
    """False for a free share Attribution — it never moves any cash or running-balance
    ledger even though total_amount_eur may carry a recorded fair-value cost basis for
    WACOP (pv_service.py). True for everything else (Achat/Vente/None for Frais/Revenu).

    Uses the transaction's CURRENT operation value everywhere (not an old/new split) —
    same level of rigor this file already applies to tx_type/ticker changes. Reclassifying
    an existing transaction's operation (e.g. Achat -> Attribution) in the same edit as an
    amount/date change is a rare correction scenario; the ledger delta in that edge case
    may be imprecise, matching the existing behavior for type/ticker changes.
    """
    return operation != "Attribution"


async def _prev_balance_eur(
    db: AsyncSession, account_id: int, portfolio_id: int, before_date: Date, before_id: int,
) -> Optional[float]:
    """Latest balance_eur strictly before (before_date, before_id) on this account — i.e.
    date < before_date, or same date with a lower id. Shared by every "find the running
    balance to build on top of" lookup in this file (create, fractional siblings, auto-
    created fees, and update's date-move/backfill paths) — same query shape, only the pivot
    (date, id) and what the caller does with the result differ."""
    result = await db.execute(
        select(Transaction.balance_eur)
        .where(
            Transaction.account_id == account_id,
            Transaction.portfolio_id == portfolio_id,
            Transaction.balance_eur.isnot(None),
            Transaction.id != before_id,
            (Transaction.date < before_date) |
            ((Transaction.date == before_date) & (Transaction.id < before_id)),
        )
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(1)
    )
    value = result.scalar_one_or_none()
    return float(value) if value is not None else None


async def _prev_balance_currency(
    db: AsyncSession, account_id: int, portfolio_id: int, currency: str, before_date: Date, before_id: int,
) -> Optional[float]:
    """Same as _prev_balance_eur, but for the per-currency balance_currency chain (only
    relevant for non-EUR transactions, since EUR balance_currency always equals balance_eur)."""
    result = await db.execute(
        select(Transaction.balance_currency)
        .where(
            Transaction.account_id == account_id,
            Transaction.portfolio_id == portfolio_id,
            Transaction.currency == currency,
            Transaction.balance_currency.isnot(None),
            Transaction.id != before_id,
            (Transaction.date < before_date) |
            ((Transaction.date == before_date) & (Transaction.id < before_id)),
        )
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(1)
    )
    value = result.scalar_one_or_none()
    return float(value) if value is not None else None


async def _propagate_balance_eur_delta(
    db: AsyncSession, account_id: int, portfolio_id: int, after_date: Date, after_id: int, delta: float,
    *, synchronize_session: bool | str | None = None,
) -> None:
    """Adds `delta` to balance_eur of every transaction on this account strictly after
    (after_date, after_id) — i.e. date > after_date, or same date with a higher id. Callers
    already guard on `delta != 0`/`_contributes_to_ledger` before calling, so this issues the
    UPDATE unconditionally. `synchronize_session` is threaded through explicitly rather than
    defaulted — update_transaction_core's date-move path relies on `False` there (it flushes
    and manages session state itself around these calls), while create_transaction_core's
    single call leaves it unset; preserved exactly as each call site had it before this was
    extracted, not normalized to one choice."""
    stmt = (
        sa_update(Transaction)
        .where(
            Transaction.account_id == account_id,
            Transaction.portfolio_id == portfolio_id,
            Transaction.balance_eur.isnot(None),
            (Transaction.date > after_date) |
            ((Transaction.date == after_date) & (Transaction.id > after_id)),
        )
        .values(balance_eur=sa_func.round(cast(Transaction.balance_eur + delta, Numeric), 2))
    )
    if synchronize_session is not None:
        stmt = stmt.execution_options(synchronize_session=synchronize_session)
    await db.execute(stmt)


async def _update_account_cash_balance(
    db: AsyncSession, account_id: int, portfolio_id: int, delta: float, tx_type: str, ticker: str,
    operation: Optional[str] = None,
) -> None:
    """Update portfolio_accounts.cash_balance_eur by adding delta (positive or negative).

    cash_balance_eur is now per (broker, portfolio) pair on the portfolio_accounts join table.
    Any transaction affects the account cash balance (not just LIQUIDITE.EURO):
    - Buying assets: negative total_amount_eur → cash decreases
    - Selling assets, dividends, deposits: positive → cash increases
    - Fees: negative → cash decreases
    Forex-position transactions (see _is_forex_position) and free share Attributions
    (see _contributes_to_ledger) are skipped entirely.
    """
    if _is_forex_position(tx_type, ticker) or not _contributes_to_ledger(operation):
        return
    result = await db.execute(
        select(PortfolioAccount).where(
            PortfolioAccount.broker_id == account_id,
            PortfolioAccount.portfolio_id == portfolio_id,
        )
    )
    pa = result.scalar_one_or_none()
    if pa is not None:
        pa.cash_balance_eur = r2((pa.cash_balance_eur or 0.0) + delta)


async def _create_fee_transaction(
    db: AsyncSession, tx: Transaction, fee_amount: float, fee_ticker: str,
) -> Transaction:
    """Create and balance-stamp an auto-linked courtage/TTF Frais transaction for `tx`, then
    apply its cash impact. Shared by create_transaction_core (initial creation) and
    update_transaction_core (fee recreation on edit) — identical shape in both; only the
    calling loop's fee-amount/ticker tuple construction differs (Optional-vs-required fields)."""
    fee_tx = Transaction(
        portfolio_id=tx.portfolio_id,
        account_id=tx.account_id,
        date=tx.date,
        type="Frais",
        ticker=fee_ticker,
        currency="EUR",
        exchange_rate=1.0,
        quantity=-1,
        unit_price=fee_amount,
        unit_price_eur=fee_amount,
        total_amount=-fee_amount,
        total_amount_eur=-fee_amount,
        linked_transaction_id=tx.id,
    )
    db.add(fee_tx)
    await db.flush()
    prev_fee_balance = await _prev_balance_eur(db, fee_tx.account_id, fee_tx.portfolio_id, fee_tx.date, fee_tx.id)
    if prev_fee_balance is not None:
        fee_tx.balance_eur = _no_neg_zero(r2(prev_fee_balance - fee_amount))
        fee_tx.balance_currency = fee_tx.balance_eur
    await _update_account_cash_balance(db, tx.account_id, tx.portfolio_id, -fee_amount, fee_tx.type, fee_tx.ticker, fee_tx.operation)
    return fee_tx


async def create_transaction_core(body: TransactionCreate, db: AsyncSession) -> Transaction:
    """Everything create_transaction does up to (but not including) commit/refresh/snapshot
    trigger. Extracted so the bulk-import feature can call this once per row inside a single
    atomic DB transaction — calling the route function N times would commit each row
    individually, making an all-or-nothing rollback across the whole import impossible.
    """
    # Verify account ownership: the account must belong to the same portfolio
    acct_result = await db.execute(select(Broker).where(Broker.id == body.account_id))
    account = acct_result.scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=400, detail="Broker not found")
    pa_result = await db.execute(
        select(PortfolioAccount).where(
            PortfolioAccount.broker_id == account.id,
            PortfolioAccount.portfolio_id == body.portfolio_id,
        )
    )
    if pa_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=400,
            detail="Broker does not belong to the specified portfolio",
        )

    tx = Transaction(**body.model_dump(exclude={"courtage_eur", "ttf_eur", "additional_executions"}))
    db.add(tx)
    await db.flush()  # get tx.id before updating account and balance

    # Auto-calculate balance_eur (Contrevaleur solde EUR) when not provided.
    # Find the most recent transaction for this account that has a known balance,
    # then add the current transaction's amount on top. A free share Attribution
    # never gets a balance_eur/balance_currency — it never moved any cash, even
    # though total_amount_eur may carry a recorded fair-value cost basis for WACOP
    # (see _contributes_to_ledger). It stays None and displays "—" in the UI.
    if tx.balance_eur is None and _contributes_to_ledger(tx.operation):
        prev_balance = await _prev_balance_eur(db, tx.account_id, tx.portfolio_id, tx.date, tx.id)
        if prev_balance is not None:
            tx.balance_eur = _no_neg_zero(r2(prev_balance + tx.total_amount_eur))
            # For EUR transactions, balance_currency equals balance_eur
            if tx.currency == "EUR" and tx.balance_currency is None:
                tx.balance_currency = tx.balance_eur
            # For non-EUR transactions, compute balance_currency as a running sum in
            # the native currency. total_amount = quantity × unit_price in that currency.
            elif tx.balance_currency is None:
                prev_curr_balance = await _prev_balance_currency(
                    db, tx.account_id, tx.portfolio_id, tx.currency, tx.date, tx.id,
                )
                if prev_curr_balance is not None:
                    tx.balance_currency = _no_neg_zero(r2(prev_curr_balance + tx.total_amount))

    # Retroactive update: propagate this transaction's amount to all SUBSEQUENT
    # transactions for the same account that have a known balance_eur.
    # Use case: adding a missing transaction from the past (e.g. a fee entered
    # after the fact). The subsequent balance_eur values must shift by the same delta.
    if tx.total_amount_eur != 0 and _contributes_to_ledger(tx.operation):
        await _propagate_balance_eur_delta(db, tx.account_id, tx.portfolio_id, tx.date, tx.id, tx.total_amount_eur)
    # Retroactive update for non-EUR balance_currency: propagate to subsequent
    # transactions in the same currency on the same account.
    if tx.currency != "EUR" and tx.balance_currency is not None and tx.total_amount != 0 and _contributes_to_ledger(tx.operation):
        await db.execute(
            sa_update(Transaction)
            .where(
                Transaction.account_id == tx.account_id,
                Transaction.portfolio_id == tx.portfolio_id,
                Transaction.currency == tx.currency,
                Transaction.balance_currency.isnot(None),
                Transaction.id != tx.id,
                (Transaction.date > tx.date) |
                ((Transaction.date == tx.date) & (Transaction.id > tx.id)),
            )
            .values(balance_currency=sa_func.round(cast(Transaction.balance_currency + tx.total_amount, Numeric), 2))
        )

    # Any transaction affects the account cash balance (deposit, buy, sell, fee, dividend)
    await _update_account_cash_balance(db, tx.account_id, tx.portfolio_id, tx.total_amount_eur, tx.type, tx.ticker, tx.operation)

    # Auto-create fractional sibling executions
    for exec_item in body.additional_executions:
        rate = exec_item.exchange_rate
        sibling = Transaction(
            portfolio_id=tx.portfolio_id,
            account_id=tx.account_id,
            date=exec_item.date,
            type=tx.type,
            ticker=tx.ticker,
            operation=tx.operation,
            currency=tx.currency,
            exchange_rate=rate,
            quantity=exec_item.quantity,
            unit_price=exec_item.unit_price,
            unit_price_eur=exec_item.unit_price * rate,
            total_amount=exec_item.quantity * exec_item.unit_price,
            total_amount_eur=exec_item.quantity * exec_item.unit_price * rate,
            fractional_parent_id=tx.id,
        )
        db.add(sibling)
        await db.flush()
        # Calculate balance_eur for the sibling (same logic as main transaction).
        # A sibling of an Attribution parent never gets a balance_eur either (see
        # _contributes_to_ledger).
        if _contributes_to_ledger(sibling.operation):
            prev_sib_balance = await _prev_balance_eur(db, sibling.account_id, sibling.portfolio_id, sibling.date, sibling.id)
            if prev_sib_balance is not None:
                sibling.balance_eur = _no_neg_zero(r2(prev_sib_balance + sibling.total_amount_eur))
                if sibling.currency == "EUR":
                    sibling.balance_currency = sibling.balance_eur
                else:
                    prev_sib_curr_balance = await _prev_balance_currency(
                        db, sibling.account_id, sibling.portfolio_id, sibling.currency, sibling.date, sibling.id,
                    )
                    if prev_sib_curr_balance is not None:
                        sibling.balance_currency = _no_neg_zero(r2(prev_sib_curr_balance + sibling.total_amount))
        await _update_account_cash_balance(db, tx.account_id, tx.portfolio_id, sibling.total_amount_eur, sibling.type, sibling.ticker, sibling.operation)

    # Auto-create linked fee transactions (brokerage + TTF) for Actif buys/sells.
    # Dedicated FRAIS.* tickers (not the parent asset's ticker) so fee_type can be
    # derived uniformly from the product, matching historical pre-regression data.
    if body.type == "Actif":
        for fee_amount, fee_ticker in (
            (body.courtage_eur, "FRAIS.COURTAGE.EUR"),
            (body.ttf_eur, "FRAIS.TTF.EUR"),
        ):
            if fee_amount > 0:
                await _create_fee_transaction(db, tx, fee_amount, fee_ticker)

    return tx


async def update_transaction_core(tx: Transaction, body: TransactionUpdate, db: AsyncSession) -> Transaction:
    """Everything update_transaction does up to (but not including) commit/refresh/snapshot
    trigger — same extraction rationale as create_transaction_core, applied consistently so
    the router stays a thin wrapper for every mutating endpoint, not just create."""
    old_total_eur = tx.total_amount_eur
    old_date = tx.date

    updates = body.model_dump(exclude_unset=True)
    date_changed = "date" in updates and updates["date"] != old_date

    for field, value in updates.items():
        setattr(tx, field, value)

    # Recompute derived fields if price/qty/rate changed
    if any(f in updates for f in ("exchange_rate", "quantity", "unit_price")):
        tx.unit_price_eur = tx.unit_price * tx.exchange_rate
        tx.total_amount = tx.quantity * tx.unit_price
        tx.total_amount_eur = tx.total_amount * tx.exchange_rate

    if date_changed:
        # Flush the date change explicitly before bulk updates so the session
        # state is coherent and synchronize_session='evaluate' doesn't interfere.
        await db.flush()

        # Undo the old position: remove this tx's amount from all transactions that
        # were after it (date > old_date, or same old_date with higher id). Uses the
        # CURRENT operation (not an old/new split) — same rigor this file already
        # applies to tx_type/ticker changes; see _contributes_to_ledger.
        if old_total_eur != 0 and _contributes_to_ledger(tx.operation):
            await _propagate_balance_eur_delta(
                db, tx.account_id, tx.portfolio_id, old_date, tx.id, -old_total_eur,
                synchronize_session=False,
            )

        # Recalculate this tx's balance_eur at its new date position. A free share
        # Attribution never gets one (see _contributes_to_ledger) — always None.
        tx.balance_eur = None
        tx.balance_currency = None
        if _contributes_to_ledger(tx.operation):
            prev_balance = await _prev_balance_eur(db, tx.account_id, tx.portfolio_id, tx.date, tx.id)
            if prev_balance is not None:
                tx.balance_eur = _no_neg_zero(r2(prev_balance + tx.total_amount_eur))
                if tx.currency == "EUR":
                    tx.balance_currency = tx.balance_eur

        # Apply the new position: add this tx's amount to all transactions after it.
        # Propagate regardless of tx.balance_eur — downstream running balances must shift
        # even when the moved tx itself has no prior to derive its own balance from.
        if tx.total_amount_eur != 0 and _contributes_to_ledger(tx.operation):
            await _propagate_balance_eur_delta(
                db, tx.account_id, tx.portfolio_id, tx.date, tx.id, tx.total_amount_eur,
                synchronize_session=False,
            )

        # A date move can be combined with an amount change in the same edit (date
        # plus quantity/unit_price/exchange_rate all provided at once) — the cash
        # balance must reflect that amount delta too, exactly like the non-date-move
        # branch below does.
        cash_delta = tx.total_amount_eur - old_total_eur
        if cash_delta != 0:
            await _update_account_cash_balance(db, tx.account_id, tx.portfolio_id, cash_delta, tx.type, tx.ticker, tx.operation)
    else:
        # Auto-calculate balance_eur when still null (e.g. transaction created before this fix)
        if tx.balance_eur is None and _contributes_to_ledger(tx.operation):
            prev_balance = await _prev_balance_eur(db, tx.account_id, tx.portfolio_id, tx.date, tx.id)
            if prev_balance is not None:
                tx.balance_eur = _no_neg_zero(r2(prev_balance + tx.total_amount_eur))
                if tx.currency == "EUR" and tx.balance_currency is None:
                    tx.balance_currency = tx.balance_eur

        # Auto-compute balance_currency for non-EUR transactions when still null.
        # Handles existing transactions created before this feature was added.
        # Runs whether or not balance_eur was just auto-calculated above.
        if tx.currency != "EUR" and tx.balance_currency is None and tx.balance_eur is not None:
            prev_curr_balance = await _prev_balance_currency(
                db, tx.account_id, tx.portfolio_id, tx.currency, tx.date, tx.id,
            )
            if prev_curr_balance is not None:
                tx.balance_currency = _no_neg_zero(r2(prev_curr_balance + tx.total_amount))

        delta = tx.total_amount_eur - old_total_eur

        # A free share Attribution never touches any running balance or the account
        # cash balance (see _contributes_to_ledger) — skip the whole block, using
        # CURRENT operation (same rigor already applied to tx_type/ticker changes).
        if delta != 0 and _contributes_to_ledger(tx.operation):
            # Update balance_eur of this transaction itself
            if tx.balance_eur is not None:
                tx.balance_eur = _no_neg_zero(r2(tx.balance_eur + delta))
                if tx.currency == "EUR":
                    tx.balance_currency = tx.balance_eur

            # Retroactive update: propagate the delta to all SUBSEQUENT transactions
            await _propagate_balance_eur_delta(
                db, tx.account_id, tx.portfolio_id, tx.date, tx.id, delta,
                synchronize_session=False,
            )

            await _update_account_cash_balance(db, tx.account_id, tx.portfolio_id, delta, tx.type, tx.ticker, tx.operation)

    # Update linked fee transactions (brokerage + TTF) if new values are provided
    # Skip if transaction is a fractional sibling (it never owns fees)
    # or if it's a fractional parent with siblings (fees managed at order creation)
    has_siblings = (await db.execute(
        select(Transaction.id).where(Transaction.fractional_parent_id == tx.id).limit(1)
    )).scalar_one_or_none() is not None
    is_fractional = tx.fractional_parent_id is not None or has_siblings

    if (body.courtage_eur is not None or body.ttf_eur is not None) and not is_fractional:
        # Delete existing linked Frais and reverse their cash impact
        children_result = await db.execute(
            select(Transaction).where(Transaction.linked_transaction_id == tx.id)
        )
        for child in children_result.scalars().all():
            await _update_account_cash_balance(db, child.account_id, child.portfolio_id, -child.total_amount_eur, child.type, child.ticker, child.operation)
            await db.delete(child)
        # Recreate with new values. Dedicated FRAIS.* tickers (not the parent asset's
        # ticker) so fee_type can be derived uniformly from the product.
        for fee_amount, fee_ticker in (
            (body.courtage_eur or 0, "FRAIS.COURTAGE.EUR"),
            (body.ttf_eur or 0, "FRAIS.TTF.EUR"),
        ):
            if fee_amount > 0:
                # Same logic as auto-created fees on create_transaction (via
                # _create_fee_transaction) — otherwise it stays null and masks the
                # parent's balance in the UI (highest id per day/currency wins).
                await _create_fee_transaction(db, tx, fee_amount, fee_ticker)

    return tx


async def delete_transaction_core(tx: Transaction, db: AsyncSession) -> tuple[int, Date]:
    """Everything delete_transaction does up to (but not including) commit/snapshot trigger.
    Returns (portfolio_id, tx_date) for the caller's snapshot-recompute trigger call, since
    tx's own attributes become unsafe to rely on for that once it's been deleted."""
    portfolio_id, tx_date, account_id = tx.portfolio_id, tx.date, tx.account_id
    tx_type, tx_ticker, tx_operation = tx.type, tx.ticker, tx.operation

    # Delete fractional siblings first (they share the brokerage fee of the parent)
    siblings_result = await db.execute(
        select(Transaction).where(Transaction.fractional_parent_id == tx.id)
    )
    for sibling in siblings_result.scalars().all():
        await _update_account_cash_balance(db, sibling.account_id, sibling.portfolio_id, -sibling.total_amount_eur, sibling.type, sibling.ticker, sibling.operation)
        await db.delete(sibling)

    # Explicitly delete linked fee transactions (brokerage/TTF) so their cash balance is also reversed
    children_result = await db.execute(
        select(Transaction).where(Transaction.linked_transaction_id == tx.id)
    )
    for child in children_result.scalars().all():
        await _update_account_cash_balance(db, child.account_id, child.portfolio_id, -child.total_amount_eur, child.type, child.ticker, child.operation)
        await db.delete(child)

    delta = -tx.total_amount_eur  # reverting the parent transaction's cash impact
    await db.delete(tx)

    # Any deleted transaction restores the cash balance
    await _update_account_cash_balance(db, account_id, portfolio_id, delta, tx_type, tx_ticker, tx_operation)

    return portfolio_id, tx_date
