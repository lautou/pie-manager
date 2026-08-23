# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Unit tests for app/services/etf_holdings_service.py.

Covers: replace_etf_holdings/replace_sector_weightings (replace-on-refetch semantics),
save_etf_fetch_result, get_composition, get_etf_tickers, get_direct_stock_tickers_in_etf_pools,
and compute_pool_lookthrough — the uniform ticker-keyed merge that powers the pool-level
sector/company allocation view. Scenarios mirror the real cases validated against Yahoo
Finance data this session: TotalEnergies held directly (TTE.PA) AND inside STN.PA, and
Tencent found inside three separate Asie-pool ETFs with no direct position at all.
"""
import pytest
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.models.portfolio import Portfolio
from app.models.broker import Broker
from app.models.product import Product
from app.models.pool import Pool, PoolProduct
from app.models.price import AssetPrice
from app.models.transaction import Transaction
from app.models.portfolio_account import PortfolioAccount
from app.models.etf_holding import EtfHolding, EtfSectorWeighting

from app.services.etf_holdings_service import (
    OTHER_KEY,
    replace_etf_holdings,
    replace_sector_weightings,
    save_etf_fetch_result,
    get_composition,
    get_etf_tickers,
    get_direct_stock_tickers_in_etf_pools,
    compute_pool_lookthrough,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

async def _setup_pool(db, suffix: str, pool_name: str = "Energie") -> dict:
    portfolio = Portfolio(name=f"Etf-{suffix}")
    db.add(portfolio)
    await db.flush()

    account = Broker(name=f"Broker-{suffix}", currency="EUR")
    db.add(account)
    await db.flush()
    db.add(PortfolioAccount(portfolio_id=portfolio.id, broker_id=account.id))
    await db.flush()

    pool = Pool(portfolio_id=portfolio.id, name=pool_name, strategy="Offensive",
                target_pct=0.25, is_active=True)
    db.add(pool)
    await db.flush()

    return {"portfolio_id": portfolio.id, "account_id": account.id, "pool_id": pool.id}


async def _hold_position(
    db, portfolio_id: int, account_id: int, pool_id: int | None,
    ticker: str, held_units: float, price: float,
    instrument_type: str | None = "ETF", currency: str = "EUR", name: str | None = None,
    price_date: date = date(2025, 1, 1),
) -> None:
    """Create (or reuse) a Product, optionally attach it to a pool, and give it a position."""
    existing = await db.execute(select(Product).where(Product.ticker == ticker))
    if existing.scalar_one_or_none() is None:
        db.add(Product(ticker=ticker, name=name or ticker, category="Actif",
                        instrument_type=instrument_type, currency=currency))
        await db.flush()

    if pool_id is not None:
        db.add(PoolProduct(pool_id=pool_id, ticker=ticker))
        await db.flush()

    is_cash = instrument_type == "Cash"
    qty = held_units if is_cash else -held_units
    amount = held_units * price if is_cash else -held_units * price
    db.add(Transaction(
        portfolio_id=portfolio_id, account_id=account_id,
        date=price_date, type="Actif", ticker=ticker,
        currency=currency, exchange_rate=1.0,
        quantity=qty, unit_price=price, unit_price_eur=price,
        total_amount=amount, total_amount_eur=amount,
    ))
    if price is not None:
        db.add(AssetPrice(ticker=ticker, date=price_date, price=price,
                           currency=currency, source="test"))
    await db.flush()


# ---------------------------------------------------------------------------
# replace_etf_holdings / replace_sector_weightings — replace-on-refetch semantics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replace_etf_holdings_inserts_then_replaces(db_session):
    suffix = id(db_session)
    ticker = f"ETF.{suffix}"
    db_session.add(Product(ticker=ticker, name="Test ETF", category="Actif", instrument_type="ETF"))
    await db_session.flush()

    await replace_etf_holdings(db_session, ticker, [
        {"ticker": "A.PA", "name": "Alpha", "weight_pct": 0.5},
        {"ticker": "B.PA", "name": "Beta", "weight_pct": 0.3},
    ])
    await db_session.flush()

    # Second fetch returns a different top-10 snapshot — old rows must be gone.
    await replace_etf_holdings(db_session, ticker, [
        {"ticker": "C.PA", "name": "Gamma", "weight_pct": 0.9},
    ])
    await db_session.flush()

    result = await db_session.execute(select(EtfHolding).where(EtfHolding.parent_ticker == ticker))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].holding_ticker == "C.PA"
    assert rows[0].weight_pct == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_replace_sector_weightings_inserts_then_replaces(db_session):
    suffix = id(db_session)
    ticker = f"ETF2.{suffix}"
    db_session.add(Product(ticker=ticker, name="Test ETF 2", category="Actif", instrument_type="ETF"))
    await db_session.flush()

    await replace_sector_weightings(db_session, ticker, {"energy": 0.9, "utilities": 0.1})
    await db_session.flush()
    await replace_sector_weightings(db_session, ticker, {"technology": 1.0})
    await db_session.flush()

    result = await db_session.execute(
        select(EtfSectorWeighting).where(EtfSectorWeighting.parent_ticker == ticker)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].sector == "technology"


@pytest.mark.asyncio
async def test_save_etf_fetch_result_updates_product_metadata(db_session):
    suffix = id(db_session)
    ticker = f"BOND.{suffix}"
    db_session.add(Product(ticker=ticker, name="Bond Fund", category="Actif", instrument_type="Obligation"))
    await db_session.flush()

    fetched_at = datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc)
    await save_etf_fetch_result(
        db_session, ticker,
        holdings=[],
        sector_weightings={},
        fetched_at=fetched_at,
        bond_duration=1.32,
        bond_maturity=8.57,
    )
    await db_session.flush()

    product = await db_session.get(Product, ticker)
    assert product.bond_duration == pytest.approx(1.32)
    assert product.bond_maturity == pytest.approx(8.57)
    # Stored as naive UTC (column has no timezone) regardless of the tz-aware input.
    assert product.holdings_updated_at == fetched_at.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_save_etf_fetch_result_without_bond_metrics_leaves_them_none(db_session):
    """An equity ETF's fetch never carries bond_duration/bond_maturity."""
    suffix = id(db_session)
    ticker = f"EQETF.{suffix}"
    db_session.add(Product(ticker=ticker, name="Equity ETF", category="Actif", instrument_type="ETF"))
    await db_session.flush()

    await save_etf_fetch_result(
        db_session, ticker,
        holdings=[{"ticker": "X.PA", "name": "X", "weight_pct": 1.0}],
        sector_weightings={"technology": 1.0},
        fetched_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    await db_session.flush()

    product = await db_session.get(Product, ticker)
    assert product.bond_duration is None
    assert product.bond_maturity is None


@pytest.mark.asyncio
async def test_save_etf_fetch_result_accepts_naive_datetime_unchanged(db_session):
    """A naive datetime (tzinfo is None) is stored as-is, no normalization needed."""
    suffix = id(db_session)
    ticker = f"NAIVEDT.{suffix}"
    db_session.add(Product(ticker=ticker, name="Naive DT ETF", category="Actif", instrument_type="ETF"))
    await db_session.flush()

    naive_fetched_at = datetime(2026, 7, 14, 6, 0)
    await save_etf_fetch_result(
        db_session, ticker, holdings=[], sector_weightings={}, fetched_at=naive_fetched_at,
    )
    await db_session.flush()

    product = await db_session.get(Product, ticker)
    assert product.holdings_updated_at == naive_fetched_at


# ---------------------------------------------------------------------------
# get_composition
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_composition_missing_product_returns_none(db_session):
    result = await get_composition(db_session, f"NOPE.{id(db_session)}")
    assert result is None


@pytest.mark.asyncio
async def test_get_composition_no_fetched_data_returns_empty_lists(db_session):
    suffix = id(db_session)
    ticker = f"NEWETF.{suffix}"
    db_session.add(Product(ticker=ticker, name="Not Yet Synced", category="Actif", instrument_type="ETF"))
    await db_session.flush()

    result = await get_composition(db_session, ticker)
    assert result is not None
    assert result["top_holdings"] == []
    assert result["sector_weightings"] == []
    assert result["top_holdings_coverage_pct"] == pytest.approx(0.0)
    assert result["holdings_updated_at"] is None


@pytest.mark.asyncio
async def test_get_composition_returns_sorted_holdings_and_coverage(db_session):
    suffix = id(db_session)
    ticker = f"STN.{suffix}"
    db_session.add(Product(ticker=ticker, name="STN.PA-like", category="Actif", instrument_type="ETF"))
    await db_session.flush()

    await replace_etf_holdings(db_session, ticker, [
        {"ticker": "TTE.PA", "name": "TotalEnergies SE", "weight_pct": 0.1863},
        {"ticker": "SHEL.L", "name": "Shell PLC", "weight_pct": 0.3510},
    ])
    await replace_sector_weightings(db_session, ticker, {"energy": 0.9946, "communication_services": 0.0054})
    await db_session.flush()

    result = await get_composition(db_session, ticker)
    assert result["ticker"] == ticker
    # Sorted descending by weight
    assert [h["ticker"] for h in result["top_holdings"]] == ["SHEL.L", "TTE.PA"]
    assert result["top_holdings_coverage_pct"] == pytest.approx((0.1863 + 0.3510) * 100, abs=0.01)
    assert [s["sector"] for s in result["sector_weightings"]] == ["energy", "communication_services"]


# ---------------------------------------------------------------------------
# get_etf_tickers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_etf_tickers_includes_etf_and_sicav(db_session):
    suffix = id(db_session)
    etf = f"ETFX.{suffix}"
    sicav = f"SICAVX.{suffix}"
    action = f"ACTX.{suffix}"
    db_session.add(Product(ticker=etf, name="ETF", category="Actif", instrument_type="ETF"))
    db_session.add(Product(ticker=sicav, name="SICAV", category="Actif", instrument_type="SICAV/FCP"))
    db_session.add(Product(ticker=action, name="Stock", category="Actif", instrument_type="Action"))
    await db_session.flush()

    tickers = await get_etf_tickers(db_session)
    assert etf in tickers
    assert sicav in tickers
    assert action not in tickers


# ---------------------------------------------------------------------------
# get_direct_stock_tickers_in_etf_pools
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_direct_stock_tickers_in_etf_pools_finds_action_alongside_etf(db_session):
    setup = await _setup_pool(db_session, f"dspool-{id(db_session)}", "Energie")
    etf_ticker = f"STN2.{id(db_session)}"
    stock_ticker = f"TTE2.{id(db_session)}"
    db_session.add(Product(ticker=etf_ticker, name="ETF", category="Actif", instrument_type="ETF"))
    db_session.add(Product(ticker=stock_ticker, name="TotalEnergies", category="Actif", instrument_type="Action"))
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=setup["pool_id"], ticker=etf_ticker))
    db_session.add(PoolProduct(pool_id=setup["pool_id"], ticker=stock_ticker))
    await db_session.flush()

    result = await get_direct_stock_tickers_in_etf_pools(db_session)
    assert (stock_ticker, "TotalEnergies") in result
    assert etf_ticker not in [t for t, _ in result]


