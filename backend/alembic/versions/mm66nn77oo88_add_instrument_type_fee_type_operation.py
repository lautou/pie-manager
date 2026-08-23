# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add instrument_type/fee_type to products, operation to transactions

Revision ID: mm66nn77oo88
Revises: ll55mm66nn77
Create Date: 2026-07-13

Robust product/transaction typology model:
- products.category simplified to exactly 'Actif' | 'Frais' (was also abused
  as a pool-theme label: Asie/Energie/Or/Obligations/Cash/Manuel/Revenu).
- products.instrument_type: ETF / SICAV-FCP / Action / Obligation /
  Or physique / Cash — new sub-classification for category='Actif'.
- products.fee_type: Courtage / Tenue de compte / Intérêts négatifs /
  Bourse / TTF / Impôts / Conversion — new sub-classification for category='Frais'.
- transactions.operation: Achat / Vente / Attribution — new sub-classification
  for type='Actif', backfilled from the existing quantity-sign convention
  (inverted for *EUR=X forex pairs, same as the WACOP convention).
- 9 historical auto-linked fee transactions (courtage/TTF created alongside
  a buy/sell) that reused their parent asset's ticker instead of a dedicated
  FRAIS.* ticker are retargeted, so fee_type is derivable uniformly. A new
  FRAIS.TTF.EUR product is created for this (distinct from the pre-existing,
  more generic FRAIS.TAXE.EUR/GBP).
