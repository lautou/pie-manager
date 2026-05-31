"""
Seed historical prices from yfinance for all non-manual products.

Usage:
    python scripts/seed_prices.py --db-url postgresql://pie:pie_password@localhost:5432/pie_db
"""

import argparse
import logging
from datetime import date, timedelta

import yfinance as yf
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

SKIP_CATEGORIES = {"Manuel", "Frais"}
CASH_TICKER = "LIQUIDITE.EURO"


def seed_prices(db_url: str, start_date: date, end_date: date):
    engine = create_engine(db_url)

    with Session(engine) as session:
        rows = session.execute(
            text("SELECT ticker, category, currency FROM products")
        ).fetchall()

    tickers_to_fetch = []
    for ticker, category, currency in rows:
        if category in SKIP_CATEGORIES or ticker == CASH_TICKER:
            continue
        tickers_to_fetch.append((ticker, currency))

    log.info(f"Fetching prices for {len(tickers_to_fetch)} tickers from {start_date} to {end_date}")

    with Session(engine) as session:
        for ticker, currency in tickers_to_fetch:
            try:
                data = yf.download(
                    ticker,
                    start=start_date.isoformat(),
                    end=(end_date + timedelta(days=1)).isoformat(),
                    progress=False,
                    auto_adjust=True,
                )
                if data.empty:
                    log.warning(f"No data for {ticker}")
                    continue

                import math
                count = 0
                for row_date, row in data.iterrows():
                    price_date = row_date.date() if hasattr(row_date, "date") else row_date
                    raw = row["Close"].iloc[0] if hasattr(row["Close"], "iloc") else row["Close"]
                    price = round(float(raw), 4)
                    if math.isnan(price):
                        continue
                    session.execute(
                        text("""
                            INSERT INTO asset_prices (ticker, date, price, currency, source)
                            VALUES (:ticker, :date, :price, :currency, :source)
                            ON CONFLICT ON CONSTRAINT uq_asset_price_ticker_date
                            DO UPDATE SET price = EXCLUDED.price, source = EXCLUDED.source
                        """),
                        {"ticker": ticker, "date": price_date, "price": price, "currency": currency, "source": "yfinance"},
                    )
                    count += 1
                session.commit()
                log.info(f"  {ticker}: {count} prices imported")

            except Exception as e:
                log.error(f"  {ticker}: ERROR - {e}")

    log.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed historical prices from yfinance")
    parser.add_argument("--db-url", default="postgresql://pie:pie_password@localhost:5432/pie_db")
    parser.add_argument("--start-date", default="2024-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", default=date.today().isoformat(), help="End date YYYY-MM-DD")
    args = parser.parse_args()

    seed_prices(
        db_url=args.db_url,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
    )
