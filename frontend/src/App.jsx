import React, { useEffect, useMemo, useRef, useState } from 'react'
import { CandlestickSeries, createChart, LineSeries } from 'lightweight-charts'
import {
  analyzeV4,
  archiveStaleHistory,
  backtestCsvXauusd,
  clearAnalysisCache,
  clearEngineLogs,
  clearInvalidCandles,
  clearTestHistory,
  downloadFreeHistory,
  getAnalysisState,
  getAnalysisExplanation,
  getBackendStatus,
  getDataHub,
  getDataMode,
  getDataState,
  getGapDiagnosis,
  getChartData,
  getDataIntegrity,
  getDataReadiness,
  getDebugData,
  getEngineLogs,
  getEngineStatus,
  getHealth,
  getIndicatorPanelsV3,
  getOverlayStatus,
  getOverlaysV2,
  getProviderStatus,
  getRoutes,
  generateTestHistoryV2,
  importRealHistory as importRealHistoryApi,
  oneClickWarmup,
  runRealModeWizard,
  rebuildCandleEngine,
  exportCurrentCandles,
  resetDatabase,
  saveProviderSettings,
  setEngineMode,
  seedHistory,
  setDataMode as saveDataMode,
  fixGap,
  smartSetup,
  startLiveBuilder,
  stopLiveBuilder,
  toggleTestMode,
  uploadCsvForBacktest,
} from './api.js'
import { API_BASE_URL } from './config/api.js'
import { createMenuActions, groupMenuActions } from './actions/menuActions.js'
import { safeArray, safeObject, safePrice, safeText } from './utils/safeFormat.js'

const TOOLBAR_TIMEFRAMES = ['1M', '5M', '15M', '1H', '4H', '1D']
const TRADINGVIEW_SYMBOLS = ['TVC:GOLD', 'OANDA:XAUUSD', 'FX_IDC:XAUUSD']
const TRADINGVIEW_INTERVALS = { '1M': '1', '5M': '5', '15M': '15', '1H': '60', '4H': '240', '1D': 'D' }
const CHART_MODES = {
  tradingview: 'TradingView Live',
  analysis: 'SH Analysis',
  split: 'Split View',
}
const NO_HISTORY_MESSAGE = 'No candle data available. Start live builder or import recent history.'
const GAP_MESSAGE = 'History gap detected. Live price is not aligned with local history.'
const FULL_ANALYSIS_MESSAGE = 'Full analysis requires recent 1D, 4H, 1H, 15M, and 5M candle history.'
const APP_VERSION = 'V1.8.3'
const APP_TITLE = 'SH Gold Analyzer V1.8.3 - Candle History Alignment Lock'
const DEFAULT_LOCKED_MODE = {
  locked_mode: 'NO_DATA_MODE',
  data_mode: 'NO_DATA_MODE',
  data_mode_label: 'NO DATA',
  backend_status: 'STARTING',
  provider_status: 'STARTING',
  provider_name: '-',
  candle_source: 'NO_CANDLE_SOURCE',
  analysis_state: 'STARTING',
  can_analyze: false,
  can_refresh: true,
  can_smart_setup: true,
  description: 'Starting SH Gold Analyzer.',
}

const LINE_STYLE = {
  solid: 0,
  dotted: 1,
  dashed: 2,
}

class OverlayCollisionManager {
  static manage(overlays = {}, visibility = {}) {
    const items = Object.entries(safeObject(overlays))
      .filter(([, item]) => item?.ready && item?.price !== null && item?.price !== undefined)
      .filter(([key]) => visibility[key] !== false)
      .sort(([, a], [, b]) => Number(b.price) - Number(a.price))
    const managed = []
    items.forEach(([key, item]) => {
      const last = managed[managed.length - 1]
      if (last && Math.abs(Number(last.price) - Number(item.price)) < 0.25) {
        last.label = `${last.label} + ${item.label}`
        last.keys.push(key)
        return
      }
      managed.push({ key, keys: [key], ...item })
    })
    return managed.slice(0, 8)
  }
}

function tone(status = '') {
  if (['LIVE', 'READY', 'VALID', 'REAL', 'REAL_MODE', 'ONLINE', 'ALIGNED', 'HEALTHY', 'HIGH', 'Full Analysis Ready', 'FULL_ANALYSIS_READY', 'Chart Ready', 'Valid Setup', 'High Quality Setup', 'RECENT_HISTORY_READY'].includes(status)) return 'good'
  if (['TEST', 'TEST_MODE', 'MEDIUM', 'WARMING_UP', 'WARNING_PRICE_GAP', 'NO_COMPLETED_CANDLES', 'LOW_TICK_CONFIDENCE', 'PARTIAL', 'GAP_WARNING', 'GAP_WARNING_MODE', 'READY_WITH_GAP_WARNING', 'STALE_OR_PRICE_GAP', 'STARTING', 'RETRYING', 'NO_PRICE', 'WAITING', 'Waiting for Data', 'Waiting for Live Price', 'Waiting for Recent Candle History', 'Waiting for Recent History', 'Waiting for Liquidity Sweep', 'Waiting for Pullback to POI', 'Waiting for 5M Confirmation', 'LIVE_ONLY', 'LIVE_ONLY_MODE', 'LIVE ONLY', 'No History', 'NO_HISTORY', 'NO_DATA_MODE', 'Waiting for Live Tick', 'Partial Analysis Ready', 'Chart Ready - Test Mode', 'Test Mode Analysis', 'Test Data Mode', 'TEST_DATA_MODE'].includes(status)) return 'warn'
  if (['PRICE_GAP', 'CRITICAL_PRICE_GAP', 'PRICE_AND_TIME_GAP', 'TIME_GAP', 'STALE_HISTORY', 'FUTURE_HISTORY', 'INVALID', 'No Trade', 'STOPPED', 'CONNECTION_FAILED', 'RATE_LIMIT', 'NO_CANDLES', 'NO_DATA', 'ERROR', 'Backend Offline', 'BACKEND_OFFLINE', 'BACKEND_OFFLINE_MODE', 'API Route Error'].includes(status)) return 'bad'
  return 'neutral'
}

function asPrice(value, fallback = '-') {
  const formatted = safePrice(value, 2)
  return formatted === '-' ? fallback : formatted
}

function clampPercent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}

function midpoint(low, high, fallback = null) {
  const lowNumber = Number(low)
  const highNumber = Number(high)
  if (Number.isFinite(lowNumber) && Number.isFinite(highNumber)) return (lowNumber + highNumber) / 2
  if (Number.isFinite(lowNumber)) return lowNumber
  if (Number.isFinite(highNumber)) return highNumber
  const fallbackNumber = Number(fallback)
  return Number.isFinite(fallbackNumber) ? fallbackNumber : null
}

function timeframeLabel(value) {
  return String(value || '').toLowerCase()
}

function movingAverageData(candles, period = 30) {
  const data = []
  const window = []
  safeArray(candles).forEach(candle => {
    const close = Number(candle?.close)
    if (!Number.isFinite(close) || candle?.time === undefined || candle?.time === null) return
    window.push(close)
    if (window.length > period) window.shift()
    if (window.length >= Math.min(period, 5)) {
      data.push({
        time: candle.time,
        value: window.reduce((sum, item) => sum + item, 0) / window.length,
      })
    }
  })
  return data
}

function latestContinuousCandles(candles, timeframe = '15M') {
  const items = safeArray(candles).filter(item => Number.isFinite(Number(item?.time)) && Number.isFinite(Number(item?.close)))
  if (items.length <= 2) return items
  const minutes = { '1M': 1, '5M': 5, '15M': 15, '1H': 60, '4H': 240, '1D': 1440 }[timeframe] || 15
  const maxTimeGap = minutes * 60 * 6
  const targetWindow = Math.min(260, items.length)
  let start = Math.max(0, items.length - targetWindow)
  for (let index = items.length - 1; index > 0; index -= 1) {
    const current = items[index]
    const previous = items[index - 1]
    const timeGap = Math.abs(Number(current.time) - Number(previous.time))
    if (timeGap > maxTimeGap) {
      start = index
      break
    }
  }
  return items.slice(start)
}

function hasLargeTimeGap(candles, timeframe = '15M') {
  const items = safeArray(candles).filter(item => Number.isFinite(Number(item?.time)))
  if (items.length < 2) return false
  const minutes = { '1M': 1, '5M': 5, '15M': 15, '1H': 60, '4H': 240, '1D': 1440 }[timeframe] || 15
  const maxTimeGap = minutes * 60 * 6
  return items.some((item, index) => index > 0 && Math.abs(Number(item.time) - Number(items[index - 1].time)) > maxTimeGap)
}

function sourceLabel(status) {
  if (!status) return '-'
  return status.provider_display_name || status.provider_name || status.provider || '-'
}

function deriveBias(analysis, overlays, panels) {
  if (analysis?.bias) return analysis.bias
  const price = Number(overlays?.chart_overlays?.price_line)
  const ma = Number(overlays?.chart_overlays?.ma_30)
  const pressure = panels?.indicator_panels?.market_pressure_score || {}
  if (!Number.isFinite(price) || !Number.isFinite(ma)) return 'Range'
  if (price > ma && Number(pressure.bullish || 0) >= Number(pressure.bearish || 0)) return 'Bullish'
  if (price < ma && Number(pressure.bearish || 0) > Number(pressure.bullish || 0)) return 'Bearish'
  return 'Range'
}

function getSavedTimeframe() {
  try {
    const value = localStorage.getItem('sh_gold_timeframe')
    return TOOLBAR_TIMEFRAMES.includes(value) ? value : '15M'
  } catch (_) {
    return '15M'
  }
}

function getSavedChartMode() {
  try {
    const value = localStorage.getItem('sh_gold_chart_mode')
    return Object.keys(CHART_MODES).includes(value) ? value : 'tradingview'
  } catch (_) {
    return 'tradingview'
  }
}

function getSavedTradingViewSymbol() {
  try {
    const value = localStorage.getItem('sh_gold_tv_symbol')
    return TRADINGVIEW_SYMBOLS.includes(value) ? value : 'TVC:GOLD'
  } catch (_) {
    return 'TVC:GOLD'
  }
}

function clearBrokenLocalStorage() {
  try {
    const timeframe = localStorage.getItem('sh_gold_timeframe')
    if (timeframe && !TOOLBAR_TIMEFRAMES.includes(timeframe)) {
      localStorage.removeItem('sh_gold_timeframe')
    }
  } catch (_) {
    // Storage may be blocked; defaults keep the app rendering.
  }
}

function safeStorageGet(key, fallback = '-') {
  try {
    return localStorage.getItem(key) || fallback
  } catch (_) {
    return fallback
  }
}

function engineSourceLabel(lockedMode = {}, dataIntegrity = {}) {
  const mode = lockedMode?.locked_mode || lockedMode?.data_mode
  if (mode === 'REAL_MODE' || dataIntegrity?.real_recent_history_present || dataIntegrity?.real_csv_history_present) return 'REAL_HISTORY'
  if (mode === 'TEST_MODE' || dataIntegrity?.test_data_present) return 'TEST_HISTORY'
  if (mode === 'LIVE_ONLY_MODE') return 'LIVE_ONLY'
  return 'NO_DATA'
}

function engineAnalysisState(lockedMode = {}, readiness = {}) {
  if (lockedMode?.analysis_state) return lockedMode.analysis_state
  if (readiness?.full_analysis_ready) return 'Ready'
  if (readiness?.chart_ready) return 'Waiting'
  return 'Disabled'
}

function SymbolBadge({ latestPrice }) {
  return (
    <div className="symbol-badge">
      <span>{APP_TITLE}</span>
      <strong>XAUUSD</strong>
      <b>{asPrice(latestPrice)}</b>
    </div>
  )
}

function DataModeBadge({ mode }) {
  const locked = mode?.data_mode_lock || mode
  const label = locked?.data_mode_label || locked?.locked_mode || locked?.data_mode || 'NO DATA'
  const backend = locked?.backend_status || 'ONLINE'
  const description = mode?.description || mode?.data_mode_description || 'Waiting for data mode'
  return (
    <div className={`data-mode-badge ${tone(locked?.locked_mode || locked?.data_mode || label)}`}>
      <span>Data Mode</span>
      <strong>{label}</strong>
      <em>{description}</em>
      <b className={tone(backend)}>{backend}</b>
    </div>
  )
}

function DataModeBanner({ lockedMode, chartMode = 'analysis', readiness }) {
  const mode = lockedMode?.locked_mode || lockedMode?.data_mode
  if (chartMode !== 'analysis') {
    return (
      <div className="data-mode-banner visual">
        <strong>Visual Mode: {chartMode === 'split' ? 'Split View' : 'TradingView Live'}</strong>
        <span>Engine Mode: separate SH internal candle data. TradingView widget data is never used for analysis.</span>
      </div>
    )
  }
  if (!mode) {
    return (
      <div className="data-mode-banner">
        <strong>Data Mode: NO DATA</strong>
        <span>Backend: {lockedMode?.backend_status || 'ONLINE'} / Analysis: {engineAnalysisState(lockedMode, readiness)}</span>
      </div>
    )
  }
  if (mode === 'TEST_MODE') {
    return <div className="data-mode-banner test"><strong>TEST MODE</strong><span>Analyze Test only. Generated candles are never real signals.</span></div>
  }
  if (mode === 'LIVE_ONLY_MODE') {
    return <div className="data-mode-banner live-only"><strong>LIVE ONLY</strong><span>Chart and live price only. Full analysis is disabled until real candle history exists.</span></div>
  }
  if (mode === 'BACKEND_OFFLINE_MODE') {
    return <div className="data-mode-banner offline"><strong>BACKEND OFFLINE</strong><span>API actions are disabled and live status is hidden.</span></div>
  }
  if (mode === 'REAL_MODE') {
    return <div className="data-mode-banner real"><strong>REAL MODE</strong><span>REAL_CSV_HISTORY and live provider checks are active.</span></div>
  }
  return null
}

