---
paths:
  - "backend/app/services/pv_service.py"
  - "backend/app/api/routers/pv.py"
  - "backend/app/api/routers/fiscal.py"
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

### `force_include_fees` — fiscal.py always includes both fee types, pv.py never does

`compute_capital_gains(db, portfolio_id, account_id=None, force_include_fees=False)`: when
`True` (only `app/api/routers/fiscal.py`'s two call sites pass this), acquisition fees are
folded into CUMP regardless of the broker's own `include_fees_in_cump` flag, and disposal fees
are deducted from realized PV — something `pv.py`'s own capital-gains page never does, by
design, in either case.

This asymmetry matches Degiro's own documented behavior, not an arbitrary choice: their live
PRU (Prix de Revient Unitaire)/unrealized P&L deliberately excludes brokerage fees and TTF
(what `include_fees_in_cump=False` on Degiro/IBKR mirrors for the main capital-gains page), but
their realized P&L always includes both. Verified against a real Degiro 2025 annual report —
this app's fiscal figures only reconciled exactly with Degiro's own reported realized PV once
both fee corrections were applied unconditionally in `fiscal.py`, while `pv.py`'s own numbers
were deliberately left untouched to keep matching Degiro's live PRU/latent-P&L display.

