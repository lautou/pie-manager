from datetime import date

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("type IN ('Actif', 'Frais', 'Revenu')", name="ck_transaction_type"),
        # NOTE: transaction.portfolio_id == account.portfolio_id consistency is enforced
        # at the application layer (transactions POST, HTTP 400), not at DB level.
        # A composite FK would require accounts(id, portfolio_id) to have a unique
        # constraint, which would be a larger schema change.
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("brokers.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Type: "Actif" (buy/sell/cash deposit), "Frais" (fees), "Revenu" (dividends)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    ticker: Mapped[str] = mapped_column(ForeignKey("products.ticker"), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)

    # exchange_rate: 1 unit of currency = exchange_rate EUR
    exchange_rate: Mapped[float] = mapped_column(Float, default=1.0)

    # Positive = buy/deposit, negative = sell/withdrawal
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price_eur: Mapped[float] = mapped_column(Float, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    total_amount_eur: Mapped[float] = mapped_column(Float, nullable=False)

    # Running balance on the account in native currency and EUR
    balance_currency: Mapped[float | None] = mapped_column(Float, nullable=True)
    balance_eur: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Optional link to a paired transaction (e.g. EUR withdrawal that funded
    # a foreign-currency asset purchase, or the two legs of a forex swap).
    linked_transaction_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Fractional order: points to the first execution of this order.
    # Null on the first (parent) execution; set on all subsequent executions.
    fractional_parent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    broker: Mapped["Broker"] = relationship(back_populates="transactions")
    product: Mapped["Product"] = relationship()