function AppNotice({ error, message, warnings, backendOffline, apiBaseUrl }) {
  const items = safeArray(warnings)
  if (backendOffline) {
    return (
      <section className="app-notice offline">
        <div>
          <strong>Backend Offline</strong>
          <span>Start the backend server to restore live chart, data loading, and analysis actions.</span>
        </div>
        <em>{apiBaseUrl}</em>
      </section>
    )
  }
  if (!error && !message && !items.length) return null
  return (
    <section className={`app-notice ${error ? 'bad' : message ? 'good' : 'warn'}`}>
      <div>
        <strong>{error ? 'Action Needed' : message ? 'Update' : 'Data Notice'}</strong>
        <span>{error || message || items[0]}</span>
      </div>
      {items.length > 1 && <em>+{items.length - 1} more</em>}
    </section>
  )
}

function BootScreen({ boot, health, apiError, debugPing, onRetry, onContinueOffline, onDebug }) {
  return (
    <main className="boot-screen">
      <section>
        <strong>Starting SH Gold Analyzer...</strong>
        <p>{boot?.slow ? 'App is taking longer than expected.' : 'Loading chart shell, backend health, and app configuration.'}</p>
        <div className="boot-checks">
          <span>Frontend Mounted <b>OK</b></span>
          <span>API Base URL <b>{API_BASE_URL}</b></span>
          <span>Backend Health <b className={tone(health?.status || apiError?.code || 'STARTING')}>{health?.status || apiError?.code || 'STARTING'}</b></span>
          <span>Chart Component <b>Loaded</b></span>
        </div>
        {(boot?.slow || apiError) && (
          <div className="boot-actions">
            <button onClick={onRetry}>Retry</button>
            <button onClick={onContinueOffline}>Continue Offline</button>
            <button onClick={onDebug}>Debug</button>
          </div>
        )}
        {apiError && <em>{apiError.message}</em>}
        {debugPing && <pre>{JSON.stringify(debugPing, null, 2)}</pre>}
      </section>
    </main>
  )
}

function TimeframeSwitcher({ timeframe, onChange }) {
  return (
    <div className="tf-switcher" aria-label="Timeframe">
      {TOOLBAR_TIMEFRAMES.map(item => (
        <button className={timeframe === item ? 'active' : ''} key={item} onClick={() => onChange(item)}>
          {timeframeLabel(item)}
        </button>
      ))}
    </div>
  )
}

function ChartModeSwitcher({ chartMode, onChange }) {
  return (
    <div className="chart-mode-switcher" aria-label="Chart Mode">
      {Object.entries(CHART_MODES).map(([key, label]) => (
        <button key={key} className={chartMode === key ? 'active' : ''} onClick={() => onChange(key)}>
          {label}
        </button>
      ))}
    </div>
  )
}

function TopToolbar({ timeframe, chartMode, latestPrice, onTimeframe, onChartMode, onAnalyze, onRefresh, onMenu, analyzeDisabled, refreshDisabled, loading, analyzeLabel }) {
  return (
    <header className="top-toolbar">
      <SymbolBadge latestPrice={latestPrice} />
      <TimeframeSwitcher timeframe={timeframe} onChange={onTimeframe} />
      <ChartModeSwitcher chartMode={chartMode} onChange={onChartMode} />
      <div className="toolbar-actions">
        <button title="Analyze" onClick={onAnalyze} disabled={analyzeDisabled}>{loading ? 'Working' : analyzeLabel}</button>
        <button title="Refresh data" onClick={onRefresh} disabled={refreshDisabled}>Refresh</button>
        <button title="Menu" onClick={onMenu}>Menu</button>
      </div>
    </header>
  )
}

function VisualReferenceNotice({ chartMode, internalReady }) {
  if (chartMode === 'analysis') return null
  return (
    <div className={`visual-reference-notice ${internalReady ? 'ready' : 'warn'}`}>
      <strong>TradingView Live Chart</strong>
      <span>TradingView Live Chart is for visual reference only. SH Analysis Engine uses internal candle data.</span>
      {!internalReady && <em>SH internal data for this timeframe is not ready.</em>}
    </div>
  )
}

function EngineDataSourceBadge({ chartMode, lockedMode, readiness, dataIntegrity, backendOffline }) {
  const source = engineSourceLabel(lockedMode, dataIntegrity)
  const analysisState = backendOffline ? 'Disabled' : engineAnalysisState(lockedMode, readiness)
  return (
    <section className="engine-source-badge">
      <div>
        <span>Visual Mode</span>
        <strong>{chartMode === 'analysis' ? 'SH Analysis Chart' : 'TradingView Live'}</strong>
      </div>
      <div>
        <span>SH Engine Data Source</span>
        <strong className={tone(source === 'REAL_HISTORY' ? 'REAL_MODE' : source)}>{source}</strong>
      </div>
      <div>
        <span>TradingView Visual Source</span>
        <strong>TradingView Widget</strong>
      </div>
      <div>
        <span>Backend</span>
        <strong className={tone(backendOffline ? 'BACKEND_OFFLINE' : lockedMode?.backend_status)}>{backendOffline ? 'OFFLINE' : lockedMode?.backend_status || 'ONLINE'}</strong>
      </div>
      <div>
        <span>Analysis</span>
        <strong className={tone(analysisState)}>{analysisState}</strong>
      </div>
    </section>
  )
}

function TradingViewLiveChart({ symbol = 'TVC:GOLD', timeframe = '5M', internalReady = false, compact = false }) {
  const containerRef = useRef(null)
  const [widgetError, setWidgetError] = useState('')
  const interval = TRADINGVIEW_INTERVALS[timeframe] || '5'

  useEffect(() => {
    const container = containerRef.current
    if (!container) return undefined
    setWidgetError('')
    container.innerHTML = ''

    const widgetHost = document.createElement('div')
    widgetHost.className = 'tradingview-widget-container__widget'
    widgetHost.style.height = '100%'
    widgetHost.style.width = '100%'

    const script = document.createElement('script')
    script.type = 'text/javascript'
    script.async = true
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol,
      interval,
      timezone: 'exchange',
      theme: 'dark',
      style: '1',
      locale: 'en',
      withdateranges: true,
      hide_side_toolbar: false,
      allow_symbol_change: true,
      save_image: true,
      calendar: false,
      support_host: 'https://www.tradingview.com',
      studies: [],
    })
    script.onerror = () => {
      setWidgetError('TradingView Live Chart failed to load. Check internet connection.')
    }

    container.appendChild(widgetHost)
    container.appendChild(script)
    return () => {
      container.innerHTML = ''
    }
  }, [symbol, interval])

  return (
    <section className={`tradingview-live-card ${compact ? 'compact' : ''}`}>
      <div className="tradingview-live-head">
        <div>
          <strong>TradingView Live Chart</strong>
          <span>{symbol} / {timeframeLabel(timeframe)} / visual reference only</span>
        </div>
        <b>{internalReady ? 'SH Engine Data Ready' : 'SH Internal Data Waiting'}</b>
      </div>
      <VisualReferenceNotice chartMode="tradingview" internalReady={internalReady} />
      {widgetError && <div className="terminal-alert bad">{widgetError}</div>}
      <div className="tradingview-widget-frame" ref={containerRef} />
    </section>
  )
}

function AnalysisResultDrawer({ open, onClose, analysis, lockedMode, dataIntegrity, explanation }) {
  const source = engineSourceLabel(lockedMode, dataIntegrity)
  const signal = safeObject(analysis?.signal)
  const note = source === 'TEST_HISTORY'
    ? 'Test Mode Analysis - not real market signal.'
    : source === 'REAL_HISTORY'
      ? 'Real Data Analysis.'
      : 'Analysis waiting for internal SH data.'
  const rows = [
    ['Data Mode', lockedMode?.data_mode_label || lockedMode?.locked_mode || source],
    ['Bias', analysis?.bias || signal.direction || '-'],
    ['Market State', analysis?.market_state || analysis?.structure?.market_state || analysis?.status || '-'],
    ['Liquidity', analysis?.liquidity || analysis?.liquidity_state || '-'],
    ['POI', analysis?.poi || analysis?.poi_state || signal.poi || '-'],
    ['Confirmation', analysis?.confirmation || analysis?.confirmation_state || signal.status || '-'],
    ['Score', signal.score ?? analysis?.score ?? '-'],
    ['Final Decision', analysis?.final_decision || signal.status || '-'],
  ]
  return (
    <aside className={`analysis-result-drawer ${open ? 'open' : ''}`}>
      <div className="analysis-result-panel">
        <header>
          <div>
            <strong>Analysis Result</strong>
            <span>{note}</span>
          </div>
          <button onClick={onClose}>X</button>
        </header>
        <div className="analysis-result-grid">
          {rows.map(([label, value]) => (
            <p key={label}>
              <span>{label}</span>
              <strong className={label === 'Final Decision' ? tone(value) : ''}>{safeText(value, '-')}</strong>
            </p>
          ))}
        </div>
        <section>
          <strong>Reason Explanation</strong>
          <p>{analysis?.reason || explanation?.summary || explanation?.explanation || analysis?.message || 'No analysis explanation is available yet.'}</p>
        </section>
      </div>
    </aside>
  )
}

function PriceMarker({ price, status }) {
  return (
    <div className={`price-marker ${tone(status)}`}>
      <span>{status || 'LIVE'}</span>
      <strong>{asPrice(price, '0.00')}</strong>
    </div>
  )
}

function CandleConfidenceChip({ confidence }) {
  const label = confidence || 'UNKNOWN'
  return <span className={`candle-confidence ${tone(label)}`}>{label}</span>
}

function CandleHealthBadge({ health }) {
  const status = health?.health_status || 'UNKNOWN'
  return (
    <span className={`candle-health-badge ${tone(status)}`}>
      {status.replaceAll('_', ' ')}
    </span>
  )
}

function CandleStatusSummary({ health, timeframe }) {
  if (!health) return null
  return (
    <div className="candle-status-summary">
      <strong>{timeframeLabel(timeframe)}</strong>
      <span>Completed: {health.completed_count ?? 0}</span>
      <span>Partial: {health.partial_count ?? 0}</span>
      <span>Health: {safeText(health.health_status, 'UNKNOWN')}</span>
      <CandleConfidenceChip confidence={Object.entries(safeObject(health.confidence_summary)).sort((a, b) => b[1] - a[1])?.[0]?.[0]} />
    </div>
  )
}

function LiveCandleInfoBar({ health, latestPrice, timeframe }) {
  if (!health) return null
  return (
    <div className="live-candle-info-bar">
      <CandleHealthBadge health={health} />
      <CandleStatusSummary health={health} timeframe={timeframe} />
      <span>Latest completed: {health.latest_completed_time ? new Date(health.latest_completed_time).toLocaleString() : '-'}</span>
      <strong>{asPrice(latestPrice)}</strong>
    </div>
  )
}

function WarmupNotice({ health, timeframe }) {
  if (!health || health.health_status === 'HEALTHY') return null
  const message = safeArray(health.warnings)[0] || `Not enough completed ${timeframeLabel(timeframe)} candles yet. Building chart history...`
  return (
    <div className="warmup-notice">
      <strong>{health.health_status?.replaceAll('_', ' ') || 'WARMING UP'}</strong>
      <span>{message}</span>
    </div>
  )
}

function HistoryAlignmentPanel({
  alignment,
  onImportHistory,
  onGenerateTestHistory,
  onLiveOnlyMode,
  onArchiveStale,
  onClearTestHistory,
  actionsDisabled,
}) {
  if (!alignment || !alignment.alignment_status || alignment.healthy) return null
  const status = alignment.alignment_status
  return (
    <div className={`history-alignment-panel ${tone(status)}`}>
      <div className="history-alignment-head">
        <strong>History Alignment: {status.replaceAll('_', ' ')}</strong>
        <span>{alignment.warning_message || 'History candles do not match current live price.'}</span>
      </div>
      <div className="history-alignment-grid">
        <span>Live Price <strong>{asPrice(alignment.latest_live_price ?? alignment.live_price)}</strong></span>
        <span>History Close <strong>{asPrice(alignment.latest_history_close)}</strong></span>
        <span>Gap <strong>{asPrice(alignment.price_gap)}</strong></span>
        <span>Gap % <strong>{alignment.price_gap_percent ?? '-'}</strong></span>
        <span>History Time <strong>{alignment.latest_history_time ? new Date(alignment.latest_history_time).toLocaleString() : '-'}</strong></span>
        <span>Live Time <strong>{alignment.latest_live_time ? new Date(alignment.latest_live_time).toLocaleString() : '-'}</strong></span>
        <span>Source <strong>{alignment.source_group || alignment.source || '-'}</strong></span>
        <span>Action <strong>{String(alignment.recommended_action || '-').replaceAll('_', ' ')}</strong></span>
      </div>
      <div className="history-alignment-actions">
        <label className={`file-action ${actionsDisabled ? 'disabled' : ''}`}>
          Import Recent History
          <input type="file" accept=".csv" onChange={onImportHistory} disabled={actionsDisabled} />
        </label>
        <button onClick={onGenerateTestHistory} disabled={actionsDisabled}>Generate Live-Anchored Test History</button>
        <button onClick={onLiveOnlyMode} disabled={actionsDisabled}>Live Only Mode</button>
        <button onClick={onArchiveStale} disabled={actionsDisabled}>Archive Misaligned History</button>
        <button onClick={onClearTestHistory} disabled={actionsDisabled}>Clear Test History</button>
      </div>
    </div>
  )
}

function HorizontalLevelTag({ label, price, color }) {
  return (
    <div className="level-tag" style={{ '--level-color': color }}>
      <span>{label}</span>
      <strong>{asPrice(price)}</strong>
    </div>
  )
}

function BackendOfflineOverlay({ visible }) {
  if (!visible) return null
  return (
    <div className="backend-offline-overlay">
      <strong>BACKEND OFFLINE</strong>
      <span>Last chart remains visible. Live status and analysis actions are disabled.</span>
    </div>
  )
}

