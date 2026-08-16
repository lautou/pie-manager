---
paths:
  - "backend/app/services/pv_service.py"
  - "backend/app/api/routers/pv.py"
---

## Capital Gains (Plus-values) — critical business rules

### Endpoint
`GET /api/pv/?portfolio_id=X&account_id=Y` — returns WACOP, unrealized/realized PV per ticker.
Service: `app/services/pv_service.py`. Router: `app/api/routers/pv.py`.

### WACOP convention by instrument type

Same sign convention as the root `CLAUDE.md`'s "Transaction conventions" section (Buy = `quantity < 0`, Sell =
`quantity > 0` for assets; **inverted** for Cash Forex — acquiring = `quantity > 0` → BUY,
reducing = `quantity < 0` → SELL). Getting the Forex inversion wrong here specifically
breaks WACOP: applying the standard asset convention to JPY acquisitions would treat them
as SELL with WACOP=0 → massive fictitious PV.

### Products excluded from PV calculation
- `LIQUIDITE.*` (LIQUIDITE.EURO, LIQUIDITE.USD…) — pure cash, not a financial asset
- `instrument_type='Or physique'` (OR.PHYSIQUE, SICAV…) — special valuation logic
- `type='Frais'` and `type='Revenu'` — do not affect WACOP

### WACOP reset
When `qty_held ≤ 0.001` (float tolerance), position is closed: WACOP resets to 0 on the next buy.
The cumulative `realized_pv_total` is never reset.