"""
from alembic import op
import sqlalchemy as sa

revision = 'mm66nn77oo88'
down_revision = 'll55mm66nn77'
branch_labels = None
depends_on = None


# Original category values, keyed by ticker, for exact downgrade restoration.
_ORIGINAL_CATEGORY = {
    'AI.PA': 'Asie', 'DBX5.DE': 'Asie', 'DBX9.DE': 'Asie', 'FLXC.DE': 'Asie',
    'H411.DE': 'Asie', 'H4ZX.DE': 'Asie', 'MC.PA': 'Asie', 'SU.PA': 'Asie',
    'IS0D.DE': 'Energie', 'NUKL.DE': 'Energie', 'QDVF.DE': 'Energie',
    'STN.PA': 'Energie', 'TTE.PA': 'Energie',
    'GOLD-EUR.PA': 'Or', 'PPFB.DE': 'Or',
    'XJSE.DE': 'Obligations',
    'JPYEUR=X': 'Cash', 'LIQUIDITE.EURO': 'Cash',
    'OR.PHYSIQUE': 'Manuel',
}

_INSTRUMENT_TYPE_MAP = {
    'Action': ['AI.PA', 'MC.PA', 'SU.PA', 'TTE.PA'],
    'ETF': ['DBX5.DE', 'DBX9.DE', 'FLXC.DE', 'H411.DE', 'H4ZX.DE', 'IS0D.DE',
            'NUKL.DE', 'QDVF.DE', 'STN.PA', 'XJSE.DE', 'GOLD-EUR.PA', 'PPFB.DE'],
    'Or physique': ['OR.PHYSIQUE'],
    'Cash': ['LIQUIDITE.EURO', 'JPYEUR=X'],
    'SICAV/FCP': ['0P00000MQC.F', '0P00000ZFN.F', '0P0000IT7S.F', '3G80.MU', 'XU6G.MU'],
}

_FEE_TYPE_MAP = {
    'Courtage': ['FRAIS.COURTAGE.EUR', 'FRAIS.COURTAGE.JPY', 'FRAIS.COURTAGE.USD'],
    'Tenue de compte': ['FRAIS.COMPTE', 'FRAIS.DEPOT.EUR'],
    'Bourse': ['FRAIS.CONNECTION.EUR'],
    'Intérêts négatifs': ['FRAIS.INTNEG.JPY'],
    'Impôts': ['FRAIS.TAXE.EUR', 'FRAIS.TAXE.GBP'],
    'TTF': ['FRAIS.TTF.EUR'],
}


def upgrade() -> None:
    # ── 1. New columns ───────────────────────────────────────────────────────
    op.add_column('products', sa.Column('instrument_type', sa.String(30), nullable=True))
    op.add_column('products', sa.Column('fee_type', sa.String(30), nullable=True))
    op.add_column('transactions', sa.Column('operation', sa.String(20), nullable=True))
    op.create_check_constraint(
        'ck_transaction_operation',
        'transactions',
        "operation IN ('Achat', 'Vente', 'Attribution') OR operation IS NULL",
    )

    # ── 2. Dedicated TTF product (distinct from the generic FRAIS.TAXE.*) ────
    op.execute("""
        INSERT INTO products (ticker, name, category, currency, fee_type)
        VALUES ('FRAIS.TTF.EUR', 'Taxe sur les Transactions Financières', 'Frais', 'EUR', 'TTF')
        ON CONFLICT (ticker) DO NOTHING
    """)

    # ── 3. Backfill instrument_type / fee_type ──────────────────────────────
    for itype, tickers in _INSTRUMENT_TYPE_MAP.items():
        in_list = ','.join(f"'{t}'" for t in tickers)
        op.execute(f"UPDATE products SET instrument_type = '{itype}' WHERE ticker IN ({in_list})")
    for ftype, tickers in _FEE_TYPE_MAP.items():
        in_list = ','.join(f"'{t}'" for t in tickers)
        op.execute(f"UPDATE products SET fee_type = '{ftype}' WHERE ticker IN ({in_list})")

    # ── 4. Simplify category to Actif | Frais ───────────────────────────────
    op.execute("UPDATE products SET category = 'Actif' WHERE category != 'Frais'")

    # ── 5. Retarget the historical auto-linked fees that reused their
    #      parent's ticker onto dedicated FRAIS.* tickers, so fee_type can be
    #      derived uniformly. Verified against production data: exactly 9
    #      rows, all EUR, across 8 parent transactions (7 with a single
    #      linked fee = courtage only; 1 with two = courtage then TTF, in
    #      that order — courtage is always created before TTF in
    #      create_transaction/update_transaction's fee-creation loop, so
    #      ordering by id within a linked_transaction_id group is reliable).
    #
    #      All 3 target sets below are computed from a single snapshot of the
    #      ORIGINAL (pre-retarget) rows into a temp table before any UPDATE
    #      runs. Running these as 3 sequential UPDATEs against the live table
    #      instead would corrupt the result: the 2nd UPDATE already renames
    #      one row of a 2-fee group off of "ticker NOT LIKE 'FRAIS.%'", so by
    #      the time the 3rd UPDATE's GROUP BY ... HAVING COUNT(*) = 2 runs,
    #      that group only has 1 matching row left and is silently dropped —
    #      leaving the TTF leg un-retargeted. Verified via synthetic data.
    op.execute("""
        CREATE TEMP TABLE _fee_retarget AS
        SELECT id, 'FRAIS.COURTAGE.EUR' AS new_ticker
        FROM transactions t
        WHERE t.type = 'Frais' AND t.linked_transaction_id IS NOT NULL
          AND t.ticker NOT LIKE 'FRAIS.%%'
          AND (SELECT COUNT(*) FROM transactions c
               WHERE c.linked_transaction_id = t.linked_transaction_id) = 1
        UNION ALL
        SELECT first_id, 'FRAIS.COURTAGE.EUR' FROM (
            SELECT MIN(id) AS first_id
            FROM transactions
            WHERE type = 'Frais' AND linked_transaction_id IS NOT NULL AND ticker NOT LIKE 'FRAIS.%%'
            GROUP BY linked_transaction_id HAVING COUNT(*) = 2
        ) g1
        UNION ALL
        SELECT second_id, 'FRAIS.TTF.EUR' FROM (
            SELECT MAX(id) AS second_id
            FROM transactions
            WHERE type = 'Frais' AND linked_transaction_id IS NOT NULL AND ticker NOT LIKE 'FRAIS.%%'
            GROUP BY linked_transaction_id HAVING COUNT(*) = 2
        ) g2
    """)
    op.execute("""
        UPDATE transactions t
        SET ticker = r.new_ticker
        FROM _fee_retarget r
        WHERE t.id = r.id AND t.currency = 'EUR'
    """)
    op.execute("DROP TABLE _fee_retarget")

    # ── 6. Backfill transactions.operation for existing 'Actif' rows ────────
    # Same sign convention as pv_service.py's WACOP logic: instrument_type='Cash'
    # products (LIQUIDITE.*, JPYEUR=X, ...) are inverted relative to regular
    # assets — quantity > 0 means acquiring/depositing for Cash, but selling
    # for everything else.
    op.execute("""
        UPDATE transactions t
        SET operation = CASE
            WHEN p.instrument_type = 'Cash' AND t.quantity > 0 THEN 'Achat'
            WHEN p.instrument_type = 'Cash' AND t.quantity < 0 THEN 'Vente'
            WHEN (p.instrument_type IS NULL OR p.instrument_type != 'Cash') AND t.quantity < 0 THEN 'Achat'
            WHEN (p.instrument_type IS NULL OR p.instrument_type != 'Cash') AND t.quantity > 0 THEN 'Vente'
            ELSE NULL
        END
        FROM products p
        WHERE t.ticker = p.ticker AND t.type = 'Actif'
    """)


def downgrade() -> None:
    op.execute("UPDATE transactions SET operation = NULL")
    op.drop_constraint('ck_transaction_operation', 'transactions', type_='check')
    op.drop_column('transactions', 'operation')

    # Restore the 9 retargeted fee tickers to their original parent ticker.
    op.execute("""
        UPDATE transactions t
        SET ticker = (SELECT p.ticker FROM transactions p WHERE p.id = t.linked_transaction_id)
        WHERE t.type = 'Frais' AND t.linked_transaction_id IS NOT NULL
          AND t.ticker IN ('FRAIS.COURTAGE.EUR', 'FRAIS.TTF.EUR')
          AND t.id IN (1269, 1272, 1274, 1276, 1278, 1281, 1297, 1306, 1307)
    """)
    op.execute("DELETE FROM products WHERE ticker = 'FRAIS.TTF.EUR'")

    # Restore original category values (best-effort, exact for known tickers;
    # anything else falls back to 'Actif' since it was never anything else).
    for ticker, category in _ORIGINAL_CATEGORY.items():
        op.execute(f"UPDATE products SET category = '{category}' WHERE ticker = '{ticker}'")

    op.drop_column('products', 'fee_type')
    op.drop_column('products', 'instrument_type')