function SmartAnalysisHud({ analysis, readiness, dataIntegrity, status, overlays, panels, dataMode, engineStatus }) {
  const locked = dataMode?.data_mode_lock || readiness?.data_mode_lock || dataMode || {}
  const bias = deriveBias(analysis, overlays, panels)
  const finalStatus = analysis?.final_decision || locked.analysis_state || readiness?.analysis_state || 'Waiting for Data'
  const score = analysis?.signal?.score ?? (readiness?.full_analysis_ready ? 75 : 0)
  const currentPrice = status?.latest_price || dataIntegrity?.latest_live_price || overlays?.chart_overlays?.price_line
  const keyLevel = overlays?.chart_overlays?.pivot_line || overlays?.chart_overlays?.ma_30
  return (
    <aside className="smart-hud">
      <div><span>Data Mode</span><strong className={tone(locked.locked_mode)}>{locked.data_mode_label || '-'}</strong></div>
      <div><span>Backend</span><strong className={tone(locked.backend_status)}>{locked.backend_status || '-'}</strong></div>
      <div><span>Provider</span><strong className={tone(locked.provider_status)}>{locked.provider_status || '-'}</strong></div>
      <div><span>Candle Source</span><strong>{locked.candle_source || '-'}</strong></div>
      <div><span>Analysis</span><strong className={tone(finalStatus)}>{finalStatus}</strong></div>
      <div><span>Engine</span><strong>{engineStatus?.engine_mode || '-'}</strong></div>
      <div><span>Bias</span><strong>{bias}</strong></div>
      <div><span>Score</span><strong>{score}</strong></div>
      <div><span>Key Level</span><strong>{asPrice(keyLevel)}</strong></div>
      <div><span>Update</span><strong>{status?.last_updated || readiness?.latest_candle_time || '-'}</strong></div>
      <div><span>Price</span><strong>{asPrice(currentPrice)}</strong></div>
    </aside>
  )
}

function SHAnalysisChart({
  chartData,
  overlays,
  overlayVisibility,
  dataIntegrity,
  latestPrice,
  providerStatus,
  readiness,
  dataMode,
  dataState,
  gapDiagnosis,
  engineStatus,
  analysis,
  panels,
  datasetKey,
  emptyMessage = NO_HISTORY_MESSAGE,
  onSeed,
  onSmartSetup,
  onFixGap,
  onOneClickWarmup,
  onImportHistory,
  onStartBuilder,
  onGenerateTestHistory,
  onClearTestHistory,
  onLiveOnlyMode,
  onArchiveStale,
  onToggleStale,
  showStaleHistory,
  onDebug,
  onRefresh,
  resetSignal,
  onResetScale,
  onTimeframeChange,
  onOpenOverlayMenu,
  onOpenDataHub,
  apiError,
  apiBaseUrl,
  health,
  backendOffline,
  actionsDisabled,
}) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const historySeriesRef = useRef(null)
  const liveSeriesRef = useRef(null)
  const maSeriesRef = useRef(null)
  const priceLinesRef = useRef([])
  const currentPriceLineRef = useRef(null)
  const savedRangeRef = useRef(null)
  const restoringRangeRef = useRef(false)
  const lastDatasetKeyRef = useRef(null)
  const [gapLeft, setGapLeft] = useState(null)
  const [chartError, setChartError] = useState('')

  const gapDetected = Boolean(dataIntegrity?.gap_detected)
  const segments = safeObject(chartData?.segments)
  const activeCandles = safeArray(segments.active)
  const staleCandles = safeArray(segments.stale)
  const historyCandles = showStaleHistory
    ? (staleCandles.length ? staleCandles : safeArray(segments.history))
    : safeArray(segments.history)
  const liveCandles = safeArray(segments.live)
  const mergedCandles = safeArray(chartData?.candles)
  const staleHidden = Boolean(chartData?.archived_stale_history_hidden || dataState?.data_state === 'READY_WITH_GAP_WARNING')
  const candleHealth = safeObject(chartData?.candle_health)
  const alignment = safeObject(chartData?.alignment || dataIntegrity?.alignment || candleHealth?.alignment)
  const alignmentStatus = chartData?.alignment_status || alignment.alignment_status || candleHealth?.health_status
  const alignmentHealthy = Boolean(alignment.healthy || alignmentStatus === 'ALIGNED')
  const isRealHistoryChart = Boolean(dataIntegrity?.real_recent_history_present || dataIntegrity?.twelve_data_history_present || dataIntegrity?.real_csv_history_present)
  const alignedRealHistoryChart = isRealHistoryChart && alignmentHealthy
  const rawGapDetected = Boolean(
    dataIntegrity?.raw_gap_detected ||
    chartData?.gap_diagnosis?.status === 'STALE_HISTORY' ||
    Number(dataIntegrity?.price_gap_percent) > 0.15 ||
    ['WARNING_PRICE_GAP', 'PRICE_GAP', 'CRITICAL_PRICE_GAP', 'PRICE_AND_TIME_GAP', 'TIME_GAP', 'STALE_HISTORY', 'FUTURE_HISTORY'].includes(alignmentStatus)
  )
  const chartGapDetected = !alignedRealHistoryChart && (gapDetected || (rawGapDetected && !showStaleHistory))
  const preferredCandles = activeCandles.length >= 80
    ? activeCandles
    : mergedCandles.length >= 80
      ? mergedCandles
      : (liveCandles.length ? liveCandles : activeCandles)
  const baseDisplayCandles = activeCandles.length ? activeCandles : mergedCandles
  const rawDisplayCandles = chartGapDetected
    ? latestContinuousCandles(liveCandles.length ? liveCandles : preferredCandles, datasetKey)
    : alignedRealHistoryChart
      ? baseDisplayCandles
      : latestContinuousCandles(baseDisplayCandles, datasetKey)
  const displayCandles = rawDisplayCandles.filter(candle => (
    Number.isFinite(Number(candle?.time)) &&
    Number.isFinite(Number(candle?.open)) &&
    Number.isFinite(Number(candle?.high)) &&
    Number.isFinite(Number(candle?.low)) &&
    Number.isFinite(Number(candle?.close)) &&
    Number(candle.high) >= Math.max(Number(candle.open), Number(candle.close), Number(candle.low)) &&
    Number(candle.low) <= Math.min(Number(candle.open), Number(candle.close), Number(candle.high))
  ))
  const showMovingAverage = displayCandles.length >= 30 && !hasLargeTimeGap(displayCandles, datasetKey)
  const overlayItems = safeObject(overlays?.overlays)
  const signalDirection = safeText(analysis?.signal?.direction, 'WAIT').toUpperCase()
  const signalScore = Number(analysis?.signal?.score ?? 0)
  const signalStatus = safeText(analysis?.signal?.status || analysis?.final_decision, '')
  const showSetupLevels = (signalDirection === 'BUY' || signalDirection === 'SELL') && signalScore >= 60 && /Valid|High Quality/i.test(signalStatus)
  const activeTags = showSetupLevels ? OverlayCollisionManager.manage(overlayItems, overlayVisibility).slice(0, 4) : []
  const chartSourceLabel = alignmentStatus && !alignmentHealthy && alignmentStatus !== 'TEST_MODE'
    ? alignmentStatus.replaceAll('_', ' ')
    : dataIntegrity?.real_recent_history_present || dataIntegrity?.twelve_data_history_present || dataIntegrity?.real_csv_history_present
      ? 'Real candle chart'
    : dataIntegrity?.test_data_present
      ? 'Test candle chart'
      : 'Live candle chart'

  function focusLiveSegment() {
    const chart = chartRef.current
    if (!chart) return
    const active = displayCandles
    if (!active.length) {
      chart.timeScale().fitContent()
      return
    }
    const candleCount = active.length
    const windowSize = candleCount <= 10
      ? Math.max(12, candleCount + 6)
      : candleCount < 40
        ? Math.max(36, candleCount + 10)
        : candleCount < 100
          ? 90
          : 190
    restoringRangeRef.current = true
    chart.timeScale().setVisibleLogicalRange({
      from: Math.max(-2, candleCount - windowSize),
      to: candleCount <= 10 ? candleCount + 4 : candleCount + 18,
    })
    requestAnimationFrame(() => {
      restoringRangeRef.current = false
    })
  }

  function restoreSavedRange() {
    const chart = chartRef.current
    const range = savedRangeRef.current
    if (!chart || !Number.isFinite(Number(range?.from)) || !Number.isFinite(Number(range?.to))) return false
    try {
      restoringRangeRef.current = true
      chart.timeScale().setVisibleLogicalRange(range)
      requestAnimationFrame(() => {
        restoringRangeRef.current = false
      })
      return true
    } catch (_) {
      savedRangeRef.current = null
      restoringRangeRef.current = false
      return false
    }
  }

  function updateGapMarker() {
    const marker = chartData?.gap_marker
    const chart = chartRef.current
    if (!marker || !chart || !containerRef.current) {
      setGapLeft(null)
      return
    }
    const coordinate = chart.timeScale().timeToCoordinate(marker.time)
    const width = containerRef.current.clientWidth
    if (coordinate === null || coordinate < 0 || coordinate > width) {
      setGapLeft(null)
      return
    }
    setGapLeft(coordinate)
  }

  useEffect(() => {
    if (!containerRef.current || chartRef.current) return undefined
    let chart
    try {
      chart = createChart(containerRef.current, {
        autoSize: true,
        layout: { background: { color: '#030507' }, textColor: '#8f98a7', fontFamily: 'Inter, ui-sans-serif, system-ui' },
        grid: {
          vertLines: { color: 'rgba(148, 163, 184, 0.10)' },
          horzLines: { color: 'rgba(148, 163, 184, 0.10)' },
        },
        rightPriceScale: {
          borderColor: 'rgba(148, 163, 184, 0.16)',
          entireTextOnly: true,
          scaleMargins: { top: 0.08, bottom: 0.12 },
        },
        timeScale: {
          borderColor: 'rgba(148, 163, 184, 0.16)',
          timeVisible: true,
          secondsVisible: false,
          fixLeftEdge: false,
          fixRightEdge: false,
          rightOffset: 10,
          barSpacing: 8,
          minBarSpacing: 3,
        },
        crosshair: {
          mode: 0,
          vertLine: { color: 'rgba(203, 213, 225, .58)', width: 1, style: LINE_STYLE.dashed, labelBackgroundColor: '#111827' },
          horzLine: { color: 'rgba(203, 213, 225, .58)', width: 1, style: LINE_STYLE.dashed, labelBackgroundColor: '#111827' },
        },
      })
      const historySeries = chart.addSeries(CandlestickSeries, {
        upColor: '#00d26a',
        downColor: '#ff4655',
        borderUpColor: '#00d26a',
        borderDownColor: '#ff4655',
        wickUpColor: '#33f28f',
        wickDownColor: '#ff6b78',
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      })
      const liveSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#00e676',
        downColor: '#ff4154',
        borderUpColor: '#00e676',
        borderDownColor: '#ff4154',
        wickUpColor: '#66ffa7',
        wickDownColor: '#ff7a86',
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      })
      const maSeries = chart.addSeries(LineSeries, {
        color: '#d6b72f',
        lineWidth: 2,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      })
      chartRef.current = chart
      historySeriesRef.current = historySeries
      liveSeriesRef.current = liveSeries
      maSeriesRef.current = maSeries
      chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (!range || restoringRangeRef.current) return
        savedRangeRef.current = range
      })
      setChartError('')
    } catch (err) {
      setChartError(err.message || 'Lightweight chart initialization failed.')
    }
    return () => {
      try {
        chart?.remove()
      } catch (_) {
        // Chart cleanup must never crash the app.
      }
      chartRef.current = null
      historySeriesRef.current = null
      liveSeriesRef.current = null
      maSeriesRef.current = null
      currentPriceLineRef.current = null
    }
  }, [])

  useEffect(() => {
    const historySeries = historySeriesRef.current
    const liveSeries = liveSeriesRef.current
    const maSeries = maSeriesRef.current
    if (!historySeries || !liveSeries || !maSeries) return
    try {
      if (chartGapDetected) {
        historySeries.setData(showStaleHistory ? historyCandles : [])
        liveSeries.setData(displayCandles)
      } else {
        historySeries.setData(displayCandles)
        liveSeries.setData([])
      }
      maSeries.setData(showMovingAverage ? movingAverageData(displayCandles, 30) : [])
    } catch (err) {
      setChartError(err.message || 'Chart data update failed.')
      return
    }
    requestAnimationFrame(() => {
      const datasetChanged = lastDatasetKeyRef.current !== datasetKey
      if (datasetChanged) {
        savedRangeRef.current = null
        lastDatasetKeyRef.current = datasetKey
        focusLiveSegment()
      } else if (!restoreSavedRange()) {
        focusLiveSegment()
      }
      updateGapMarker()
    })
  }, [datasetKey, chartGapDetected, historyCandles, liveCandles, activeCandles, displayCandles, showStaleHistory, showMovingAverage])

  useEffect(() => {
    const historySeries = historySeriesRef.current
    const liveSeries = liveSeriesRef.current
    if (!historySeries || !liveSeries) return
    priceLinesRef.current.forEach(({ series, line }) => {
      try {
        series.removePriceLine(line)
      } catch (_) {
        // Ignore stale price lines after chart resets.
      }
    })
    priceLinesRef.current = []
    const targetSeries = chartGapDetected ? liveSeries : historySeries
    if (currentPriceLineRef.current) {
      try {
        currentPriceLineRef.current.series.removePriceLine(currentPriceLineRef.current.line)
      } catch (_) {
        // Ignore stale current price line.
      }
      currentPriceLineRef.current = null
    }
    const lastCandle = displayCandles[displayCandles.length - 1]
    const currentPrice = Number(latestPrice || lastCandle?.close)
    if (Number.isFinite(currentPrice)) {
      try {
        const line = targetSeries.createPriceLine({
          price: currentPrice,
          color: '#ff4154',
          lineWidth: 1,
          lineStyle: LINE_STYLE.dotted,
          axisLabelVisible: true,
          title: asPrice(currentPrice),
        })
        currentPriceLineRef.current = { series: targetSeries, line }
      } catch (err) {
        setChartError(err.message || 'Current price line update failed.')
      }
    }
    if (!showSetupLevels) return
    Object.entries(safeObject(overlayItems)).forEach(([key, item]) => {
      const price = Number(item?.price)
      if (key === 'price_line') return
      if (!['entry_zone_low', 'entry_zone_high', 'invalidation', 'target_1', 'target_2', 'target_3'].includes(key)) return
      if (!item?.ready || !Number.isFinite(price) || overlayVisibility[key] === false) return
      try {
        const line = targetSeries.createPriceLine({
          price,
          color: item.color || '#94a3b8',
          lineWidth: key === 'price_line' ? 2 : 1,
          lineStyle: LINE_STYLE[item.style] ?? 0,
          axisLabelVisible: true,
          title: item.label || key,
        })
        priceLinesRef.current.push({ series: targetSeries, line })
      } catch (err) {
        setChartError(err.message || 'Chart overlay update failed.')
      }
    })
  }, [overlayItems, overlayVisibility, chartGapDetected, liveCandles.length, activeCandles.length, displayCandles, latestPrice, showSetupLevels])

  useEffect(() => {
    savedRangeRef.current = null
    focusLiveSegment()
    updateGapMarker()
  }, [resetSignal])

  useEffect(() => {
    updateGapMarker()
  }, [chartData?.gap_marker])

  return (
    <div className="chart-wrap">
      <div className="chart-headline">
        <div className="chart-timeframes">
          {TOOLBAR_TIMEFRAMES.map(item => (
            <button
              key={item}
              className={datasetKey === item ? 'active' : ''}
              onClick={() => onTimeframeChange?.(item)}
            >
              {timeframeLabel(item)}
            </button>
          ))}
        </div>
        <div className="chart-head-actions">
          <span className={`chart-live-badge ${dataIntegrity?.test_data_present ? 'test' : 'live'}`}>
            <i />
            {chartSourceLabel}
          </span>
          <CandleHealthBadge health={candleHealth} />
          {Number.isFinite(Number(latestPrice)) && <PriceMarker price={latestPrice} status={backendOffline ? 'STALE' : providerStatus?.status || 'LIVE'} />}
        </div>
      </div>

      <div className="tv-chart-shell">
        <LiveCandleInfoBar health={candleHealth} latestPrice={latestPrice} timeframe={datasetKey} />
        <WarmupNotice health={candleHealth} timeframe={datasetKey} />
        <HistoryAlignmentPanel
          alignment={alignment}
          onImportHistory={onImportHistory}
          onGenerateTestHistory={onGenerateTestHistory}
          onLiveOnlyMode={onLiveOnlyMode}
          onArchiveStale={onArchiveStale}
          onClearTestHistory={onClearTestHistory}
          actionsDisabled={actionsDisabled}
        />
        <BackendOfflineOverlay visible={backendOffline} />
        {(!displayCandles.length || chartError) && (
          <div className="chart-empty">
            <div className="chart-empty-panel">
              <strong>{backendOffline ? 'Live chart paused' : chartError ? 'Chart Render Error' : 'No XAUUSD candle data available'}</strong>
              <p>{backendOffline ? 'Backend is offline. Start the server to load live candles again.' : emptyMessage || 'Choose one option to load data.'}</p>
              {chartError && <small>{chartError}</small>}
              {!backendOffline && <small>Current API error: {apiError?.message || '-'}</small>}
              {!backendOffline && <small>API Base URL: {apiBaseUrl}</small>}
              {!backendOffline && <small>Backend Health: {health?.status || 'Offline'}</small>}
            </div>
            <div className="chart-empty-actions">
              <button onClick={onSmartSetup} disabled={actionsDisabled}>Smart Setup</button>
              <button onClick={onGenerateTestHistory} disabled={actionsDisabled}>Generate Test History</button>
              <button onClick={onDebug}>Debug Data</button>
              <button onClick={onRefresh} disabled={actionsDisabled}>Refresh Data</button>
            </div>
          </div>
        )}
        {(gapDetected || (alignmentStatus && !alignmentHealthy && alignmentStatus !== 'TEST_MODE')) && (
          <div className="gap-banner">
            <strong>{alignmentStatus?.replaceAll('_', ' ') || gapDiagnosis?.status || 'History gap detected'}</strong>
            <span>{alignment.warning_message || chartData?.warning_message || gapDiagnosis?.message || dataIntegrity?.gap_warning || GAP_MESSAGE}</span>
          </div>
        )}
        {!alignedRealHistoryChart && chartGapDetected && displayCandles.length > 0 && displayCandles.length < 40 && (
          <div className="chart-data-note">
            <strong>{displayCandles.length} fresh {timeframeLabel(datasetKey)} candles</strong>
            <span>Import real recent history or keep live builder running for a full chart.</span>
          </div>
        )}
        <div ref={containerRef} className="tv-chart" />
        {displayCandles.length > 0 && <div className="chart-watermark">XAUUSD</div>}
        {gapDetected && showStaleHistory && gapLeft !== null && (
          <div className="history-gap-line" style={{ left: `${gapLeft}px` }}>
            <span>{chartData?.gap_marker?.label || 'History Gap'}</span>
          </div>
        )}
        {analysis?.signal && showSetupLevels && (
          <SmartAnalysisHud
            analysis={analysis}
            readiness={readiness}
            dataIntegrity={dataIntegrity}
            status={providerStatus}
            overlays={overlays}
            panels={panels}
            dataMode={dataMode}
            engineStatus={engineStatus}
          />
        )}
        <div className="level-tag-stack">
          {safeArray(activeTags).map(item => (
            <HorizontalLevelTag key={item.key} label={item.label || item.key} price={item.price} color={item.color || '#94a3b8'} />
          ))}
        </div>
      </div>
    </div>
  )
}

