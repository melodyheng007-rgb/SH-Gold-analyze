# SH Market Analyzer V3.7 Engine Rules

## Scope

- Analyze XAUUSD and BTCUSD from completed provider candles.
- Treat TradingView as a visual reference, not an analysis data source.
- Keep the product research-only; it does not place broker orders.
- Present Diamond Zones as Buy/Sell key zones, not guaranteed entries or TP/SL signals.

## Trusted Data

- XAUUSD uses matched OANDA midpoint candle history.
- BTCUSD uses matched Binance spot candle history.
- Forming candles may be displayed but cannot confirm analysis.
- Stale, gapped, malformed, fallback, or unmatched data must be disclosed and cannot be promoted to a production setup.
- Generated or sample history must never be labeled as real market history.

## Diamond Integrity

- A Diamond is created only from information available at its completed-candle origin time.
- Historical Diamonds remain append-only and replayable after later score changes.
- Context and qualified zones remain visible but are not counted as confirmed trades.
- Validation outcomes use later candles only; same-candle stop and target touches remain ambiguous.
- XAU and BTC evidence, profiles, timeframes, and outcomes remain isolated.

## Position Profiles

- Scalp uses 15M direction with 5M confirmation.
- Swing uses 4H direction with 1H confirmation.
- A profile mismatch remains a blocker and cannot be replaced with a fabricated signal.

## Decision Safety

- Data trust, market direction, liquidity, POI, confirmation, regime, news, and quality gates must agree before a zone becomes actionable.
- Anti-chase logic blocks entries extended from structure or fair value.
- News locks and volatility shocks block promotion without deleting historical evidence.
- Scores and grades communicate evidence strength; they do not promise a profitable outcome.

## Account And API Security

- Market routes require a valid Supabase user session in production.
- Maintenance and provider settings additionally require an administrator role.
- Local `.env`, provider tokens, databases, logs, caches, and browser artifacts must never be committed.
- Service-role keys and OAuth client secrets must never be exposed through frontend environment variables.
