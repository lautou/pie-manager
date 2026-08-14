from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import portfolios, products, brokers, transactions, pools, prices, snapshots, dashboard, admin
from app.api.routers import holdings, rebalancing, analytics, pv, fiscal, indicators, transaction_import
from app.api.routers import country_performance


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.pgq import close_pgq_pool, get_pgq_queries, init_pgq_pool
    await init_pgq_pool()  # never raises — see app/core/pgq.py

    # On startup: fill any missing daily snapshots (non-blocking task).
    try:
        await get_pgq_queries().enqueue("fill_missing_snapshots", payload=b"startup")
    except Exception:
        pass  # Don't block startup if the job queue is unavailable

    # On startup: refresh live prices immediately so the UI doesn't wait up
    # to 15 min for the next scheduled PgQueuer run (non-blocking task).
    try:
        await get_pgq_queries().enqueue("refresh_prices_live", payload=b"startup")
    except Exception:
        pass  # Don't block startup if the job queue is unavailable

    # On startup: refresh ETF holdings too, rather than waiting up to a week for
    # the next scheduled PgQueuer run (non-blocking task).
    try:
        await get_pgq_queries().enqueue("refresh_etf_holdings", payload=b"startup")
    except Exception:
        pass  # Don't block startup if the job queue is unavailable

    # On startup: refresh macro indicators too, rather than waiting up to a day for
    # the next scheduled PgQueuer run (non-blocking task).
    try:
        await get_pgq_queries().enqueue("refresh_macro_indicators", payload=b"startup")
    except Exception:
        pass  # Don't block startup if the job queue is unavailable

    # On startup: refresh the country performance leaderboard too, rather than waiting up
    # to a day for the next scheduled PgQueuer run (non-blocking task).
    try:
        await get_pgq_queries().enqueue("refresh_country_performance", payload=b"startup")
    except Exception:
        pass  # Don't block startup if the job queue is unavailable

    yield
    await close_pgq_pool()


app = FastAPI(
    title="PIE Manager API",
    version="1.0.0",
    lifespan=lifespan,
    redirect_slashes=False,   # prevent 307 redirects on missing trailing slashes
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(portfolios.router, prefix="/api/portfolios")
app.include_router(products.router, prefix="/api/products")
app.include_router(brokers.router, prefix="/api/brokers")
app.include_router(transactions.router, prefix="/api/transactions")
app.include_router(pools.router, prefix="/api/pools")
app.include_router(prices.router, prefix="/api/prices")
app.include_router(snapshots.router, prefix="/api/snapshots")
app.include_router(dashboard.router, prefix="/api/dashboard")
app.include_router(holdings.router, prefix="/api/dashboard")
app.include_router(rebalancing.router, prefix="/api/dashboard")
app.include_router(analytics.router, prefix="/api/dashboard")
app.include_router(admin.router, prefix="/api/admin")
app.include_router(pv.router, prefix="/api/pv")
app.include_router(fiscal.router, prefix="/api/fiscal")
app.include_router(indicators.router, prefix="/api/indicators")
app.include_router(country_performance.router, prefix="/api/indicators")
app.include_router(transaction_import.router, prefix="/api/transactions/import")


@app.get("/health")
async def health():
    return {"status": "ok"}
