from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import portfolios, products, brokers, transactions, pools, prices, snapshots, dashboard, admin
from app.api.routers import holdings, rebalancing, analytics, pv, fiscal


@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup: fill any missing daily snapshots (non-blocking Celery task)
    try:
        from app.tasks.snapshots import fill_missing_snapshots
        fill_missing_snapshots.delay()
    except Exception:
        pass  # Don't block startup if Celery is unavailable

    # On startup: refresh live prices immediately so the UI doesn't wait up
    # to 15 min for the next scheduled Celery Beat run (non-blocking task).
    try:
        from app.tasks.prices import refresh_prices_live
        refresh_prices_live.delay()
    except Exception:
        pass  # Don't block startup if Celery is unavailable

    # On startup: refresh ETF holdings too, rather than waiting up to a week for
    # the next scheduled Celery Beat run (non-blocking task).
    try:
        from app.tasks.etf_holdings import refresh_etf_holdings
        refresh_etf_holdings.delay()
    except Exception:
        pass  # Don't block startup if Celery is unavailable
    yield


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


@app.get("/health")
async def health():
    return {"status": "ok"}
