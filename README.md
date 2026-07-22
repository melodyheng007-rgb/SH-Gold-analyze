# SH Market Analyzer V3.8.5

## V3.8 Adaptive Diamond Intelligence

- Diamond History is append-only and exposes wins, losses, open zones, invalidated zones, and chart replay.
- Grade D or better structural Diamond Zones are displayed without Active/Balanced/Precision modes.
- Scalp uses 15M direction with a 5M completed-candle trigger; Swing uses 4H direction with a 1H trigger.
- Released calendar events are clearly marked and display provider Actual values when available.

Evidence-driven trading workstation for closed-candle XAUUSD and BTCUSD market research.

> Educational analysis only. Historical validation does not guarantee future performance. The project does not place trades or scrape TradingView.

## Market Data

- XAUUSD analysis uses matched `OANDA:XAUUSD` midpoint candle history.
- The OANDA feed is source-locked across chart, indicators, Pro Analyze, Diamond Zone, and history validation.
- BTCUSD analysis uses matched `BINANCE:BTCUSDT` spot candle history.
- TradingView remains a separate live visual reference.
- Unmatched or stale feeds are visibly downgraded to research-only.
- Forming candles are displayed live but excluded from analysis and validation.
- XAU freshness respects OANDA's market session, so scheduled weekend and maintenance closures do not create a false stale-data lock.

## V3.2 Result Integrity

- Every detected origin remains a blue Buy or orange Sell Diamond Zone, preserving the original chart identity and history.
- Small hollow crystals show context, stronger hollow crystals show qualified watches, and filled crystals show confirmed closed-candle entries.
- Zone Intelligence V2 ranks visible Diamonds using origin quality, premium/discount location, structure, liquidity, rejection, survival, and distance.
- Every zone exposes its signal role, confirmation stage, health, final blocker, and actionable-entry state.
- Validation reports final failure diagnostics such as no retest or zone invalidation without counting those origins as trades.
- Decision Quality carries the same result-integrity contract through the API, history, alerts, and UI.

## V3.1 Foundation

- Anti-Chase Location Guard blocks directional entries that are overextended from EMA20 at an extreme completed-candle range location.
- Auto Entry now requires the Regime and Location gate before a Diamond plan can be armed.
- Decision Quality exposes a six-stage execution-readiness path with prioritized live blockers.
- The compact decision strip shows the next gate, blocker reason, readiness, and ATR extension without adding another control panel.

## V3.0 Foundation

- The persistent Evidence Ledger upgrades every Diamond into an auditable lifecycle without deleting legacy history.
- Lifecycle events preserve detected, qualified, confirmed, waiting, active, resolved, expired, ambiguous, and invalidated stages.
- Evidence snapshots freeze feed trust, Decision Quality, Regime Guard, news risk, session context, K-Trend, MTF state, and Diamond quality at the observed stage.
- Directional 5, 10, and 20-bar forward returns mature only after the required later provider candles close.
- Performance Calibration separates XAU/BTC evidence by Scalp, Swing, timeframe, session, direction, and market regime.
- Win rate and expectancy use confirmed resolved entries only; context, expired, and ambiguous events remain visible but are excluded.
- The History dock is now a compact Evidence Ledger with lifecycle counts, profile calibration, evidence facts, forward returns, and chart replay.
- V3 remains research-only: no evidence score guarantees future performance and no broker order is submitted.

## V2.3 Foundation

- Regime Guard classifies bullish trend, bearish trend, range, transition, and volatility shock from completed candles only.
- EMA20/50 direction, ATR14, path efficiency, normalized EMA slope, volatility expansion, and 48-candle range location are disclosed in the API.
- Opposing-trend setups and volatility shocks are vetoed without inventing a replacement signal.
- Range setups must reach the directionally correct outer 25% edge before the regime gate can open.
- Decision Quality includes regime agreement inside Market Agreement and applies conservative conflict, transition, range, and shock ceilings.
- The existing Confidence panel shows the regime, gate, strength, range location, and key measurements without adding another tab or action button.

