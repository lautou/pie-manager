from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func, cast, Numeric
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from typing import Optional
from datetime import date as Date

from app.core.database import get_db
from app.models import Transaction, Broker, PortfolioAccount


def _no_neg_zero(v: float) -> float:
    """Normalize IEEE 754 negative zero (-0.0) to positive zero."""
    return v + 0.0

router = APIRouter(tags=["transactions"])


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
    # When provided, linked fee transactions (brokerage + TTF) are replaced with new values
    courtage_eur: Optional[float] = None
    ttf_eur: Optional[float] = None



class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    portfolio_id: int
    account_id: int
    date: Date
    type: str
    ticker: str
    currency: str
    exchange_rate: float
    quantity: float
    unit_price: float
    unit_price_eur: float
    total_amount: float
    total_amount_eur: float
    balance_currency: Optional[float]
    balance_eur: Optional[float]
    fractional_parent_id: Optional[int]
    linked_transaction_id: Optional[int]

    @field_validator("balance_eur", "balance_currency", mode="before")
    @classmethod
    def _normalize_zero(cls, v: object) -> object:
        # Bulk DB updates (balance ± delta) can produce IEEE 754 −0.0 when the
        # result cancels exactly.  −0.0 == 0.0 in Python, so the assignment
        # below converts negative zero to positive zero without touching other values.
        if isinstance(v, float) and v == 0.0:
            return 0.0
        return v


def _trigger_snapshot_recompute(portfolio_id: int, from_date: Date):
    from app.tasks.snapshots import compute_daily_snapshots_all_users
    compute_daily_snapshots_all_users.delay(from_date.isoformat())


async def _update_account_cash_balance(
    db: AsyncSession, account_id: int, portfolio_id: int, delta: float
) -> None:
    """Update portfolio_accounts.cash_balance_eur by adding delta (positive or negative).

    cash_balance_eur is now per (broker, portfolio) pair on the portfolio_accounts join table.
    Any transaction affects the account cash balance (not just LIQUIDITE.EURO):
    - Buying assets: negative total_amount_eur → cash decreases
    - Selling assets, dividends, deposits: positive → cash increases
    - Fees: negative → cash decreases
    """
    result = await db.execute(
        select(PortfolioAccount).where(
            PortfolioAccount.broker_id == account_id,
            PortfolioAccount.portfolio_id == portfolio_id,
        )
    )
    pa = result.scalar_one_or_none()
    if pa is not None:
        pa.cash_balance_eur = round((pa.cash_balance_eur or 0.0) + delta, 2)