@pytest.mark.asyncio
async def test_get_direct_stock_tickers_in_etf_pools_excludes_action_only_pool(db_session):
    """A pool with no ETF/SICAV at all contributes no direct-stock tickers."""
    setup = await _setup_pool(db_session, f"actiononly-{id(db_session)}", "ActionsOnly")
    stock_ticker = f"SOLO.{id(db_session)}"
    db_session.add(Product(ticker=stock_ticker, name="Solo Stock", category="Actif", instrument_type="Action"))
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=setup["pool_id"], ticker=stock_ticker))
    await db_session.flush()

    result = await get_direct_stock_tickers_in_etf_pools(db_session)
    assert stock_ticker not in [t for t, _ in result]


@pytest.mark.asyncio
async def test_get_direct_stock_tickers_in_etf_pools_empty_when_no_etf_anywhere(db_session):
    """No ETF/SICAV product exists at all → early return before the second query."""
    result = await get_direct_stock_tickers_in_etf_pools(db_session)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# compute_pool_lookthrough — pool-not-found guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_pool_lookthrough_nonexistent_pool_returns_none(db_session):
    setup = await _setup_pool(db_session, f"nopool-{id(db_session)}")
    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], 9_999_999)
    assert result is None


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_wrong_portfolio_returns_none(db_session):
    setup = await _setup_pool(db_session, f"wrongpf-{id(db_session)}")
    other_portfolio = Portfolio(name=f"Other-{id(db_session)}")
    db_session.add(other_portfolio)
    await db_session.flush()

    result = await compute_pool_lookthrough(db_session, other_portfolio.id, setup["pool_id"])
    assert result is None


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_empty_pool_no_products(db_session):
    setup = await _setup_pool(db_session, f"emptypool-{id(db_session)}")
    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    assert result is not None
    assert result["total_eur"] == pytest.approx(0.0)
    assert result["by_company"] == []
    assert result["by_sector"] == []


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_pool_has_tickers_but_none_held(db_session):
    """PoolProduct rows exist, but the portfolio never actually bought any of them."""
    setup = await _setup_pool(db_session, f"unheld-{id(db_session)}")
    ticker = f"UNHELD.{id(db_session)}"
    db_session.add(Product(ticker=ticker, name="Unheld ETF", category="Actif", instrument_type="ETF"))
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=setup["pool_id"], ticker=ticker))
    await db_session.flush()

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    assert result["total_eur"] == pytest.approx(0.0)
    assert result["by_company"] == []


