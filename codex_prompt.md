# Prompt for Codex

You are working on `SH Gold Analyzer V1.7.2 - Menu Callback Wiring Fix`.

Goal: keep this project a clean XAUUSD-only analysis dashboard with strict data honesty, a professional Real Data Hub, an institutional multi-timeframe workflow, and a frontend that never renders a blank screen.

Important constraints:

1. Use SH Gold Analyzer branding only.
2. Do not copy CRAZII logo, watermark, website text, or proprietary assets.
3. TradingView Lightweight Charts is only the frontend chart renderer.
4. Keep XAUUSD only.
5. Do not add lot size, account balance, FTMO, risk percent, prop firm mode, multi-pair support, auto trading, payment, VIP, or license features.
6. Gold-API live price is current price only and must not be used as fake history.
7. Data mode must come from `DataModeLockService`.
8. Missing, live-only, offline, test, or gapped data must not show as `No Trade`.
9. Real valid setup decisions are allowed only in `REAL_MODE`.
10. `REAL_MODE` must not be enabled from generated test history.
11. The frontend must show an Error Boundary, boot screen, backend offline shell, or empty chart state instead of a blank page.

V1.7.2 adds:

- safe `MobileMenuDrawer` callback defaults
- defined `handleOpenDataHub` / `handleCloseDataHub` callback wiring
- Data Hub menu open action without render crashes
- `frontend/src/components/ErrorBoundary.jsx`
- `frontend/src/utils/safeFormat.js`
- startup boot screen and slow-load warning
- safe API response fallbacks
- frontend debug ping panel
- backend offline fallback UI
- chart empty-state guard
- local storage validation and clear action