@router.get("/", response_model=list[TransactionOut])
async def list_transactions(
    portfolio_id: int = Query(...),
    account_id: Optional[int] = Query(None),
    ticker: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    date_from: Optional[Date] = Query(None),
    date_to: Optional[Date] = Query(None),
    skip: int = Query(0),
    limit: int = Query(5000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Transaction).where(Transaction.portfolio_id == portfolio_id)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if ticker:
        stmt = stmt.where(Transaction.ticker.ilike(f"%{ticker}%"))
    if currency:
        stmt = stmt.where(Transaction.currency.ilike(f"%{currency}%"))
    if date_from:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to:
        stmt = stmt.where(Transaction.date <= date_to)
    stmt = stmt.order_by(
        Transaction.date.desc(),
        Transaction.id.desc()
    ).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/", response_model=TransactionOut, status_code=201)
async def create_transaction(body: TransactionCreate, db: AsyncSession = Depends(get_db)):
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
    # then add the current transaction's amount on top.
    if tx.balance_eur is None:
        prev_result = await db.execute(
            select(Transaction.balance_eur)
            .where(
                Transaction.account_id == tx.account_id,
                Transaction.balance_eur.isnot(None),
                Transaction.id != tx.id,
                # Only look at transactions BEFORE this date/id (not future ones)
                (Transaction.date < tx.date) |
                ((Transaction.date == tx.date) & (Transaction.id < tx.id)),
            )
            .order_by(Transaction.date.desc(), Transaction.id.desc())
            .limit(1)
        )
        prev_balance = prev_result.scalar_one_or_none()
        if prev_balance is not None:
            tx.balance_eur = _no_neg_zero(round(float(prev_balance) + tx.total_amount_eur, 2))
            # For EUR transactions, balance_currency equals balance_eur
            if tx.currency == "EUR" and tx.balance_currency is None:
                tx.balance_currency = tx.balance_eur

    # Retroactive update: propagate this transaction's amount to all SUBSEQUENT
    # transactions for the same account that have a known balance_eur.
    # Use case: adding a missing transaction from the past (e.g. a fee entered
    # after the fact). The subsequent balance_eur values must shift by the same delta.
    if tx.total_amount_eur != 0:
        from sqlalchemy import update as sa_update
        await db.execute(
            sa_update(Transaction)
            .where(
                Transaction.account_id == tx.account_id,
                Transaction.balance_eur.isnot(None),
                Transaction.id != tx.id,
                (Transaction.date > tx.date) |
                ((Transaction.date == tx.date) & (Transaction.id > tx.id)),
            )
            .values(balance_eur=sa_func.round(cast(Transaction.balance_eur + tx.total_amount_eur, Numeric), 2))
        )

    # Any transaction affects the account cash balance (deposit, buy, sell, fee, dividend)
    await _update_account_cash_balance(db, tx.account_id, tx.portfolio_id, tx.total_amount_eur)

    # Auto-create fractional sibling executions
    for exec_item in body.additional_executions:
        rate = exec_item.exchange_rate
        sibling = Transaction(
            portfolio_id=tx.portfolio_id,
            account_id=tx.account_id,
            date=exec_item.date,
            type=tx.type,
            ticker=tx.ticker,
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
        # Calculate balance_eur for the sibling (same logic as main transaction)
        prev_sib = await db.execute(
            select(Transaction.balance_eur)
            .where(
                Transaction.account_id == sibling.account_id,
                Transaction.balance_eur.isnot(None),
                Transaction.id != sibling.id,
                (Transaction.date < sibling.date) |
                ((Transaction.date == sibling.date) & (Transaction.id < sibling.id)),
            )
            .order_by(Transaction.date.desc(), Transaction.id.desc())
            .limit(1)
        )
        prev_sib_balance = prev_sib.scalar_one_or_none()
        if prev_sib_balance is not None:
            sibling.balance_eur = _no_neg_zero(round(float(prev_sib_balance) + sibling.total_amount_eur, 2))
            if sibling.currency == "EUR":
                sibling.balance_currency = sibling.balance_eur
        await _update_account_cash_balance(db, tx.account_id, tx.portfolio_id, sibling.total_amount_eur)

    # Auto-create linked fee transactions (brokerage + TTF) for Actif buys/sells
    if body.type == "Actif":
        for fee_amount in (body.courtage_eur, body.ttf_eur):
            if fee_amount > 0:
                fee_tx = Transaction(
                    portfolio_id=tx.portfolio_id,
                    account_id=tx.account_id,
                    date=tx.date,
                    type="Frais",
                    ticker=tx.ticker,
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
                # Calculate balance_eur for the auto-created fee transaction
                prev_fee_result = await db.execute(
                    select(Transaction.balance_eur)
                    .where(
                        Transaction.account_id == fee_tx.account_id,
                        Transaction.balance_eur.isnot(None),
                        Transaction.id != fee_tx.id,
                        (Transaction.date < fee_tx.date) |
                        ((Transaction.date == fee_tx.date) & (Transaction.id < fee_tx.id)),
                    )
                    .order_by(Transaction.date.desc(), Transaction.id.desc())
                    .limit(1)
                )
                prev_fee_balance = prev_fee_result.scalar_one_or_none()
                if prev_fee_balance is not None:
                    fee_tx.balance_eur = _no_neg_zero(round(float(prev_fee_balance) - fee_amount, 2))
                    fee_tx.balance_currency = fee_tx.balance_eur
                await _update_account_cash_balance(db, tx.account_id, tx.portfolio_id, -fee_amount)

    await db.commit()
    await db.refresh(tx)
    _trigger_snapshot_recompute(tx.portfolio_id, tx.date)
    return tx


@router.put("/{transaction_id}", response_model=TransactionOut)
async def update_transaction(
    transaction_id: int,
    body: TransactionUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Transaction).where(Transaction.id == transaction_id))
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

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

    from sqlalchemy import update as sa_update

    if date_changed:
        # Flush the date change explicitly before bulk updates so the session
        # state is coherent and synchronize_session='evaluate' doesn't interfere.
        await db.flush()

        # Undo the old position: remove this tx's amount from all transactions that
        # were after it (date > old_date, or same old_date with higher id).
        if old_total_eur != 0:
            await db.execute(
                sa_update(Transaction)
                .where(
                    Transaction.account_id == tx.account_id,
                    Transaction.balance_eur.isnot(None),
                    Transaction.id != tx.id,
                    (Transaction.date > old_date) |
                    ((Transaction.date == old_date) & (Transaction.id > tx.id)),
                )
                .values(balance_eur=sa_func.round(cast(Transaction.balance_eur - old_total_eur, Numeric), 2))
                .execution_options(synchronize_session=False)
            )

        # Recalculate this tx's balance_eur at its new date position
        prev_result = await db.execute(
            select(Transaction.balance_eur)
            .where(
                Transaction.account_id == tx.account_id,
                Transaction.balance_eur.isnot(None),
                Transaction.id != tx.id,
                (Transaction.date < tx.date) |
                ((Transaction.date == tx.date) & (Transaction.id < tx.id)),
            )
            .order_by(Transaction.date.desc(), Transaction.id.desc())
            .limit(1)
        )
        prev_balance = prev_result.scalar_one_or_none()
        if prev_balance is not None:
            tx.balance_eur = _no_neg_zero(round(float(prev_balance) + tx.total_amount_eur, 2))
            if tx.currency == "EUR":
                tx.balance_currency = tx.balance_eur
        else:
            tx.balance_eur = None
            tx.balance_currency = None

        # Apply the new position: add this tx's amount to all transactions after it.
        # Propagate regardless of tx.balance_eur — downstream running balances must shift
        # even when the moved tx itself has no prior to derive its own balance from.
        if tx.total_amount_eur != 0:
            await db.execute(
                sa_update(Transaction)
                .where(
                    Transaction.account_id == tx.account_id,
                    Transaction.balance_eur.isnot(None),
                    Transaction.id != tx.id,
                    (Transaction.date > tx.date) |
                    ((Transaction.date == tx.date) & (Transaction.id > tx.id)),
                )
                .values(balance_eur=sa_func.round(cast(Transaction.balance_eur + tx.total_amount_eur, Numeric), 2))
                .execution_options(synchronize_session=False)
            )
    else:
        # Auto-calculate balance_eur when still null (e.g. transaction created before this fix)
        if tx.balance_eur is None:
            prev_result = await db.execute(
                select(Transaction.balance_eur)
                .where(
                    Transaction.account_id == tx.account_id,
                    Transaction.balance_eur.isnot(None),
                    Transaction.id != tx.id,
                    (Transaction.date < tx.date) |
                    ((Transaction.date == tx.date) & (Transaction.id < tx.id)),
                )
                .order_by(Transaction.date.desc(), Transaction.id.desc())
                .limit(1)
            )
            prev_balance = prev_result.scalar_one_or_none()
            if prev_balance is not None:
                tx.balance_eur = _no_neg_zero(round(float(prev_balance) + tx.total_amount_eur, 2))
                if tx.currency == "EUR" and tx.balance_currency is None:
                    tx.balance_currency = tx.balance_eur

        delta = tx.total_amount_eur - old_total_eur

        if delta != 0:
            # Update balance_eur of this transaction itself
            if tx.balance_eur is not None:
                tx.balance_eur = _no_neg_zero(round(tx.balance_eur + delta, 2))
                if tx.currency == "EUR":
                    tx.balance_currency = tx.balance_eur

            # Retroactive update: propagate the delta to all SUBSEQUENT transactions
            await db.execute(
                sa_update(Transaction)
                .where(
                    Transaction.account_id == tx.account_id,
                    Transaction.balance_eur.isnot(None),
                    (Transaction.date > tx.date) |
                    ((Transaction.date == tx.date) & (Transaction.id > tx.id)),
                )
                .values(balance_eur=sa_func.round(cast(Transaction.balance_eur + delta, Numeric), 2))
                .execution_options(synchronize_session=False)
            )

            await _update_account_cash_balance(db, tx.account_id, tx.portfolio_id, delta)

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
            await _update_account_cash_balance(db, child.account_id, child.portfolio_id, -child.total_amount_eur)
            await db.delete(child)
        # Recreate with new values
        for fee_amount in (body.courtage_eur or 0, body.ttf_eur or 0):
            if fee_amount > 0:
                fee_tx = Transaction(
                    portfolio_id=tx.portfolio_id,
                    account_id=tx.account_id,
                    date=tx.date,
                    type="Frais",
                    ticker=tx.ticker,
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
                await _update_account_cash_balance(db, tx.account_id, tx.portfolio_id, -fee_amount)

    await db.commit()
    await db.refresh(tx)
    _trigger_snapshot_recompute(tx.portfolio_id, tx.date)
    return tx


@router.delete("/{transaction_id}", status_code=204)
async def delete_transaction(transaction_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Transaction).where(Transaction.id == transaction_id))
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    portfolio_id, tx_date, account_id = tx.portfolio_id, tx.date, tx.account_id

    # Delete fractional siblings first (they share the brokerage fee of the parent)
    siblings_result = await db.execute(
        select(Transaction).where(Transaction.fractional_parent_id == transaction_id)
    )
    for sibling in siblings_result.scalars().all():
        await _update_account_cash_balance(db, sibling.account_id, sibling.portfolio_id, -sibling.total_amount_eur)
        await db.delete(sibling)

    # Explicitly delete linked fee transactions (brokerage/TTF) so their cash balance is also reversed
    children_result = await db.execute(
        select(Transaction).where(Transaction.linked_transaction_id == transaction_id)
    )
    for child in children_result.scalars().all():
        await _update_account_cash_balance(db, child.account_id, child.portfolio_id, -child.total_amount_eur)
        await db.delete(child)

    delta = -tx.total_amount_eur  # reverting the parent transaction's cash impact
    await db.delete(tx)

    # Any deleted transaction restores the cash balance
    await _update_account_cash_balance(db, account_id, portfolio_id, delta)

    await db.commit()
    _trigger_snapshot_recompute(portfolio_id, tx_date)
