# SH Gold Analyzer V1.7.2

Menu Callback Wiring Fix for XAUUSD / Gold.

> Educational analysis only. This project does not place trades, calculate lot size, manage account risk, process payments, scrape TradingView, or provide financial advice.

## Direction

- XAUUSD only.
- Original SH Gold Analyzer branding only.
- TradingView Lightweight Charts is display-only.
- Gold-API live price is current price only, not fake candle history.
- No lot size, account balance, FTMO, prop firm mode, payment, VIP/license, auto trading, or multi-pair logic.

## V1.7.2 Highlights

- Mobile menu `onOpenDataHub` callback is defined, passed, and guarded.
- Menu action callbacks have safe no-op defaults.
- Data Hub can be opened from the Menu without render crashes.
- React Error Boundary with visible frontend render error screen.
- Startup boot screen with slow-load warning, retry, continue offline, and debug buttons.
- Safe API fallbacks so one bad endpoint cannot blank the dashboard.
- Safe format helpers for numbers, prices, text, arrays, objects, and dates.
- Backend-offline dashboard shell with disabled API actions.
- Empty chart guard with Smart Setup, Generate Test History, Debug Data, and Refresh actions.
- Real Data Hub and Institutional Analysis Engine V4 remain intact.

## Data Modes

- `REAL_MODE`: real CSV history, live price, no active gap.
- `TEST_MODE`: generated test history exists. Output is `Test Mode Analysis`.
- `LIVE_ONLY_MODE`: live price/building candles exist, but full history is missing.
- `GAP_WARNING_MODE`: history exists but is stale or price-misaligned.
- `NO_DATA_MODE`: no usable candles and no live price.
- `BACKEND_OFFLINE_MODE`: frontend cannot reach backend.

## Core API

```text
GET  /api/health
GET  /api/xauusd/data-hub
GET  /api/xauusd/data-mode
GET  /api/xauusd/readiness
GET  /api/xauusd/pro-analysis-v4
GET  /api/xauusd/analysis-explanation
GET  /api/xauusd/chart-data?timeframe=15M&limit=500
GET  /api/xauusd/overlays-v2?timeframe=15M
GET  /api/xauusd/indicator-panels-v3?timeframe=15M
GET  /api/xauusd/debug-data
POST /api/xauusd/real-mode-wizard
POST /api/xauusd/import-real-history
POST /api/xauusd/generate-test-history-v2
POST /api/xauusd/clear-test-history
POST /api/xauusd/analyze-v4
POST /api/xauusd/smart-setup
POST /api/xauusd/set-data-mode
POST /api/xauusd/rebuild-candles
```

## Run

Backend:

```bash
cd backend
.venv\Scripts\activate
uvicorn app:app --reload --host 127.0.0.1 --port 8001
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.