function HistogramPanel({ title, data = [], mode = 'pressure' }) {
  const items = safeArray(data)
  const values = items.map(item => Number(item?.value)).filter(Number.isFinite)
  const maxAbs = Math.max(...values.map(Math.abs), 1)
  const top = mode === 'bearishness' ? 0 : maxAbs
  const bottom = -maxAbs
  return (
    <section className="indicator-panel">
      <div className="indicator-title">
        <strong>{title}</strong>
        <span>{mode === 'bearishness' ? 'blue pressure' : 'green / red flow'}</span>
      </div>
      <div className="histogram-body">
        <div className="histogram-bars">
          <span className="zero-line" />
          {items.slice(-64).map((item, idx) => {
            const value = Number(item?.value) || 0
            const height = Math.max(8, Math.min(50, Math.abs(value) / maxAbs * 48))
            const positive = value >= 0
            const color = mode === 'bearishness' ? '#2f80ed' : item.color === 'red' ? '#ff5630' : '#22c55e'
            return (
              <i
                key={`${item?.time || 'bar'}-${idx}`}
                className={positive ? 'up' : 'down'}
                style={{ '--bar-height': `${height}%`, '--bar-color': color }}
              />
            )
          })}
        </div>
        <div className="axis-values">
          <span>{Math.round(top)}</span>
          <span>0</span>
          <span>{Math.round(bottom)}</span>
        </div>
      </div>
    </section>
  )
}

function IndicatorPanel({ panels, dataIntegrity }) {
  const panelData = safeObject(panels?.indicator_panels)
  const pressure = safeObject(panelData.market_pressure_score)
  const modeLabel = panels?.data_mode_lock?.data_mode_label
  const waiting = panels?.status === 'WAITING_FOR_HISTORY' || (!safeArray(panelData.boys_selling).length && !safeArray(panelData.bearishness).length && !safeArray(panelData.market_pressure).length)
  const fixGap = panels?.status === 'FIX_GAP_REQUIRED'
  return (
    <div className="indicator-stack">
      {fixGap ? (
        <section className="indicator-waiting">
          <strong>Fix gap required</strong>
          <span>Use Fix Gap Now to choose TEST, REAL CSV, or LIVE ONLY.</span>
        </section>
      ) : waiting ? (
        <section className="indicator-waiting">
          <strong>Waiting for candle history</strong>
          <span>{dataIntegrity?.test_data_present ? 'TEST DATA' : 'Recent 5M/15M candles are required.'}</span>
        </section>
      ) : (
        <>
          {panels?.badge && <div className="test-data-badge">{panels.badge}</div>}
          {modeLabel && <div className="test-data-badge">{modeLabel}</div>}
          <HistogramPanel title="Market Pressure" data={panelData.market_pressure || panelData.boys_selling || []} />
          <HistogramPanel title="Liquidity Pressure" mode="bearishness" data={panelData.liquidity_pressure || panelData.balance || panelData.bearishness || []} />
          <HistogramPanel title="Setup Quality" data={panelData.setup_quality || []} />
        </>
      )}
      <section className="market-pressure-panel">
        <div><span>Bullish</span><strong>{asPrice(pressure.bullish, '0')}%</strong></div>
        <div><span>Bearish</span><strong>{asPrice(pressure.bearish, '0')}%</strong></div>
        <div><span>Neutral</span><strong>{asPrice(pressure.neutral, '0')}%</strong></div>
      </section>
    </div>
  )
}

function DataStatusCards({ readiness, dataIntegrity, provider, overlayStatus, chartData, dataMode }) {
  const locked = dataMode?.data_mode_lock || readiness?.data_mode_lock || dataMode || {}
  const sourceSummary = locked.candle_source || chartData?.source_labels?.summary || dataIntegrity?.source_labels?.summary || '-'
  const readyOverlays = overlayStatus?.ready_count ?? chartData?.overlay_status?.ready_count ?? 0
  const waitingOverlays = overlayStatus?.waiting_count ?? chartData?.overlay_status?.waiting_count ?? 0
  return (
    <section className="data-status-cards">
      <div><span>Data Mode</span><strong className={tone(locked.locked_mode)}>{locked.data_mode_label || '-'}</strong></div>
      <div><span>Candle Source</span><strong>{sourceSummary}</strong></div>
      <div><span>Backend</span><strong className={tone(locked.backend_status)}>{locked.backend_status || '-'}</strong></div>
      <div><span>Provider</span><strong className={tone(locked.provider_status)}>{locked.provider_status || provider?.status || '-'}</strong></div>
      <div><span>Analysis</span><strong className={locked.analysis_ready ? 'good' : 'warn'}>{locked.analysis_state || '-'}</strong></div>
      <div><span>Overlay Readiness</span><strong>{readyOverlays} ready / {waitingOverlays} waiting</strong></div>
    </section>
  )
}

function AnalysisStatusChips({ overlays, panels, analysis, readiness, provider, dataIntegrity, dataMode }) {
  const locked = dataMode?.data_mode_lock || readiness?.data_mode_lock || dataMode || {}
  const status = analysis?.final_decision || locked.analysis_state || readiness?.analysis_state || 'Waiting for Data'
  const score = analysis?.signal?.score ?? (readiness?.full_analysis_ready ? 75 : 0)
  const bias = deriveBias(analysis, overlays, panels)
  const keyLevel = overlays?.chart_overlays?.pivot_line
  return (
    <section className="status-chips">
      <div><span>Bias</span><strong>{bias}</strong></div>
      <div><span>Status</span><strong className={tone(status)}>{status}</strong></div>
      <div><span>Current Price</span><strong>{asPrice(provider?.latest_price || dataIntegrity?.latest_live_price || overlays?.chart_overlays?.price_line)}</strong></div>
      <div><span>Key Level</span><strong>{asPrice(keyLevel)}</strong></div>
      <div><span>Signal Score</span><strong>{score}</strong></div>
      <div><span>Data</span><strong className={tone(locked.locked_mode)}>{locked.data_mode_label || dataIntegrity?.status || '-'}</strong></div>
    </section>
  )
}

function ConfidenceMeter({ value }) {
  const percent = clampPercent(value)
  const activeBars = Math.ceil(percent / 20)
  return (
    <span className="confidence-meter" aria-label={`Confidence ${percent}%`}>
      {Array.from({ length: 5 }).map((_, index) => (
        <i
          key={index}
          className={index < activeBars ? 'active' : ''}
          style={{ '--bar-index': index + 1 }}
        />
      ))}
      <strong>{percent}%</strong>
    </span>
  )
}

function SignalDeskCard({ card }) {
  return (
    <article className={`signal-desk-card ${card.tone}`}>
      <header>
        <div className="signal-asset-mark" aria-hidden="true">
          <span />
        </div>
        <div className="signal-title">
          <strong>{card.symbol}</strong>
          <span>{card.assetLabel} · {card.timeframe}</span>
        </div>
        <em>{card.horizon}</em>
      </header>

      <div className="signal-action-row">
        <span className={`signal-direction ${card.tone}`}>
          <i />
          {card.directionLabel}
        </span>
        {card.setupBadge && <b>{card.setupBadge}</b>}
      </div>

      <dl>
        <div>
          <dt>Entry</dt>
          <dd>{asPrice(card.entry)}</dd>
        </div>
        <div>
          <dt>Target</dt>
          <dd className="good">{asPrice(card.target)}</dd>
        </div>
        <div>
          <dt>Stop</dt>
          <dd className="bad">{asPrice(card.stop)}</dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd><ConfidenceMeter value={card.confidence} /></dd>
        </div>
        <div>
          <dt>State</dt>
          <dd className="muted">{card.state}</dd>
        </div>
      </dl>

      <footer>
        {card.tags.map(tag => <span key={tag}>{tag}</span>)}
      </footer>
    </article>
  )
}