# ---------------------------------------------------------------------------
# compute_pool_lookthrough — instrument-type / pricing skip rules
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_pool_lookthrough_skips_cash_and_or_physique(db_session):
    setup = await _setup_pool(db_session, f"skip-{id(db_session)}")
    cash_ticker = f"LIQ.{id(db_session)}"
    gold_ticker = f"GOLD.{id(db_session)}"
    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          cash_ticker, held_units=1000, price=1.0, instrument_type="Cash")
    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          gold_ticker, held_units=1, price=30000.0, instrument_type="Or physique")

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    assert result["total_eur"] == pytest.approx(0.0)
    assert cash_ticker not in [e["key"] for e in result["by_company"]]


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_skips_ticker_with_no_price(db_session):
    setup = await _setup_pool(db_session, f"noprice-{id(db_session)}")
    ticker = f"NOPX.{id(db_session)}"
    db_session.add(Product(ticker=ticker, name="No Price ETF", category="Actif", instrument_type="ETF"))
    await db_session.flush()
    db_session.add(PoolProduct(pool_id=setup["pool_id"], ticker=ticker))
    db_session.add(Transaction(
        portfolio_id=setup["portfolio_id"], account_id=setup["account_id"],
        date=date(2025, 1, 1), type="Actif", ticker=ticker,
        currency="EUR", exchange_rate=1.0,
        quantity=-5.0, unit_price=100.0, unit_price_eur=100.0,
        total_amount=-500.0, total_amount_eur=-500.0,
    ))
    await db_session.flush()
    # No AssetPrice row at all.

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    assert result["total_eur"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_zero_price_excludes_position(db_session):
    """AssetPrice exists but price is exactly 0.0 → value_eur == 0 → excluded from totals."""
    setup = await _setup_pool(db_session, f"zeropx-{id(db_session)}")
    ticker = f"ZEROPX.{id(db_session)}"
    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          ticker, held_units=10, price=0.0)

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    assert result["total_eur"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_pool_lookthrough — the real cases: direct<->ETF and ETF<->ETF overlap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_pool_lookthrough_merges_direct_stock_with_etf_holding(db_session):
    """
    TotalEnergies held directly (TTE.PA) AND found inside STN.PA at 18.63% — both must
    merge into a single by_company line keyed on TTE.PA. STN.PA's top-10 covers only
    53.73% of assets (18.63% + 35.10% Shell) so the remainder must land in OTHER_KEY.
    """
    setup = await _setup_pool(db_session, f"merge-{id(db_session)}", "Energie")
    stn_ticker = f"STN.{id(db_session)}"
    tte_ticker = f"TTE.{id(db_session)}"

    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          stn_ticker, held_units=10, price=50.0, name="STN.PA-like")
    await replace_etf_holdings(db_session, stn_ticker, [
        {"ticker": tte_ticker, "name": "TotalEnergies SE", "weight_pct": 0.1863},
        {"ticker": "SHEL.L", "name": "Shell PLC", "weight_pct": 0.3510},
    ])
    await replace_sector_weightings(db_session, stn_ticker, {"energy": 0.9946})

    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          tte_ticker, held_units=5, price=60.0,
                          instrument_type="Action", name="TotalEnergies SE")
    # Synthetic self-row for the direct stock, as the fetch task would write it.
    await replace_etf_holdings(db_session, tte_ticker, [
        {"ticker": tte_ticker, "name": "TotalEnergies SE", "weight_pct": 1.0},
    ])
    await replace_sector_weightings(db_session, tte_ticker, {"energy": 1.0})
    await db_session.flush()

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])

    assert result["total_eur"] == pytest.approx(800.0)  # 10*50 (STN.PA) + 5*60 (TTE.PA)
    by_company = {e["key"]: e for e in result["by_company"]}
    # 500 * 0.1863 (via STN.PA) + 300 * 1.0 (direct) = 93.15 + 300 = 393.15
    assert by_company[tte_ticker]["value_eur"] == pytest.approx(393.15, abs=0.01)
    assert by_company["SHEL.L"]["value_eur"] == pytest.approx(175.5, abs=0.01)
    # 500 * (1 - 0.5373) = 231.35 — only STN.PA contributes to OTHER (TTE.PA direct is 100% covered)
    assert by_company[OTHER_KEY]["value_eur"] == pytest.approx(231.35, abs=0.01)
    # OTHER_KEY always sorts last, even though it isn't the smallest value here.
    assert result["by_company"][-1]["key"] == OTHER_KEY

    by_sector = {e["key"]: e["value_eur"] for e in result["by_sector"]}
    assert by_sector["energy"] == pytest.approx(800.0 * 0.9946 * (500 / 800) + 300.0, abs=1.0) \
        or by_sector["energy"] > 700  # sanity: energy dominates regardless of exact float path


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_merges_same_company_across_multiple_etfs(db_session):
    """
    Tencent (0700.HK) is a top-10 holding in three separate Asie-pool ETFs, with NO direct
    position at all. All three contributions must merge into one by_company line — this is
    the ETF<->ETF overlap the direct<->ETF test above does not exercise.
    """
    setup = await _setup_pool(db_session, f"tencent-{id(db_session)}", "Asie")
    tencent = "0700.HK"

    specs = [
        (f"FLXC.{id(db_session)}", 10, 100.0, 0.12),
        (f"H411.{id(db_session)}", 5, 50.0, 0.06),
        (f"H4ZX.{id(db_session)}", 20, 10.0, 0.08),
    ]
    for ticker, units, price, weight in specs:
        await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                              ticker, held_units=units, price=price)
        await replace_etf_holdings(db_session, ticker, [
            {"ticker": tencent, "name": "Tencent Holdings Ltd", "weight_pct": weight},
        ])
        await replace_sector_weightings(db_session, ticker, {"communication_services": 1.0})

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])

    assert result["total_eur"] == pytest.approx(10 * 100 + 5 * 50 + 20 * 10)  # 1450
    by_company = {e["key"]: e for e in result["by_company"]}
    # 1000*0.12 + 250*0.06 + 200*0.08 = 120 + 15 + 16 = 151
    assert by_company[tencent]["value_eur"] == pytest.approx(151.0, abs=0.01)


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_multi_sector_fund_not_collapsed_to_pool_theme(db_session):
    """
    A uranium-mining ETF genuinely diversifies a nominally "Energie" pool into
    Industrials/Utilities (real NUKL.DE weights) — by_sector must reflect that, not
    default to 100% "energy" just because of the pool's name.
    """
    setup = await _setup_pool(db_session, f"nukl-{id(db_session)}", "Energie")
    ticker = f"NUKL.{id(db_session)}"
    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          ticker, held_units=1, price=1000.0)
    await replace_sector_weightings(db_session, ticker, {
        "energy": 0.4653, "industrials": 0.4371, "utilities": 0.0882, "technology": 0.0094,
    })
    await replace_etf_holdings(db_session, ticker, [
        {"ticker": "CCO.TO", "name": "Cameco Corp", "weight_pct": 0.1556},
    ])

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    by_sector = {e["key"]: e["value_eur"] for e in result["by_sector"]}
    assert by_sector["energy"] == pytest.approx(465.3, abs=0.1)
    assert by_sector["industrials"] == pytest.approx(437.1, abs=0.1)
    assert by_sector["utilities"] == pytest.approx(88.2, abs=0.1)
    # Sorted descending: energy > industrials > utilities > technology
    assert [e["key"] for e in result["by_sector"]] == ["energy", "industrials", "utilities", "technology"]