## V2.2 Foundation

- Decision Quality separates Data Confidence, Strategy Evidence, Diamond Quality, Market Agreement, and Risk Geometry.
- Every score exposes its checks, available points, earned points, and blocker reason.
- Conservative score ceilings prevent untrusted feeds, news locks, context markers, and historical Diamonds from appearing actionable.
- A historical confirmed Diamond is explicitly rejected as a current entry unless its event time matches the latest completed candle.
- `Next Best Action` identifies the missing evidence without inventing a Buy or Sell signal.
- The compact Reliability Matrix is available inside the existing Evidence panel on desktop and mobile.
- Decision Quality cannot modify trade plans, promote strategies, or submit broker orders.

## V2.1 Foundation

- A 13-stage Gate Funnel explains where completed-candle candidates pass or fail without loosening signal rules.
- Diamond V6.1 remains the live Champion while V6.2 runs as a shadow-only Challenger.
- Challenger promotion is never automatic and requires at least 100 resolved events plus manual review.
- Feed Reconciliation checks provider source, OHLC integrity, duplicates, gaps, freshness, and comparable-close drift.
- Execution Reality separates research-trackable setups from broker-executable pricing; midpoint candles are not treated as Bid/Ask quotes.
- Deduplicated in-app alerts are created only for confirmed closed-candle Diamond events.
- A compact Confidence panel combines gate blockers, feed trust, execution readiness, governance, and alerts.

## V2.0 Foundation

- Diamond V6.1 closed-candle walk-forward Validation Lab.
- No-look-ahead event timing: a signal is accepted only on its historical confirmation candle.
- Later candles exclusively resolve stop and fixed-R target outcomes.
- Same-candle stop and target touches are marked ambiguous and excluded from win rate.
- Validation evidence segmented by direction and UTC market session.
- Immutable SQLite validation cache with provider data fingerprint and engine version.
- Persistent Diamond audit metadata: strategy, profile, engine version, and configuration fingerprint.
- Click-to-replay Diamond History on the original chart candle.
- XAU and BTC validation remain isolated by symbol and timeframe.

## Evidence Rules

- `INSUFFICIENT_SAMPLE`: fewer than 20 resolved events.
- `EARLY_SAMPLE`: 20-49 resolved events.
- `DEVELOPING_SAMPLE`: 50-99 resolved events.
- `EVIDENCE_READY`: at least 100 resolved events.
- Context and qualified origins without confirmed entries are never counted as wins or losses.

## Core V2 API

```text
GET  /api/health
GET  /api/market/signal-view
GET  /api/market/chart-live
GET  /api/market/diamond-history
GET  /api/market/diamond-validation
POST /api/market/diamond-validation/run
GET  /api/market/strategy-governance
GET  /api/market/alerts
POST /api/market/alerts/{alert_id}/acknowledge
GET  /api/market/setups
POST /api/market/analyze-v4
```

## Run

Backend:

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app:app --reload --host 127.0.0.1 --port 8001
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Accounts And Deployment

Production authentication uses Supabase Auth and includes email registration, 6-digit signup confirmation, login, persistent sessions, 6-digit password recovery, and Google sign-in. The browser sends the active session token to protected market routes; privileged maintenance tools additionally require an administrator role.

Copy the example environment files and provide your own project values:

```text
frontend/.env.example
backend/.env.example
```

Vite loads `frontend/.env` and FastAPI loads `backend/.env` during local development. Hosting environment variables take precedence over the backend file.

Account access is locked by default in the frontend. Use `VITE_AUTH_REQUIRED=false` only for explicit local developer bypass. Set `AUTH_REQUIRED=true` on the deployed backend and keep `VITE_AUTH_REQUIRED=true` in Vercel. Never expose a Supabase service-role key or Google client secret through a `VITE_` variable.

See [docs/DEPLOY_VERCEL.md](docs/DEPLOY_VERCEL.md) for the complete GitHub, Supabase, Google OAuth, backend, and Vercel checklist.