function SignalDesk({ analysis, provider, dataIntegrity, timeframe, dataMode, readiness, backendOffline }) {
  if (backendOffline && !analysis?.signal) return null
  const signal = safeObject(analysis?.signal)
  const locked = dataMode?.data_mode_lock || readiness?.data_mode_lock || dataMode || {}
  const symbol = analysis?.symbol || signal.pair || 'XAUUSD'
  const direction = safeText(signal.direction, 'WAIT').toUpperCase()
  const isBuy = direction === 'BUY'
  const isSell = direction === 'SELL'
  const toneClass = isBuy ? 'buy' : isSell ? 'sell' : 'wait'
  const entryZone = safeObject(signal.entry_zone)
  const livePrice = provider?.latest_price || dataIntegrity?.latest_live_price
  const targetLevels = safeArray(signal.target_levels)
  const status = signal.status || analysis?.final_decision || locked.analysis_state || 'Waiting for Data'
  const setupType = signal.setup_type && signal.setup_type !== 'None' ? signal.setup_type : ''
  const modeTag = locked.data_mode_label || readiness?.data_mode_label || dataIntegrity?.status || 'AUTO'
  const card = {
    symbol,
    assetLabel: symbol.includes('BTC') ? 'Crypto' : 'Gold',
    timeframe,
    horizon: ['1D', '4H'].includes(timeframe) ? 'SWING' : 'INTRADAY',
    tone: toneClass,
    directionLabel: isBuy || isSell ? direction : 'WAIT',
    setupBadge: setupType ? 'DESK' : '',
    entry: midpoint(entryZone.low, entryZone.high, livePrice),
    target: targetLevels[0] || signal.liquidity_target,
    stop: signal.invalidation_level,
    confidence: signal.score ?? analysis?.score_engine?.score ?? 0,
    state: signal.confirmation_status || status,
    tags: [
      signal.market_state || status,
      setupType || 'Auto (AI picks best)',
      modeTag,
    ].filter(Boolean).slice(0, 3),
  }

  return (
    <section className="signal-desk">
      <div className="signal-desk-heading">
        <div>
          <span>Signal Desk</span>
          <strong>{status}</strong>
        </div>
        <p>{signal.final_action || analysis?.analysis_explanation?.reason || 'Run Analyze to refresh the latest setup.'}</p>
      </div>
      <div className="signal-desk-grid">
        <SignalDeskCard card={card} />
      </div>
    </section>
  )
}

function SmartExplanationCard({ explanation, analysis }) {
  const payload = explanation?.analysis_explanation || explanation || analysis?.analysis_explanation
  if (!payload?.summary) return null
  return (
    <section className="smart-explanation-card">
      <header>
        <strong>Smart Analysis Explanation</strong>
        <span>{payload.direction || analysis?.signal?.direction || 'WAIT'}</span>
      </header>
      <p>{payload.summary}</p>
      <div>
        <span>Next Trigger <strong>{payload.next_trigger || '-'}</strong></span>
        <span>Invalidation <strong>{payload.invalidation_condition || '-'}</strong></span>
        <span>Confidence <strong>{payload.confidence ?? 0}</strong></span>
      </div>
      {payload.data_mode_warning && <em>{payload.data_mode_warning}</em>}
    </section>
  )
}

function WorkflowPanel({ analysis, dataIntegrity }) {
  const rows = safeArray(analysis?.institutional_workflow || analysis?.workflow)
  if (!rows.length && !dataIntegrity) return null
  const fallbackRows = dataIntegrity ? [{
    name: 'Data Integrity',
    status: dataIntegrity.status,
    confidence: dataIntegrity.gap_detected ? 35 : 100,
    timeframe: 'All',
    reason: dataIntegrity.gap_reason || dataIntegrity.warnings?.[0] || 'Candle quality checked.',
  }] : []
  return (
    <section className="workflow-panel">
      <header>
        <strong>Institutional Workflow</strong>
        <span>Data Integrity to Final Decision</span>
      </header>
      {safeArray(rows.length ? rows : fallbackRows).map((row, index) => (
        <div className="workflow-row" key={`${row.name}-${index}`}>
          <strong>{row.name}</strong>
          <span className={tone(row.status)}>{row.status}</span>
          <em>{row.timeframe}</em>
          <p>{row.reason}</p>
          <b>{row.confidence ?? 0}</b>
        </div>
      ))}
    </section>
  )
}

function DebugDataPanel({ debugData, routes, apiBaseUrl, health, apiError, dataState, gapDiagnosis, debugPing, open, onToggle, onDebugPing, onClearLocalStorage }) {
  if (!debugData && !routes?.length && !apiError) return null
  const debugAlignment = safeObject(debugData?.chart_data?.alignment || debugData?.chart_data?.data_integrity?.alignment || debugPing?.chartData?.alignment)
  return (
    <section className="debug-panel">
      <header>
        <strong>Debug Data</strong>
        <span>{apiError?.code || health?.status || 'OK'}</span>
        <div>
          <button onClick={onDebugPing}>Ping</button>
          <button onClick={onClearLocalStorage}>Clear Storage</button>
          <button onClick={onToggle}>{open ? 'Hide' : 'Show'}</button>
        </div>
      </header>
      {open && (
      <>
      <div className="debug-grid">
        <p><span>Backend Connected</span><strong>{health?.status === 'OK' || debugData?.backend_connected ? 'Yes' : 'No'}</strong></p>
        <p><span>API Base URL</span><strong>{apiBaseUrl}</strong></p>
        <p><span>Database Path</span><strong>{debugData?.database_path || '-'}</strong></p>
        <p><span>Database Exists</span><strong>{debugData?.database_exists ? 'Yes' : 'No'}</strong></p>
        <p><span>Candle Tables</span><strong>{debugData?.setup_checklist?.candle_tables_created ? 'Ready' : '-'}</strong></p>
        <p><span>History Folder</span><strong>{debugData?.history_folder_exists ? 'Found' : 'Missing'}</strong></p>
        <p><span>Provider</span><strong>{debugData?.provider_name || '-'}</strong></p>
        <p><span>Provider Status</span><strong>{debugData?.provider_status?.status || '-'}</strong></p>
        <p><span>Data State</span><strong>{dataState?.data_state || debugData?.data_state?.data_state || '-'}</strong></p>
        <p><span>Gap Diagnosis</span><strong>{gapDiagnosis?.status || debugData?.gap_diagnosis?.status || debugData?.data_mode?.gap_diagnosis?.status || '-'}</strong></p>
        <p><span>Alignment</span><strong className={tone(debugAlignment.alignment_status)}>{debugAlignment.alignment_status || '-'}</strong></p>
        <p><span>Latest Price</span><strong>{asPrice(debugAlignment.latest_live_price || debugData?.latest_price)}</strong></p>
        <p><span>History Close</span><strong>{asPrice(debugAlignment.latest_history_close || gapDiagnosis?.latest_history_close || debugData?.gap_diagnosis?.latest_history_close)}</strong></p>
        <p><span>Price Gap</span><strong>{asPrice(debugAlignment.price_gap)}</strong></p>
        <p><span>Analysis Allowed</span><strong>{debugAlignment.analysis_allowed === false ? 'No' : debugAlignment.analysis_allowed === true ? 'Yes' : '-'}</strong></p>
        <p><span>Active Source</span><strong>{debugAlignment.source_group || gapDiagnosis?.latest_history_source || '-'}</strong></p>
        <p><span>Last Error</span><strong>{debugData?.last_error || apiError?.message || '-'}</strong></p>
        <p><span>Current Route</span><strong>{window.location.href}</strong></p>
        <p><span>Local Data Mode</span><strong>{safeText(safeStorageGet('sh_gold_data_mode'))}</strong></p>
        <p><span>App Version</span><strong>{APP_VERSION}</strong></p>
      </div>
      <div className="debug-counts">
        {['1M', '5M', '15M', '1H', '4H', '1D'].map(tf => (
          <span key={tf}>{tf}: <strong>{debugData?.candle_counts?.[tf] || 0}</strong></span>
        ))}
      </div>
      {apiError?.code === 'ROUTE_NOT_FOUND' && (
        <div className="route-list">
          <strong>Available API Routes</strong>
          {safeArray(routes || debugData?.available_routes).slice(0, 40).map(route => (
            <span key={`${route.methods?.join(',')}-${route.path}`}>{route.methods?.join(',')} {route.path}</span>
          ))}
        </div>
      )}
      {debugPing && (
        <pre className="debug-json">{JSON.stringify(debugPing, null, 2)}</pre>
      )}
      </>
      )}
    </section>
  )
}

function OverlayMenuDrawer({ open, onClose, overlays = {}, visibility = {}, onToggle }) {
  const groups = ['Core', 'Liquidity', 'Session', 'Setup', 'Moving Average', 'Debug']
  const grouped = Object.entries(safeObject(overlays)).reduce((acc, [key, item]) => {
    const group = item.group || 'Debug'
    acc[group] = acc[group] || []
    acc[group].push([key, item])
    return acc
  }, {})
  return (
    <aside className={`overlay-drawer ${open ? 'open' : ''}`}>
      <div className="overlay-panel">
        <header>
          <strong>Overlays</strong>
          <button onClick={onClose}>X</button>
        </header>
        {groups.filter(group => safeArray(grouped[group]).length).map(group => (
          <section className="overlay-group" key={group}>
            <h3>{group}</h3>
            {safeArray(grouped[group]).map(([key, item]) => {
              const active = visibility[key] !== false && item.ready
              return (
                <button key={key} className={active ? 'active' : ''} onClick={() => item.ready && onToggle(key)} disabled={!item.ready}>
                  <i style={{ '--overlay-color': item.color || '#94a3b8' }} />
                  <span>{item.label}</span>
                  <em>{item.ready ? 'Ready' : 'Waiting for Data'}</em>
                  <strong>{item.ready ? asPrice(item.price) : item.reason}</strong>
                  <b>{active ? 'ON' : 'OFF'}</b>
                </button>
              )
            })}
          </section>
        ))}
      </div>
    </aside>
  )
}

function FixGapModal({ open, onClose, diagnosis, onGenerateTest, onImportReal, onLiveOnly }) {
  if (!open) return null
  return (
    <aside className="fix-gap-modal">
      <div className="fix-gap-panel">
        <header>
          <div>
            <strong>Fix Gap Now</strong>
            <span>{diagnosis?.status || 'GAP WARNING'}</span>
          </div>
          <button onClick={onClose}>X</button>
        </header>
        <p>{diagnosis?.message || 'Choose how to recover the XAUUSD chart data.'}</p>
        <div className="fix-gap-stats">
          <span>Live <strong>{asPrice(diagnosis?.live_price)}</strong></span>
          <span>History <strong>{asPrice(diagnosis?.latest_history_close)}</strong></span>
          <span>Gap <strong>{diagnosis?.price_gap_percent ?? '-'}%</strong></span>
        </div>
        <div className="fix-gap-options">
          <button onClick={onGenerateTest}>
            <strong>Generate Live-Anchored Test History</strong>
            <span>Development and UI testing only. Shows TEST DATA.</span>
          </button>
          <label>
            <strong>Import Real Recent History</strong>
            <span>Upload real XAUUSD CSV. Enables real analysis when enough candles exist.</span>
            <input type="file" accept=".csv" onChange={onImportReal} />
          </label>
          <button onClick={onLiveOnly}>
            <strong>Live-Only Mode</strong>
            <span>Use current live price and building candles. Full analysis disabled.</span>
          </button>
        </div>
      </div>
    </aside>
  )
}

function DataHubDrawer({
  open = false,
  onClose = () => {},
  dataHub = null,
  wizard = null,
  counts = {},
  onImportReal = () => {},
  onGenerateTest = () => {},
  onClearTest = () => {},
  onLiveOnly = () => {},
  onFixGap = () => {},
  onSmartSetup = () => {},
  onRealModeWizard = () => {},
  onDebug = () => {},
  onExport = () => {},
  onReset = () => {},
  onWizard = () => {},
  actionsDisabled = false,
}) {
  const hubCounts = safeObject(dataHub?.candle_counts_by_timeframe || counts)
  const readiness = safeObject(dataHub?.analysis_readiness)
  return (
    <aside className={`mobile-drawer data-hub-drawer ${open ? 'open' : ''}`}>
      <div className="drawer-panel data-hub-panel">
        <div className="drawer-head">
          <strong>Real Data Hub</strong>
          <button onClick={onClose}>X</button>
        </div>
        <section className="data-hub-grid">
          <p><span>Data Mode</span><strong className={tone(dataHub?.current_data_mode)}>{dataHub?.data_mode_label || '-'}</strong></p>
          <p><span>Backend</span><strong className={tone(dataHub?.backend_status)}>{dataHub?.backend_status || '-'}</strong></p>
          <p><span>Provider</span><strong className={tone(dataHub?.provider_status)}>{dataHub?.provider_status || '-'}</strong></p>
          <p><span>Candle Source</span><strong>{dataHub?.candle_source || '-'}</strong></p>
          <p><span>Latest Price</span><strong>{asPrice(dataHub?.latest_live_price)}</strong></p>
          <p><span>Latest 15M</span><strong>{dataHub?.latest_primary_candle_time || '-'}</strong></p>
          <p><span>Freshness</span><strong className={tone(dataHub?.history_freshness)}>{dataHub?.history_freshness || '-'}</strong></p>
          <p><span>Gap Status</span><strong className={tone(dataHub?.gap_status)}>{dataHub?.gap_status || '-'}</strong></p>
          <p><span>Readiness</span><strong className={readiness.ready ? 'good' : 'warn'}>{readiness.state || '-'}</strong></p>
          <p><span>Last Error</span><strong>{dataHub?.last_error || '-'}</strong></p>
        </section>
        <section className="drawer-section">
          <h3>Actions</h3>
          <div className="drawer-grid">
            <label className="drawer-button file-label">
              Import Real History
              <input type="file" accept=".csv" onChange={onImportReal} />
            </label>
            <button onClick={onGenerateTest} disabled={actionsDisabled}>Generate Test History</button>
            <button onClick={onClearTest} disabled={actionsDisabled}>Clear Test History</button>
            <button onClick={onLiveOnly} disabled={actionsDisabled}>Live Only Mode</button>
            <button onClick={onFixGap} disabled={actionsDisabled}>Fix Gap</button>
            <button onClick={onSmartSetup} disabled={actionsDisabled}>Smart Setup</button>
            <button onClick={onDebug}>Debug Data</button>
            <button onClick={onExport} disabled={actionsDisabled}>Export Candles</button>
            <button onClick={onWizard} disabled={actionsDisabled}>Real Mode Wizard</button>
            <button onClick={onReset} disabled={actionsDisabled}>Reset Database</button>
          </div>
        </section>
        <section className="drawer-section">
          <h3>Candle Counts</h3>
          <div className="drawer-counts">
            {['1M', '5M', '15M', '1H', '4H', '1D'].map(tf => (
              <span key={tf}>{tf} <strong>{hubCounts?.[tf] || 0}</strong></span>
            ))}
          </div>
        </section>
        <section className="wizard-panel">
          <h3>Real Mode Setup Wizard</h3>
          {safeArray(wizard?.workflow_steps).length ? safeArray(wizard?.workflow_steps).map(step => (
            <p key={step.step || step.name}>
              <span>{step.step}. {step.name}</span>
              <strong className={tone(step.status)}>{step.status}</strong>
            </p>
          )) : (
            <p><span>Ready to run</span><strong>Click Wizard</strong></p>
          )}
          {wizard?.message && <em>{wizard.message}</em>}
        </section>
      </div>
    </aside>
  )
}