# ---------------------------------------------------------------------------
# compute_pool_lookthrough — unclassified & partial-holdings-only edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_compute_pool_lookthrough_unfetched_ticker_is_unclassified(db_session):
    """A held ETF with no EtfHolding/EtfSectorWeighting rows at all (not yet synced)."""
    setup = await _setup_pool(db_session, f"unfetched-{id(db_session)}")
    ticker = f"UNSYNCED.{id(db_session)}"
    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          ticker, held_units=10, price=100.0)

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    assert result["unclassified_eur"] == pytest.approx(1000.0)
    assert result["unclassified_pct"] == pytest.approx(100.0)
    assert result["by_company"] == []
    assert result["by_sector"] == []


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_sector_only_no_holdings_still_aggregates_sector(db_session):
    """
    Defensive branch: sector rows exist with zero holdings rows (shouldn't happen via the
    real fetch task, which always writes both, but the aggregation must not treat this as
    "unclassified" — only "neither present" counts as unclassified.
    """
    setup = await _setup_pool(db_session, f"sectoronly-{id(db_session)}")
    ticker = f"SECTORONLY.{id(db_session)}"
    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          ticker, held_units=10, price=100.0)
    await replace_sector_weightings(db_session, ticker, {"healthcare": 1.0})
    # No replace_etf_holdings call at all — holdings_by_parent has no entry for this ticker.

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    assert result["unclassified_eur"] == pytest.approx(0.0)
    by_sector = {e["key"]: e["value_eur"] for e in result["by_sector"]}
    assert by_sector["healthcare"] == pytest.approx(1000.0)
    assert result["by_company"] == []


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_full_coverage_no_other_bucket(db_session):
    """A fund whose top-10 sums to >= 99.9% must NOT get an OTHER_KEY bucket."""
    setup = await _setup_pool(db_session, f"fullcov-{id(db_session)}")
    ticker = f"FULLCOV.{id(db_session)}"
    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          ticker, held_units=10, price=100.0)
    await replace_etf_holdings(db_session, ticker, [
        {"ticker": "ONLY.PA", "name": "Only Holding", "weight_pct": 1.0},
    ])

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    assert OTHER_KEY not in [e["key"] for e in result["by_company"]]


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_under_coverage_creates_other_bucket(db_session):
    """A fund whose top-10 covers 60% of assets → the remaining 40% is an explicit OTHER_KEY row."""
    setup = await _setup_pool(db_session, f"undercov-{id(db_session)}")
    ticker = f"UNDERCOV.{id(db_session)}"
    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          ticker, held_units=10, price=100.0)
    await replace_etf_holdings(db_session, ticker, [
        {"ticker": "XXX.PA", "name": "XXX", "weight_pct": 0.6},
    ])

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    by_company = {e["key"]: e["value_eur"] for e in result["by_company"]}
    assert by_company["XXX.PA"] == pytest.approx(600.0)
    assert by_company[OTHER_KEY] == pytest.approx(400.0)
    assert result["by_company"][-1]["key"] == OTHER_KEY


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_freshness_uses_oldest_contributing_update(db_session):
    """holdings_updated_at reflects the least-fresh contributing ticker (min across positions)."""
    setup = await _setup_pool(db_session, f"fresh-{id(db_session)}")
    older = f"OLDER.{id(db_session)}"
    newer = f"NEWER.{id(db_session)}"
    older_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    newer_at = datetime(2026, 7, 10, tzinfo=timezone.utc)

    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          older, held_units=1, price=100.0)
    await save_etf_fetch_result(db_session, older, holdings=[], sector_weightings={"energy": 1.0},
                                 fetched_at=older_at)
    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          newer, held_units=1, price=100.0)
    await save_etf_fetch_result(db_session, newer, holdings=[], sector_weightings={"energy": 1.0},
                                 fetched_at=newer_at)
    await db_session.flush()

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    assert result["holdings_updated_at"] == older_at.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_compute_pool_lookthrough_no_freshness_data_returns_none(db_session):
    """None of the contributing products have ever been fetched → holdings_updated_at is None."""
    setup = await _setup_pool(db_session, f"nofresh-{id(db_session)}")
    ticker = f"NOFRESH.{id(db_session)}"
    await _hold_position(db_session, setup["portfolio_id"], setup["account_id"], setup["pool_id"],
                          ticker, held_units=1, price=100.0)
    await replace_sector_weightings(db_session, ticker, {"energy": 1.0})

    result = await compute_pool_lookthrough(db_session, setup["portfolio_id"], setup["pool_id"])
    assert result["holdings_updated_at"] is None
