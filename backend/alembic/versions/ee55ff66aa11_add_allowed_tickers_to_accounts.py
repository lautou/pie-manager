"""add allowed_tickers to accounts

Revision ID: ee55ff66aa11
Revises: dd44ee55ff66
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'ee55ff66aa11'
down_revision = 'dd44ee55ff66'
branch_labels = None
depends_on = None

_BD_TICKERS = [
    "AI.PA", "TTE.PA", "SU.PA", "MC.PA",
    "LIQUIDITE.EURO",
    "FRAIS.COURTAGE.EUR", "FRAIS.TAXE.EUR", "FRAIS.COMPTE",
]

_DEGIRO_TICKERS = [
    "DBX5.DE", "DBX9.DE", "FLXC.DE", "H411.DE", "H4ZX.DE",
    "IS0D.DE", "NUKL.DE", "QDVF.DE", "STN.PA", "GOLD-EUR.PA", "PPFB.DE",
    "LIQUIDITE.EURO",
    "FRAIS.COURTAGE.EUR", "FRAIS.TAXE.EUR", "FRAIS.COMPTE",
]

_IBKR_TICKERS = [
    "XJSE.DE", "LIQUIDITE.EURO", "JPYEUR=X",
    "FRAIS.COURTAGE.EUR", "FRAIS.COURTAGE.JPY", "FRAIS.COURTAGE.USD",
    "FRAIS.INTNEG.JPY", "FRAIS.TAXE.EUR", "FRAIS.TAXE.GBP", "FRAIS.COMPTE",
]

_REVOLUT_TICKERS = [
    "JPYEUR=X", "LIQUIDITE.EURO",
    "FRAIS.COURTAGE.EUR", "FRAIS.COMPTE",
]

_BNP_TICKERS = [
    "0P00000MQC.F", "0P00000ZFN.F", "0P0000IT7S.F", "3G80.MU", "XU6G.MU",
    "LIQUIDITE.EURO", "FRAIS.COMPTE", "FRAIS.TAXE.EUR",
]

_AUCOFFRE_TICKERS = [
    "OR.PHYSIQUE",
    "FRAIS.COURTAGE.EUR", "FRAIS.TAXE.EUR", "FRAIS.COMPTE",
]


def _sql_json(tickers: list) -> str:
    import json
    return f"'{json.dumps(tickers)}'::jsonb"


def upgrade() -> None:
    op.add_column('accounts', sa.Column('allowed_tickers', JSONB, nullable=True))

    op.execute(f"UPDATE accounts SET allowed_tickers = {_sql_json(_BD_TICKERS)} WHERE LOWER(name) LIKE '%bourse%'")
    op.execute(f"UPDATE accounts SET allowed_tickers = {_sql_json(_DEGIRO_TICKERS)} WHERE LOWER(name) LIKE '%degiro%'")
    op.execute(f"UPDATE accounts SET allowed_tickers = {_sql_json(_IBKR_TICKERS)} WHERE LOWER(name) LIKE '%ibkr%' OR LOWER(name) LIKE '%interactive%'")
    op.execute(f"UPDATE accounts SET allowed_tickers = {_sql_json(_REVOLUT_TICKERS)} WHERE LOWER(name) LIKE '%revolut%'")
    op.execute(f"UPDATE accounts SET allowed_tickers = {_sql_json(_BNP_TICKERS)} WHERE LOWER(name) LIKE '%bnp%'")
    op.execute(f"UPDATE accounts SET allowed_tickers = {_sql_json(_AUCOFFRE_TICKERS)} WHERE LOWER(name) LIKE '%coffre%'")


def downgrade() -> None:
    op.drop_column('accounts', 'allowed_tickers')
