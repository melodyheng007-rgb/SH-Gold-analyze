# SH Gold Analyzer V1.7.2 Engine Rules

## Scope

- XAUUSD only.
- Pure analysis engine.
- TradingView Lightweight Charts is display-only.
- No TradingView scraping.
- No lot sizing, account balance, FTMO, prop firm, payment, VIP, auto trading, or multi-pair logic.

## Data Honesty

- `TEST_HISTORY` and `TEST_HISTORY_LIVE_ANCHORED` always lock to `TEST_MODE`.
- `REAL_CSV_HISTORY` is the real-history source used by the Real Mode Wizard.
- Test history must never be labeled real.
- Live price alone must never be labeled candle history.
- Missing, live-only, gapped, or offline data returns a waiting/offline state, not `No Trade`.
- Real valid setup decisions are allowed only in `REAL_MODE`.

## Frontend Stability

- The React app must be wrapped in `ErrorBoundary`.
- Startup must show a visible boot screen, not a blank background.
- Backend offline must render the dashboard shell with `BACKEND_OFFLINE_MODE`.
- Every `.map()` and `.slice()` in the UI must receive a safe array fallback.
- Empty chart data must render the chart shell with visible recovery actions.
- Drawer/menu callbacks must be passed from `App.jsx` and have safe no-op defaults.

## Institutional Analysis Engine V4

Workflow:

1. Data Integrity
2. HTF Bias
3. Liquidity Map
4. Dealing Range / CRT
5. Premium / Discount
6. POI Detection
7. Confirmation
8. Setup Quality Score
9. Final Decision

Required timeframes:

- `1D`
- `4H`
- `1H`
- `15M`
- `5M`

## Decisions

- `Waiting for Data`
- `Test Mode Analysis`
- `Live Only`
- `Waiting for Liquidity Sweep`
- `Waiting for Pullback to POI`
- `Waiting for 5M Confirmation`
- `No Trade`
- `Valid Buy Setup`
- `Valid Sell Setup`
- `High Quality Buy Setup`
- `High Quality Sell Setup`
- `Invalidated`

## Overlays V2

Draw only valid non-null values. Core overlays include Price Line, 30MA, Pivot, and KTR+3. Liquidity overlays include PDH, PDL, PWH, PWL, equal highs/lows, sweep, CRT levels, equilibrium, premium, and discount. Setup overlays include POI, entry zone, invalidation, and targets.

## Indicator Panels V3

- Market Pressure
- Liquidity Pressure
- Setup Quality

If `TEST_MODE`, show TEST DATA. If `LIVE_ONLY_MODE`, show waiting for candle history.