function MobileMenuDrawer({
  open = false,
  onClose = () => {},
  status = null,
  debugData = null,
  counts = {},
  onStart = () => {},
  onStop = () => {},
  onSeed = () => {},
  onDownload = () => {},
  onRefresh = () => {},
  onAnalyze = () => {},
  onDebug = () => {},
  onSmartSetup = () => {},
  onFixGap = () => {},
  onOpenDataHub = () => {},
  onRealModeWizard = () => {},
  onOneClickWarmup = () => {},
  onClearCache = () => {},
  onClearLogs = () => {},
  onRebuild = () => {},
  onClearInvalid = () => {},
  onGenerateTestHistory = () => {},
  onClearTestHistory = () => {},
  onLiveOnlyMode = () => {},
  onOpenOverlayMenu = () => {},
  onResetScale = () => {},
  onToggleStale = () => {},
  showStaleHistory = false,
  onToggleTestMode = () => {},
  testModeEnabled = false,
  dataMode = null,
  health = null,
  backendOffline = false,
  actionsDisabled = false,
  analyzeDisabled = false,
  chartMode = 'tradingview',
  onChartMode = () => {},
  tvSymbol = 'TVC:GOLD',
  onTvSymbol = () => {},
  engineMode = 'balanced',
  onEngineMode = () => {},
  apiKey = '',
  setApiKey = () => {},
  onSaveKey = () => {},
  onUploadCsv = () => {},
  onImportHistory = () => {},
  onClearLocalStorage = () => {},
}) {
  const menuActions = createMenuActions({
    'chart.tradingview': () => onChartMode('tradingview'),
    'chart.analysis': () => onChartMode('analysis'),
    'chart.split': () => onChartMode('split'),
    'chart.resetScale': onResetScale,
    'data.hub': onOpenDataHub,
    'data.realModeWizard': onRealModeWizard,
    'data.importRealHistory': onImportHistory,
    'data.generateTestHistory': onGenerateTestHistory,
    'data.clearTestHistory': onClearTestHistory,
    'data.liveOnlyMode': onLiveOnlyMode,
    'analysis.analyze': onAnalyze,
    'analysis.smartSetup': onSmartSetup,
    'analysis.fixGap': onFixGap,
    'analysis.clearCache': onClearCache,
    'system.debug': onDebug,
    'system.backendHealth': onRefresh,
    'system.clearLocalStorage': onClearLocalStorage,
  }, {
    actionsDisabled,
    analyzeDisabled,
    backendOffline,
    chartMode,
  })
  const menuGroups = groupMenuActions(menuActions)
  const activeActionId = `chart.${chartMode}`
  const runAction = action => {
    if (!action.enabled) return
    action.handler()
  }

  return (
    <aside className={`mobile-drawer ${open ? 'open' : ''}`}>
      <div className="drawer-panel">
        <div className="drawer-head">
          <strong>{APP_TITLE}</strong>
          <button onClick={onClose}>X</button>
        </div>
        {menuGroups.map(section => (
          <section className="drawer-section" key={section.group}>
            <h3>{section.group}</h3>
            <div className="drawer-grid">
              {section.actions.map(action => {
                const isImport = action.id === 'data.importRealHistory'
                const active = action.id === activeActionId
                if (isImport) {
                  return (
                    <label
                      className={`drawer-button file-label ${active ? 'active' : ''} ${!action.enabled ? 'disabled' : ''}`}
                      key={action.id}
                      title={action.description}
                    >
                      {action.label}
                      <input type="file" accept=".csv" onChange={action.handler} disabled={!action.enabled} />
                    </label>
                  )
                }
                return (
                  <button
                    className={active ? 'active' : ''}
                    disabled={!action.enabled}
                    key={action.id}
                    onClick={() => runAction(action)}
                    title={action.description}
                  >
                    {action.label}
                  </button>
                )
              })}
            </div>
            {section.group === 'Chart' && (
              <label className="drawer-field compact">
                <span>TradingView Symbol</span>
                <select value={tvSymbol} onChange={event => onTvSymbol(event.target.value)}>
                  {TRADINGVIEW_SYMBOLS.map(symbol => <option key={symbol} value={symbol}>{symbol}</option>)}
                </select>
              </label>
            )}
          </section>
        ))}
        <div className="drawer-status">
          <p><span>Data Mode</span><strong>{dataMode?.data_mode_label || '-'}</strong></p>
          <p><span>Backend</span><strong>{backendOffline ? 'BACKEND OFFLINE' : health?.status || '-'}</strong></p>
          <p><span>Provider</span><strong>{sourceLabel(status)}</strong></p>
          <p><span>Status</span><strong>{status?.status || '-'}</strong></p>
          <p><span>Latest Price</span><strong>{asPrice(status?.latest_price)}</strong></p>
          <p><span>Database</span><strong>{debugData?.database_exists ? 'Ready' : 'Missing'}</strong></p>
        </div>
        <div className="drawer-counts">
          {['1M', '5M', '15M', '1H', '4H', '1D'].map(tf => (
            <span key={tf}>{tf} <strong>{counts?.[tf] || 0}</strong></span>
          ))}
        </div>
      </div>
    </aside>
  )
}

function ChartContainer(props) {
  return (
    <section className="terminal-card">
      <SHAnalysisChart {...props} />
      <IndicatorPanel panels={props.panels} dataIntegrity={props.dataIntegrity} />
    </section>
  )
}

function SplitChartView({ liveProps, analysisProps, sourceBadge }) {
  return (
    <section className="split-chart-view">
      <div className="split-pane live-pane">
        <TradingViewLiveChart {...liveProps} compact />
      </div>
      <div className="split-pane analysis-pane">
        {sourceBadge}
        <ChartContainer {...analysisProps} />
      </div>
    </section>
  )
}

export default function App() {
  const [status, setStatus] = useState(null)
  const [health, setHealth] = useState(null)
  const [backendStatus, setBackendStatus] = useState(null)
  const [analysisState, setAnalysisState] = useState(null)
  const [routes, setRoutes] = useState([])
  const [apiErrorInfo, setApiErrorInfo] = useState(null)
  const [engineStatus, setEngineStatus] = useState(null)
  const [dataReadiness, setDataReadiness] = useState(null)
  const [dataIntegrity, setDataIntegrity] = useState(null)
  const [dataMode, setDataMode] = useState(null)
  const [dataHub, setDataHub] = useState(null)
  const [dataState, setDataState] = useState(null)
  const [gapDiagnosis, setGapDiagnosis] = useState(null)
  const [debugData, setDebugData] = useState(null)
  const [overlays, setOverlays] = useState(null)
  const [overlayStatus, setOverlayStatus] = useState(null)
  const [panels, setPanels] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [analysisExplanation, setAnalysisExplanation] = useState(null)
  const [chartData, setChartData] = useState(null)
  const [overlayVisibility, setOverlayVisibility] = useState({})
  const [timeframe, setTimeframe] = useState(getSavedTimeframe)
  const [chartMode, setChartMode] = useState(getSavedChartMode)
  const [tvSymbol, setTvSymbol] = useState(getSavedTradingViewSymbol)
  const [mobileTab, setMobileTab] = useState('live')
  const [isMobileLayout, setIsMobileLayout] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [isDataHubOpen, setIsDataHubOpen] = useState(false)
  const [overlayMenuOpen, setOverlayMenuOpen] = useState(false)
  const [analysisDrawerOpen, setAnalysisDrawerOpen] = useState(false)
  const [fixGapOpen, setFixGapOpen] = useState(false)
  const [wizardResult, setWizardResult] = useState(null)
  const [debugOpen, setDebugOpen] = useState(false)
  const [debugPing, setDebugPing] = useState(null)
  const [boot, setBoot] = useState({ phase: 'STARTING', slow: false, continueOffline: false })
  const [showStaleHistory, setShowStaleHistory] = useState(false)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [resetSignal, setResetSignal] = useState(0)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const refreshInFlightRef = useRef(false)

  const counts = safeObject(dataReadiness?.candle_counts || status?.candle_counts)
  const lockedMode = dataMode?.data_mode_lock || dataReadiness?.data_mode_lock || chartData?.data_mode_lock || dataMode || DEFAULT_LOCKED_MODE
  const historyAlignment = safeObject(chartData?.alignment || dataIntegrity?.alignment || chartData?.candle_health?.alignment)
  const alignmentBlocksAnalysis = historyAlignment.analysis_allowed === false || ['WARNING_PRICE_GAP', 'PRICE_GAP', 'CRITICAL_PRICE_GAP', 'PRICE_AND_TIME_GAP', 'TIME_GAP', 'STALE_HISTORY', 'FUTURE_HISTORY', 'NO_HISTORY'].includes(historyAlignment.alignment_status)
  const activeChartCandles = safeArray(chartData?.segments?.active)
  const chartCandles = activeChartCandles.length
    ? activeChartCandles
    : (dataIntegrity?.gap_detected ? safeArray(chartData?.segments?.live) : safeArray(chartData?.candles))
  const chartReady = Boolean(chartCandles.length)
  const backendOffline = apiErrorInfo?.code === 'BACKEND_OFFLINE' || lockedMode.locked_mode === 'BACKEND_OFFLINE_MODE'
  const actionsDisabled = loading || backendOffline
  const refreshDisabled = refreshing
  const internalDataReady = chartReady && lockedMode.can_analyze !== false && !alignmentBlocksAnalysis && !backendOffline
  const analyzeDisabled = backendOffline || loading || alignmentBlocksAnalysis || (chartMode === 'analysis' && lockedMode.can_analyze === false)
  const analyzeLabel = lockedMode.locked_mode === 'TEST_MODE' ? 'Analyze Test' : 'Analyze'
  const chartMessage = chartReady ? '' : (debugData?.errors?.[0] || NO_HISTORY_MESSAGE)
  const providerStopped = status?.status === 'STOPPED'
  const fullAnalysisDisabled = dataReadiness?.chart_ready && !dataReadiness?.full_analysis_ready
  const routeError = apiErrorInfo?.code === 'ROUTE_NOT_FOUND'

  const warnings = useMemo(() => {
    const items = []
    if (backendOffline) return items
    if (routeError) items.push('API route not found. Frontend and backend route names may not match.')
    if (alignmentBlocksAnalysis) items.push(historyAlignment.warning_message || 'History candles are not aligned with current live price.')
    if (dataIntegrity?.gap_detected) items.push(dataIntegrity.gap_warning || GAP_MESSAGE)
    if (!chartReady) items.push(NO_HISTORY_MESSAGE)
    if (chartMode !== 'analysis' && !internalDataReady) items.push('SH internal data for this timeframe is not ready.')
    if (providerStopped) items.push('Live builder is stopped. Start live builder to update current price.')
    if (fullAnalysisDisabled) items.push(FULL_ANALYSIS_MESSAGE)
    if (dataReadiness?.action_required && safeArray(dataReadiness?.action_choices).length) {
      items.push(`Action needed: ${safeArray(dataReadiness.action_choices).map(item => item?.label || 'Action').join(' / ')}`)
    }
    return [...new Set(items)]
  }, [backendOffline, routeError, dataIntegrity, chartReady, chartMode, internalDataReady, providerStopped, fullAnalysisDisabled, dataReadiness, alignmentBlocksAnalysis, historyAlignment])

  async function handleApiError(err) {
    const info = {
      message: err.message,
      code: err.code || 'API_ERROR',
      status: err.status || 0,
      apiBaseUrl: err.apiBaseUrl || API_BASE_URL,
      payload: err.payload || null,
    }
    setApiErrorInfo(info)
    setError(info.code === 'BACKEND_OFFLINE' || info.code === 'TIMEOUT' ? '' : err.message)
    setBoot(state => ({ ...state, phase: info.code === 'BACKEND_OFFLINE' || info.code === 'TIMEOUT' ? 'BACKEND_OFFLINE' : 'ERROR' }))
    if (import.meta.env.DEV) {
      console.group('SH Gold Analyzer Boot')
      console.error('Boot error', err)
      console.groupEnd()
    }
    if (info.code === 'BACKEND_OFFLINE' || info.code === 'TIMEOUT') {
      const offlineMode = {
        locked_mode: 'BACKEND_OFFLINE_MODE',
        data_mode: 'BACKEND_OFFLINE_MODE',
        data_mode_label: 'BACKEND OFFLINE',
        backend_status: 'BACKEND_OFFLINE',
        provider_status: 'OFFLINE',
        provider_name: '-',
        candle_source: 'LAST_KNOWN_CHART',
        analysis_state: 'Backend Offline',
        can_analyze: false,
        can_refresh: false,
        can_smart_setup: false,
        description: 'Backend offline. Last chart remains visible and actions are disabled.',
      }
      setHealth({ status: 'OFFLINE', version: '-', backend_status: 'BACKEND_OFFLINE' })
      setBackendStatus({ backend_status: 'BACKEND_OFFLINE', data_mode_lock: offlineMode })
      setDataMode(offlineMode)
      setDataState({ data_state: 'BACKEND_OFFLINE_MODE', analysis_state: 'Backend Offline', data_mode_lock: offlineMode })
      setStatus({ status: 'OFFLINE', provider_name: '-', latest_price: null })
      return
    }
    if (info.code === 'ROUTE_NOT_FOUND') {
      try {
        const routeResult = await getRoutes()
        setRoutes(routeResult.routes || [])
      } catch (_) {
        setRoutes([])
      }
    }
  }

  async function safeCall(label, request, fallback) {
    try {
      return await request()
    } catch (err) {
      const info = {
        label,
        message: err.message,
        code: err.code || 'API_ERROR',
        status: err.status || 0,
        apiBaseUrl: err.apiBaseUrl || API_BASE_URL,
        payload: err.payload || null,
      }
      if (import.meta.env.DEV) {
        console.warn(`SH Gold Analyzer API fallback: ${label}`, info)
      }
      return fallback
    }
  }

  async function refresh(nextTimeframe = timeframe, includeStale = showStaleHistory) {
    if (refreshInFlightRef.current) return
    refreshInFlightRef.current = true
    setRefreshing(true)
    setError('')
    setApiErrorInfo(null)
    try {
      const healthResult = await getHealth()
      setHealth(healthResult)
      if (import.meta.env.DEV) {
        console.group('SH Gold Analyzer Boot')
        console.log('Backend health', healthResult)
        console.groupEnd()
      }
      if (healthResult.status === 'OFFLINE') {
        throw Object.assign(new Error('Backend server is not running. Please start backend on port 8001.'), {
          code: 'BACKEND_OFFLINE',
          apiBaseUrl: API_BASE_URL,
        })
      }
      const [backendStatusResult, provider, engine, readiness, modeResult, stateResult, integrityResult, chartResult, overlayResult, panelResult, explanationResult] = await Promise.all([
        safeCall('backend-status', getBackendStatus, { backend_status: 'ONLINE', data_mode_lock: DEFAULT_LOCKED_MODE }),
        safeCall('provider-status', getProviderStatus, { status: 'NO_DATA', provider_name: '-', latest_price: null, settings: {} }),
        safeCall('engine-status', getEngineStatus, { engine_mode: 'balanced', engine_core_version: 'V4' }),
        safeCall('data-readiness', getDataReadiness, { ...DEFAULT_LOCKED_MODE, candle_counts: {}, data_mode_lock: DEFAULT_LOCKED_MODE }),
        safeCall('data-mode', getDataMode, DEFAULT_LOCKED_MODE),
        safeCall('data-state', getDataState, { data_state: 'NO_DATA_MODE', data_mode_lock: DEFAULT_LOCKED_MODE }),
        safeCall('data-integrity', () => getDataIntegrity(nextTimeframe, 300), { status: 'NO_HISTORY', warnings: [] }),
        safeCall('chart-data', () => getChartData(nextTimeframe, 500, includeStale), { status: 'NO_HISTORY', candles: [], segments: {}, data_integrity: { status: 'NO_HISTORY' }, overlays: {}, overlay_status: {} }),
        safeCall('overlays-v2', () => getOverlaysV2(nextTimeframe, 300), { status: 'NO_CANDLES', overlays: {}, chart_overlays: {}, overlay_status: {} }),
        safeCall('indicator-panels-v3', () => getIndicatorPanelsV3(nextTimeframe, 300), { status: 'WAITING_FOR_HISTORY', indicator_panels: {}, badge: null }),
        safeCall('analysis-explanation', getAnalysisExplanation, { analysis_explanation: null }),
      ])
      setBackendStatus(backendStatusResult)
      setAnalysisState({ analysis_state: readiness?.analysis_state || stateResult?.analysis_state || 'Waiting for Data' })
      setStatus(provider)
      setEngineStatus(engine)
      setDataReadiness(readiness)
      setDataMode(modeResult?.data_mode_lock || modeResult || DEFAULT_LOCKED_MODE)
      setDataState(stateResult)
      const nextIntegrity = chartResult?.data_integrity || integrityResult
      if (nextIntegrity?.gap_detected) {
        const diagnosisResult = await safeCall('gap-diagnosis', () => getGapDiagnosis(nextTimeframe), { status: 'GAP_WARNING' })
        setGapDiagnosis(diagnosisResult)
      } else {
        setGapDiagnosis(null)
      }
      setDataIntegrity(chartResult?.data_integrity || integrityResult)
      setChartData(chartResult || { candles: [], segments: {} })
      setOverlays(overlayResult || { overlays: {} })
      setOverlayStatus(chartResult?.overlay_status || overlayResult?.overlay_status || null)
      setPanels(panelResult)
      setAnalysisExplanation(explanationResult)
      const keys = Object.keys(safeObject(overlayResult?.overlays))
      setOverlayVisibility(prev => {
        const next = { ...prev }
        keys.forEach(key => {
          if (!(key in next)) next[key] = overlayResult?.overlays?.[key]?.visible !== false
        })
        return next
      })
      setBoot(state => ({ ...state, phase: 'READY', slow: false }))
    } catch (err) {
      await handleApiError(err)
    } finally {
      refreshInFlightRef.current = false
      setRefreshing(false)
    }
  }

  async function runAnalysis() {
    if (alignmentBlocksAnalysis) {
      setError(historyAlignment.warning_message || 'History candles are not aligned with current live price. Import recent history, generate live-anchored test history, or use live-only mode.')
      setAnalysisDrawerOpen(false)
      return
    }
    if ((chartMode === 'tradingview' || chartMode === 'split') && !internalDataReady) {
      setError('TradingView chart is live, but SH analysis data is not ready. Import real history or use SH Analysis mode.')
      setAnalysisDrawerOpen(true)
      return
    }
    setLoading(true)
    setError('')
    try {
      const result = await analyzeV4()
      setAnalysis(result)
      setAnalysisExplanation(result.analysis_explanation || null)
      setAnalysisDrawerOpen(true)
      await refresh(timeframe)
    } catch (err) {
      setAnalysis(err.payload || null)
      setAnalysisDrawerOpen(true)
      await handleApiError(err)
      await refresh(timeframe)
    } finally {
      setLoading(false)
    }
  }

  async function startBuilder() {
    try {
      const result = await startLiveBuilder()
      setStatus(result)
      if (result.error) setError(result.error)
      await refresh()
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function stopBuilder() {
    setStatus(await stopLiveBuilder())
    await refresh()
  }

  async function seedHistoryAndRefresh() {
    try {
      const result = await seedHistory()
      setMessage(result.message || 'Preloaded history seed completed.')
      await refresh(timeframe)
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function generateTestHistoryAndRefresh() {
    try {
      const result = await generateTestHistoryV2()
      setMessage(result.message || 'Generated TEST DATA candles for chart testing.')
      setFixGapOpen(false)
      setIsDataHubOpen(false)
      await refresh(timeframe)
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function oneClickWarmupAndRefresh() {
    try {
      const result = await oneClickWarmup()
      const actions = result.next_actions?.length ? ` Next: ${result.next_actions.map(item => item.label).join(' / ')}.` : ''
      setMessage(`One-click warmup: ${result.data_mode?.data_mode_label || result.status}. Full analysis: ${result.full_analysis_ready ? 'ready' : 'waiting'}.${actions}`)
      await refresh(timeframe)
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function smartSetupAndRefresh() {
    try {
      const result = await smartSetup()
      setMessage(result.fix_gap_required ? 'Smart Setup found a data gap. Choose a recovery option.' : 'Smart Setup complete.')
      if (result.fix_gap_required) setFixGapOpen(true)
      await refresh(timeframe)
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function liveOnlyModeAndRefresh() {
    try {
      const result = await fixGap('LIVE_ONLY')
      setMessage(result.status || 'Live Only mode enabled.')
      setFixGapOpen(false)
      setIsDataHubOpen(false)
      await refresh(timeframe)
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function archiveStaleAndRefresh() {
    try {
      const result = await archiveStaleHistory()
      setMessage(`${result.status || 'Stale history archived'}. Archived: ${result.archived_total ?? 0}`)
      await refresh(timeframe)
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function toggleStaleHistoryAndRefresh() {
    const next = !showStaleHistory
    setShowStaleHistory(next)
    try {
      await saveDataMode(dataMode?.selected_data_mode || 'AUTO', next)
    } catch (_) {
      // Local display toggle still works even if the setting save fails.
    }
    await refresh(timeframe, next)
  }

  async function clearTestHistoryAndRefresh() {
    if (!window.confirm('Clear TEST_HISTORY candles from the local database?')) return
    try {
      const result = await clearTestHistory()
      setMessage(result.message || 'TEST_HISTORY candles cleared.')
      setIsDataHubOpen(false)
      await refresh(timeframe)
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function toggleTestModeAndRefresh() {
    try {
      const enabled = !status?.settings?.test_mode_enabled
      const result = await toggleTestMode(enabled)
      setMessage(result.warning || `Test mode ${enabled ? 'enabled' : 'disabled'}.`)
      await refresh(timeframe)
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function downloadHistoryAndRefresh() {
    const result = await downloadFreeHistory()
    setMessage(result.message)
    await refresh(timeframe)
  }

  async function saveKey() {
    const result = await saveProviderSettings({ goldapi_io_key: apiKey })
    setMessage(result.message)
    setApiKey('')
    await refresh(timeframe)
  }

  async function rebuildAndRefresh() {
    const result = await rebuildCandleEngine()
    setMessage(result.message || result.status || 'Candle engine rebuilt from tick storage.')
    await refresh(timeframe)
  }

  async function clearInvalidAndRefresh() {
    if (!window.confirm('Clear invalid or misaligned candle rows from the local database?')) return
    const result = await clearInvalidCandles()
    setMessage(`Invalid candle cleanup complete. Removed: ${Object.values(result.removed || {}).reduce((a, b) => a + b, 0)}`)
    await refresh(timeframe)
  }

  async function uploadCsv(event) {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      const result = await uploadCsvForBacktest(file)
      setMessage(result.data_message || 'CSV uploaded for backtest/training.')
      await backtestCsvXauusd()
    } catch (err) {
      setError(err.message)
    } finally {
      event.target.value = ''
    }
  }

  async function importRealHistory(event) {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      const result = await importRealHistoryApi(file, timeframe)
      setMessage(`REAL_CSV_HISTORY imported: ${JSON.stringify(result.imported || {})}.`)
      setFixGapOpen(false)
      setIsDataHubOpen(false)
      await refresh(timeframe)
    } catch (err) {
      setError(err.message)
    } finally {
      event.target.value = ''
    }
  }

  async function clearCacheAndRefresh() {
    await clearAnalysisCache()
    await refresh(timeframe)
  }

  async function clearLogsAndRefresh() {
    await clearEngineLogs()
    await getEngineLogs()
    setMessage('Engine logs cleared.')
  }

  async function debugAndRefresh() {
    try {
      const [debugResult, routeResult, healthResult] = await Promise.all([
        safeCall('debug-data', getDebugData, { backend_connected: false, errors: ['Debug data unavailable.'] }),
        safeCall('routes', getRoutes, { routes: [] }),
        safeCall('health', getHealth, { status: 'OFFLINE' }),
      ])
      setDebugData(debugResult)
      setRoutes(safeArray(routeResult.routes))
      setHealth(healthResult)
      setDebugOpen(true)
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function runDebugPing() {
    const result = {}
    result.health = await safeCall('debug.health', getHealth, { status: 'OFFLINE' })
    result.dataHub = await safeCall('debug.data-hub', getDataHub, { error: 'Unavailable' })
    result.dataMode = await safeCall('debug.data-mode', getDataMode, DEFAULT_LOCKED_MODE)
    result.chartData = await safeCall('debug.chart-data', () => getChartData('15M', 10, showStaleHistory), { candles: [], segments: {}, error: 'Unavailable' })
    result.timestamp = new Date().toISOString()
    setDebugPing(result)
    setDebugOpen(true)
    return result
  }

  function clearLocalStorageAndReload() {
    try {
      localStorage.clear()
    } catch (_) {
      // Keep visible UI if storage is blocked.
    }
    window.location.reload()
  }

  function continueOffline() {
    const offlineMode = {
      ...DEFAULT_LOCKED_MODE,
      locked_mode: 'BACKEND_OFFLINE_MODE',
      data_mode: 'BACKEND_OFFLINE_MODE',
      data_mode_label: 'BACKEND OFFLINE',
      backend_status: 'BACKEND_OFFLINE',
      provider_status: 'OFFLINE',
      analysis_state: 'Backend Offline',
      can_analyze: false,
      can_refresh: false,
      can_smart_setup: false,
      description: 'Backend offline. Dashboard shell is running with placeholders.',
    }
    setBoot(state => ({ ...state, phase: 'BACKEND_OFFLINE', continueOffline: true }))
    setDataMode(offlineMode)
    setDataState({ data_state: 'BACKEND_OFFLINE_MODE', analysis_state: 'Backend Offline', data_mode_lock: offlineMode })
    setStatus({ status: 'OFFLINE', provider_name: '-', latest_price: null })
    setHealth({ status: 'OFFLINE', version: APP_VERSION, backend_status: 'BACKEND_OFFLINE' })
  }

  async function runWizardAndRefresh() {
    try {
      const result = await runRealModeWizard()
      setWizardResult(result)
      setMessage(result.message || result.status || 'Real Mode Wizard completed.')
      await refresh(timeframe)
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function exportCandlesAndRefresh() {
    try {
      const result = await exportCurrentCandles()
      const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'sh_gold_analyzer_xauusd_candles.json'
      link.click()
      URL.revokeObjectURL(url)
      setMessage('Current XAUUSD candles exported.')
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function resetDatabaseAndRefresh() {
    if (!window.confirm('Reset local XAUUSD candle database sources?')) return
    try {
      const result = await resetDatabase(true)
      setMessage(result.status || 'Database reset complete.')
      setAnalysis(null)
      setAnalysisExplanation(null)
      setWizardResult(null)
      await refresh(timeframe)
    } catch (err) {
      await handleApiError(err)
    }
  }

  async function handleOpenDataHub() {
    setMenuOpen(false)
    setIsDataHubOpen(true)
    if (backendOffline) return
    const hubResult = await safeCall('data-hub', getDataHub, { current_data_mode: 'NO_DATA_MODE', data_mode_label: 'NO DATA', candle_counts_by_timeframe: {}, analysis_readiness: {} })
    setDataHub(hubResult)
  }

  function handleCloseDataHub() {
    setIsDataHubOpen(false)
  }

  function handleFixGap() {
    setMenuOpen(false)
    setIsDataHubOpen(false)
    setFixGapOpen(true)
  }

  function handleOpenOverlays() {
    setMenuOpen(false)
    setOverlayMenuOpen(true)
  }

  function handleOpenDebug() {
    setMenuOpen(false)
    debugAndRefresh()
  }

  function handleResetScale() {
    setResetSignal(value => value + 1)
  }

  function handleChartMode(nextMode) {
    const mode = Object.keys(CHART_MODES).includes(nextMode) ? nextMode : 'tradingview'
    setChartMode(mode)
    setMenuOpen(false)
    if (mode === 'tradingview') setMobileTab('live')
    if (mode === 'analysis') setMobileTab('analysis')
  }

  function handleTradingViewSymbol(nextSymbol) {
    setTvSymbol(TRADINGVIEW_SYMBOLS.includes(nextSymbol) ? nextSymbol : 'TVC:GOLD')
  }

  async function changeEngineMode(mode) {
    try {
      const result = await setEngineMode(mode)
      setEngineStatus(result)
      setMessage(`Engine mode set to ${mode}.`)
      await refresh(timeframe)
    } catch (err) {
      await handleApiError(err)
    }
  }

  function toggleOverlay(key) {
    setOverlayVisibility(prev => ({ ...prev, [key]: prev[key] === false }))
  }

  useEffect(() => {
    clearBrokenLocalStorage()
    if (import.meta.env.DEV) {
      console.group('SH Gold Analyzer Boot')
      console.log('App mounted')
      console.log('API base URL', API_BASE_URL)
      console.groupEnd()
    }
    const slowTimer = setTimeout(() => {
      setBoot(state => state.phase === 'STARTING' ? { ...state, slow: true } : state)
    }, 5000)
    refresh(timeframe)
    return () => clearTimeout(slowTimer)
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem('sh_gold_timeframe', timeframe)
    } catch (_) {
      // Ignore blocked storage; runtime state is enough.
    }
  }, [timeframe])

  useEffect(() => {
    try {
      localStorage.setItem('sh_gold_chart_mode', chartMode)
      localStorage.setItem('sh_gold_tv_symbol', tvSymbol)
    } catch (_) {
      // Ignore blocked storage; runtime state is enough.
    }
  }, [chartMode, tvSymbol])

  useEffect(() => {
    const query = window.matchMedia('(max-width: 760px)')
    const sync = () => setIsMobileLayout(query.matches)
    sync()
    query.addEventListener?.('change', sync)
    return () => query.removeEventListener?.('change', sync)
  }, [])

  useEffect(() => {
    const interval = setInterval(() => {
      if (status?.is_running) refresh(timeframe, showStaleHistory)
    }, 6000)
    return () => clearInterval(interval)
  }, [status?.is_running, timeframe, showStaleHistory])

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const healthResult = await getHealth()
        setHealth(healthResult)
        if (backendOffline) await refresh(timeframe, showStaleHistory)
      } catch (err) {
        await handleApiError(err)
      }
    }, 10000)
    return () => clearInterval(interval)
  }, [backendOffline, timeframe, showStaleHistory])

  if (boot.phase === 'STARTING' && !boot.continueOffline && !chartData) {
    return (
      <BootScreen
        boot={boot}
        health={health}
        apiError={apiErrorInfo}
        debugPing={debugPing}
        onRetry={() => refresh(timeframe)}
        onContinueOffline={continueOffline}
        onDebug={runDebugPing}
      />
    )
  }

  const analysisChartProps = {
    chartData,
    overlays,
    overlayVisibility,
    onToggleOverlay: toggleOverlay,
    dataIntegrity,
    latestPrice: status?.latest_price || dataIntegrity?.latest_live_price,
    providerStatus: status,
    readiness: dataReadiness,
    dataMode,
    dataState,
    gapDiagnosis,
    engineStatus,
    analysis,
    panels,
    datasetKey: timeframe,
    emptyMessage: chartMessage,
    onSeed: seedHistoryAndRefresh,
    onSmartSetup: smartSetupAndRefresh,
    onFixGap: handleFixGap,
    onOneClickWarmup: oneClickWarmupAndRefresh,
    onImportHistory: importRealHistory,
    onStartBuilder: startBuilder,
    onGenerateTestHistory: generateTestHistoryAndRefresh,
    onClearTestHistory: clearTestHistoryAndRefresh,
    onLiveOnlyMode: liveOnlyModeAndRefresh,
    onArchiveStale: archiveStaleAndRefresh,
    onToggleStale: toggleStaleHistoryAndRefresh,
    showStaleHistory,
    onDebug: handleOpenDebug,
    onRefresh: () => refresh(),
    resetSignal,
    onResetScale: handleResetScale,
    onTimeframeChange: next => { setTimeframe(next); refresh(next) },
    onOpenOverlayMenu: handleOpenOverlays,
    apiError: apiErrorInfo,
    apiBaseUrl: API_BASE_URL,
    health,
    backendOffline,
    actionsDisabled,
  }
  const liveChartProps = {
    symbol: tvSymbol,
    timeframe,
    internalReady: internalDataReady,
  }
  const sourceBadge = (
    <EngineDataSourceBadge
      chartMode={chartMode}
      lockedMode={lockedMode}
      readiness={dataReadiness}
      dataIntegrity={dataIntegrity}
      backendOffline={backendOffline}
    />
  )

  return (
    <main className="app terminal-app">
      <TopToolbar
        timeframe={timeframe}
        chartMode={chartMode}
        latestPrice={status?.latest_price || dataIntegrity?.latest_live_price}
        onTimeframe={next => { setTimeframe(next); refresh(next) }}
        onChartMode={handleChartMode}
        onAnalyze={runAnalysis}
        onRefresh={() => refresh()}
        onMenu={() => setMenuOpen(true)}
        analyzeDisabled={analyzeDisabled}
        refreshDisabled={refreshDisabled}
        loading={loading}
        analyzeLabel={analyzeLabel}
      />

      <AppNotice
        error={error}
        message={message}
        warnings={warnings}
        backendOffline={backendOffline}
        apiBaseUrl={API_BASE_URL}
      />
      <DataModeBadge mode={dataMode || dataReadiness} />
      <DataModeBanner lockedMode={lockedMode} chartMode={chartMode} readiness={dataReadiness} />
      {chartMode !== 'split' && sourceBadge}

      {!isMobileLayout && chartMode === 'tradingview' && (
        <TradingViewLiveChart {...liveChartProps} />
      )}

      {!isMobileLayout && chartMode === 'analysis' && (
        <>
          <SignalDesk
            analysis={analysis}
            provider={status}
            dataIntegrity={dataIntegrity}
            timeframe={timeframe}
            dataMode={dataMode}
            readiness={dataReadiness}
            backendOffline={backendOffline}
          />
          <ChartContainer {...analysisChartProps} />
          <DataStatusCards
            readiness={dataReadiness}
            dataIntegrity={dataIntegrity}
            provider={status}
            overlayStatus={overlayStatus}
            chartData={chartData}
            dataMode={dataMode}
          />
          <AnalysisStatusChips
            overlays={overlays}
            panels={panels}
            analysis={analysis}
            readiness={dataReadiness}
            provider={status}
            dataIntegrity={dataIntegrity}
            dataMode={dataMode}
          />
          <SmartExplanationCard explanation={analysisExplanation} analysis={analysis} />
          <WorkflowPanel analysis={analysis} dataIntegrity={dataIntegrity} />
        </>
      )}

      {!isMobileLayout && chartMode === 'split' && (
        <SplitChartView liveProps={liveChartProps} analysisProps={analysisChartProps} sourceBadge={sourceBadge} />
      )}

      {isMobileLayout && (
        <section className="mobile-workspace">
          <div className="mobile-tab-switcher">
            {[
              ['live', 'Live Chart'],
              ['analysis', 'SH Analysis'],
              ['workflow', 'Workflow'],
              ['data', 'Data Hub'],
            ].map(([key, label]) => (
              <button key={key} className={mobileTab === key ? 'active' : ''} onClick={() => setMobileTab(key)}>
                {label}
              </button>
            ))}
          </div>
          {mobileTab === 'live' && <TradingViewLiveChart {...liveChartProps} />}
          {mobileTab === 'analysis' && <ChartContainer {...analysisChartProps} />}
          {mobileTab === 'workflow' && (
            <>
              <SignalDesk
                analysis={analysis}
                provider={status}
                dataIntegrity={dataIntegrity}
                timeframe={timeframe}
                dataMode={dataMode}
                readiness={dataReadiness}
                backendOffline={backendOffline}
              />
              <SmartExplanationCard explanation={analysisExplanation} analysis={analysis} />
              <WorkflowPanel analysis={analysis} dataIntegrity={dataIntegrity} />
            </>
          )}
          {mobileTab === 'data' && (
            <>
              <DataStatusCards
                readiness={dataReadiness}
                dataIntegrity={dataIntegrity}
                provider={status}
                overlayStatus={overlayStatus}
                chartData={chartData}
                dataMode={dataMode}
              />
              <AnalysisStatusChips
                overlays={overlays}
                panels={panels}
                analysis={analysis}
                readiness={dataReadiness}
                provider={status}
                dataIntegrity={dataIntegrity}
                dataMode={dataMode}
              />
              <button className="mobile-data-hub-button" onClick={handleOpenDataHub} disabled={actionsDisabled}>Open Data Hub</button>
            </>
          )}
        </section>
      )}

      <DebugDataPanel
        debugData={debugData}
        routes={routes}
        apiBaseUrl={API_BASE_URL}
        health={health}
        apiError={apiErrorInfo}
        dataState={dataState}
        gapDiagnosis={gapDiagnosis}
        debugPing={debugPing}
        open={debugOpen || Boolean(apiErrorInfo)}
        onToggle={() => setDebugOpen(value => !value)}
        onDebugPing={runDebugPing}
        onClearLocalStorage={clearLocalStorageAndReload}
      />

      <div className="bottom-status">
        <span className={`dot ${tone(status?.status)}`} />
        <strong>{status?.status || 'STARTING'}</strong>
        <span>{backendOffline ? 'Backend Offline' : routeError ? 'API Route Error' : lockedMode.analysis_state || dataReadiness?.analysis_state || dataIntegrity?.status || 'Waiting for Data'}</span>
        <em className={`data-mode-mini ${tone(lockedMode.locked_mode)}`}>{lockedMode.data_mode_label || dataReadiness?.data_mode_label || 'NO DATA'}</em>
        <button onClick={runAnalysis} disabled={analyzeDisabled}>{loading ? 'Working' : analyzeLabel}</button>
      </div>

      <MobileMenuDrawer
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        status={status}
        debugData={debugData}
        counts={counts}
        onStart={startBuilder}
        onStop={stopBuilder}
        onSeed={seedHistoryAndRefresh}
        onDownload={downloadHistoryAndRefresh}
        onRefresh={() => refresh()}
        onAnalyze={runAnalysis}
        onDebug={handleOpenDebug}
        onSmartSetup={smartSetupAndRefresh}
        onRealModeWizard={runWizardAndRefresh}
        onFixGap={handleFixGap}
        onOneClickWarmup={oneClickWarmupAndRefresh}
        onClearCache={clearCacheAndRefresh}
        onClearLogs={clearLogsAndRefresh}
        onRebuild={rebuildAndRefresh}
        onClearInvalid={clearInvalidAndRefresh}
        onGenerateTestHistory={generateTestHistoryAndRefresh}
        onClearTestHistory={clearTestHistoryAndRefresh}
        onLiveOnlyMode={liveOnlyModeAndRefresh}
        onOpenOverlayMenu={handleOpenOverlays}
        onOpenDataHub={handleOpenDataHub}
        onResetScale={handleResetScale}
        onToggleStale={toggleStaleHistoryAndRefresh}
        showStaleHistory={showStaleHistory}
        onToggleTestMode={toggleTestModeAndRefresh}
        testModeEnabled={Boolean(status?.settings?.test_mode_enabled)}
        dataMode={lockedMode}
        health={health}
        backendOffline={backendOffline}
        actionsDisabled={actionsDisabled}
        analyzeDisabled={analyzeDisabled}
        chartMode={chartMode}
        onChartMode={handleChartMode}
        tvSymbol={tvSymbol}
        onTvSymbol={handleTradingViewSymbol}
        engineMode={engineStatus?.engine_mode || 'balanced'}
        onEngineMode={changeEngineMode}
        apiKey={apiKey}
        setApiKey={setApiKey}
        onSaveKey={saveKey}
        onUploadCsv={uploadCsv}
        onImportHistory={importRealHistory}
        onClearLocalStorage={clearLocalStorageAndReload}
      />

      <DataHubDrawer
        open={isDataHubOpen}
        onClose={handleCloseDataHub}
        dataHub={dataHub}
        wizard={wizardResult}
        counts={counts}
        onImportReal={importRealHistory}
        onGenerateTest={generateTestHistoryAndRefresh}
        onClearTest={clearTestHistoryAndRefresh}
        onLiveOnly={liveOnlyModeAndRefresh}
        onFixGap={handleFixGap}
        onSmartSetup={smartSetupAndRefresh}
        onDebug={handleOpenDebug}
        onExport={exportCandlesAndRefresh}
        onReset={resetDatabaseAndRefresh}
        onWizard={runWizardAndRefresh}
        actionsDisabled={actionsDisabled}
      />

      <FixGapModal
        open={fixGapOpen}
        onClose={() => setFixGapOpen(false)}
        diagnosis={gapDiagnosis}
        onGenerateTest={generateTestHistoryAndRefresh}
        onImportReal={importRealHistory}
        onLiveOnly={liveOnlyModeAndRefresh}
      />

      <OverlayMenuDrawer
        open={overlayMenuOpen}
        onClose={() => setOverlayMenuOpen(false)}
        overlays={safeObject(overlays?.overlays)}
        visibility={overlayVisibility}
        onToggle={toggleOverlay}
      />

      <AnalysisResultDrawer
        open={analysisDrawerOpen}
        onClose={() => setAnalysisDrawerOpen(false)}
        analysis={analysis}
        lockedMode={lockedMode}
        dataIntegrity={dataIntegrity}
        explanation={analysisExplanation}
      />
    </main>
  )
}
