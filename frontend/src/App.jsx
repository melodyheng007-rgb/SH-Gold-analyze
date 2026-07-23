import React, { startTransition, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  BarChart3,
  Bitcoin,
  Bell,
  CalendarClock,
  ChartSpline,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  CircleDollarSign,
  Coins,
  Database,
  Download,
  Diamond,
  Globe2,
  Layers3,
  ListChecks,
  LogIn,
  LogOut,
  RefreshCw,
  Search,
  Send,
  Server,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  UserRound,
  Waypoints,
  X,
} from 'lucide-react'
import AustraliaFlag from 'country-flag-icons/string/3x2/AU'
import CanadaFlag from 'country-flag-icons/string/3x2/CA'
import SwitzerlandFlag from 'country-flag-icons/string/3x2/CH'
import ChinaFlag from 'country-flag-icons/string/3x2/CN'
import EuropeFlag from 'country-flag-icons/string/3x2/EU'
import UnitedKingdomFlag from 'country-flag-icons/string/3x2/GB'
import JapanFlag from 'country-flag-icons/string/3x2/JP'
import NewZealandFlag from 'country-flag-icons/string/3x2/NZ'
import UnitedStatesFlag from 'country-flag-icons/string/3x2/US'
import {
  archiveStaleHistory,
  backtestCsvXauusd,
  clearAnalysisCache,
  clearEngineLogs,
  clearInvalidCandles,
  clearTestHistory,
  downloadFreeHistory,
  getAnalysisState,
  getAnalysisExplanation,
  getDiamondHistory,
  getDiamondValidation,
  getMarketAlerts,
  getTrackedSetups,
  getBackendStatus,
  getDataHub,
  getDataMode,
  getDataState,
  getGapDiagnosis,
  getChartData,
  getDataIntegrity,
  getDataReadiness,
  getEngineLogs,
  getEngineStatus,
  getHealth,
  getMarketCandleTick,
  getMarketChartSnapshot,
  getMarketMtfSnapshot,
  getMarketNewsCalendar,
  getMarketOverview,
  getMarketSignalView,
  getTelegramAlertSettings,
  getTelegramCommunity,
  getOverlayStatus,
  getProviderCredentials,
  getProviderStatus,
  getStrategyGovernance,
  generateTestHistoryV2,
  importRealHistory as importRealHistoryApi,
  oneClickWarmup,
  runRealModeWizard,
  rebuildCandleEngine,
  exportCurrentCandles,
  resetDatabase,
  runDiamondValidation,
  setEngineMode,
  seedHistory,
  setDataMode as saveDataMode,
  fixGap,
  smartSetup,
  startLiveBuilder,
  stopLiveBuilder,
  toggleTestMode,
  uploadCsvForBacktest,
  verifyOandaFeed,
  saveTelegramAlertSettings,
  saveTelegramCommunity,
  testTelegramAlert,
  acknowledgeMarketAlert,
} from './api.js'
import { API_BASE_URL } from './config/api.js'
import { createMenuActions, groupMenuActions } from './actions/menuActions.js'
import WorkspaceErrorBoundary from './components/WorkspaceErrorBoundary.jsx'
import { safeArray, safeObject, safePrice, safeText } from './utils/safeFormat.js'
import { mergeChartDelta } from './utils/chartDelta.js'
import { isIndicatorSnapshotReady, readChartSnapshot, writeChartSnapshot } from './utils/chartSnapshotCache.js'
import { normalizeChartCandles, normalizeChartSeries } from './utils/chartSeries.js'
import {
  diamondHistoricalScore,
  diamondMarkerKind,
  diamondReplayTimestamp,
  diamondWasVisible,
} from './utils/diamondEvidence.js'
import { confidenceEngineSummary, confidenceStageState, decisionPlanVisible, executionReadinessGates } from './utils/confidenceEngine.js'
import {
  signalScore,
  signalTier,
} from './utils/signalRadar.js'
import { deriveDiamondRiskGuide } from './utils/diamondRiskGuide.js'
import { useAuth } from './auth/AuthProvider.jsx'

let chartEnginePromise

function loadChartEngine() {
  if (!chartEnginePromise) chartEnginePromise = import('lightweight-charts')
  return chartEnginePromise
}

const TOOLBAR_TIMEFRAMES = ['1M', '5M', '15M', '1H', '4H', '1D']
const TRADING_STYLES = {
  SCALPING: { label: '5M', timeframes: 'Scalp', executionTimeframe: '5M' },
  SWING: { label: '1H', timeframes: 'Intraday / Swing', executionTimeframe: '1H' },
}
const MARKET_ASSETS = {
  XAUUSD: { label: 'Gold', tradingViewSymbol: 'OANDA:XAUUSD' },
  BTCUSD: { label: 'Bitcoin', tradingViewSymbol: 'BINANCE:BTCUSDT' },
}
const DEFAULT_TELEGRAM_COMMUNITY_URL = String(import.meta.env.VITE_TELEGRAM_COMMUNITY_URL || '').trim()
const MENU_GROUP_ICONS = {
  Chart: BarChart3,
  Feed: ShieldCheck,
  Alerts: Bell,
  Data: Database,
  Analysis: Activity,
  System: SlidersHorizontal,
}
const TRADINGVIEW_SYMBOLS = [...new Set(Object.values(MARKET_ASSETS).map(asset => asset.tradingViewSymbol))]
const TRADINGVIEW_INTERVALS = { '1M': '1', '5M': '5', '15M': '15', '1H': '60', '4H': '240', '1D': 'D' }
const CHART_MODES = {
  signal: 'Signal View',
  tradingview: 'TradingView Live',
}
const NO_HISTORY_MESSAGE = 'No candle data available. Start live builder or import recent history.'
const GAP_MESSAGE = 'History gap detected. Live price is not aligned with local history.'
const FULL_ANALYSIS_MESSAGE = 'Full analysis requires recent 1D, 4H, 1H, 15M, and 5M candle history.'
const APP_VERSION = 'V3.8.7'
const APP_TITLE = 'SH Market Analyzer V3.8.7 - Dual-Lane Diamond Intelligence'
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
  description: 'Starting SH Market Analyzer.',
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

class DiamondMarkerRenderer {
  constructor(source) {
    this.source = source
  }

  draw(target) {
    const { chart, series, markers } = this.source
    if (!chart || !series || !markers.length) return
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      markers.forEach(marker => {
        const x = chart.timeScale().timeToCoordinate(Number(marker.time))
        const y = series.priceToCoordinate(Number(marker.marker_price ?? marker.line))
        if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || x > mediaSize.width || y < 0 || y > mediaSize.height) return
        const buyEntry = String(marker.entry_side || marker.direction).toUpperCase() === 'BUY'
          || (!marker.entry_side && String(marker.direction).toUpperCase() === 'BULLISH')
        const markerKind = marker.marker_kind || 'entry'
        const contextMarker = markerKind === 'context' || markerKind === 'liquidity'
        const directionalPalette = buyEntry
          ? { main: '#18bdf2', light: '#67dcff', dark: '#078dca', bright: '#31caff' }
          : { main: '#ff8733', light: '#ffbd73', dark: '#d95a12', bright: '#ffa24f' }
        const palette = directionalPalette
        const size = marker.latestEntry ? 11.5 : markerKind === 'setup' ? 8.5 : contextMarker ? 6.2 : 9.5
        const quality = Number(marker.quality_score ?? marker.strength ?? 100)
        const faded = quality < (contextMarker ? 68 : 82)
        const drawFacet = (points, color) => {
          context.fillStyle = color
          context.beginPath()
          points.forEach(([offsetX, offsetY], index) => {
            const pointX = x + offsetX * size
            const pointY = y + offsetY * size
            if (index === 0) context.moveTo(pointX, pointY)
            else context.lineTo(pointX, pointY)
          })
          context.closePath()
          context.fill()
        }
        const drawOutline = () => {
          context.strokeStyle = palette.main
          context.lineWidth = 1.15
          context.beginPath()
          context.moveTo(x - size, y - size * .08)
          context.lineTo(x - size * .6, y - size * .76)
          context.lineTo(x + size * .6, y - size * .76)
          context.lineTo(x + size, y - size * .08)
          context.lineTo(x, y + size * 1.14)
          context.closePath()
          context.stroke()
          context.globalAlpha *= .42
          drawFacet([[-.46, -.32], [.46, -.32], [0, .82]], palette.bright)
        }

        context.save()
        context.globalAlpha = marker.latestEntry ? .98 : faded ? .62 : .9
        context.lineJoin = 'round'
        context.shadowColor = palette.main
        context.shadowBlur = marker.latestEntry ? 6 : 3

        if (contextMarker) {
          context.shadowBlur = 1.5
          context.globalAlpha *= .72
          drawOutline()
        } else if (markerKind === 'setup') {
          drawOutline()
        } else {
          drawFacet([[-1, -.08], [-.6, -.76], [-.35, -.76], [-.53, -.08]], palette.dark)
          drawFacet([[-.48, -.76], [.48, -.76], [.28, -.45], [-.28, -.45]], palette.main)
          drawFacet([[.35, -.76], [.6, -.76], [1, -.08], [.53, -.08]], palette.light)
          drawFacet([[-.47, -.36], [.47, -.36], [.62, -.08], [-.62, -.08]], palette.bright)
          drawFacet([[-.92, .04], [-.5, .04], [-.08, .86], [0, 1.14]], palette.dark)
          drawFacet([[-.38, .04], [.38, .04], [0, 1.08]], palette.main)
          drawFacet([[.5, .04], [.92, .04], [.08, .86], [0, 1.14]], palette.light)
        }

        if (marker.latestEntry) {
          context.strokeStyle = palette.bright
          context.globalAlpha = .62
          context.lineWidth = 1
          context.beginPath()
          context.moveTo(x - size, y - size * .08)
          context.lineTo(x - size * .6, y - size * .76)
          context.lineTo(x + size * .6, y - size * .76)
          context.lineTo(x + size, y - size * .08)
          context.lineTo(x, y + size * 1.14)
          context.closePath()
          context.stroke()
          if (marker.latestEntry) {
            context.shadowBlur = 0
            context.fillStyle = palette.main
            context.globalAlpha = .32
            context.beginPath()
            context.ellipse(x, y + size * 1.48, size * .42, Math.max(1, size * .09), 0, 0, Math.PI * 2)
            context.fill()
          }
        }
        if (marker.marker_label) {
          context.shadowBlur = 0
          context.globalAlpha = .98
          context.font = '800 7px Inter, ui-sans-serif, system-ui'
          context.textAlign = 'center'
          context.textBaseline = 'middle'
          const label = String(marker.marker_label)
          const labelWidth = Math.ceil(context.measureText(label).width) + 7
          const labelHeight = 11
          const labelY = buyEntry
            ? y + size * 1.38 + labelHeight / 2
            : y - size * 1.02 - labelHeight / 2
          context.fillStyle = 'rgba(7, 16, 31, .92)'
          context.fillRect(x - labelWidth / 2, labelY - labelHeight / 2, labelWidth, labelHeight)
          context.strokeStyle = palette.main
          context.lineWidth = 1
          context.strokeRect(x - labelWidth / 2, labelY - labelHeight / 2, labelWidth, labelHeight)
          context.fillStyle = palette.light
          context.fillText(label, x, labelY + .25)
        }
        context.restore()
      })
    })
  }
}

class DiamondMarkerPaneView {
  constructor(source) {
    this.rendererInstance = new DiamondMarkerRenderer(source)
  }

  zOrder() { return 'top' }

  renderer() { return this.rendererInstance }
}

class DiamondMarkersPrimitive {
  constructor() {
    this.chart = null
    this.series = null
    this.markers = []
    this.requestUpdate = null
    this.views = [new DiamondMarkerPaneView(this)]
  }

  attached({ chart, series, requestUpdate }) {
    this.chart = chart
    this.series = series
    this.requestUpdate = requestUpdate
  }

  detached() {
    this.chart = null
    this.series = null
    this.requestUpdate = null
  }

  paneViews() { return this.views }

  setMarkers(zones) {
    const entryTimes = zones
      .filter(zone => (zone.marker_kind || 'entry') === 'entry')
      .map(zone => Number(zone.time))
      .filter(Number.isFinite)
    const latestEntryTime = entryTimes.length ? Math.max(...entryTimes) : null
    this.markers = zones.map(zone => ({
      ...zone,
      latestEntry: (zone.marker_kind || 'entry') === 'entry' && Number(zone.time) === latestEntryTime,
    }))
    this.requestUpdate?.()
  }
}

function tone(status = '') {
  if (/^(actionable|high quality|valid)/i.test(String(status))) return 'good'
  if (/^(pending|waiting|developing|candidate|no valid)/i.test(String(status))) return 'warn'
  if (/^(news lock|blocked)/i.test(String(status))) return 'bad'
  if (['LIVE', 'READY', 'VALID', 'REAL', 'REAL_MODE', 'ONLINE', 'ALIGNED', 'HEALTHY', 'HIGH', 'TRUSTED', 'BULLISH', 'Full Analysis Ready', 'FULL_ANALYSIS_READY', 'Chart Ready', 'Valid Setup', 'High Quality Setup', 'RECENT_HISTORY_READY'].includes(status)) return 'good'
  if (['TEST', 'TEST_MODE', 'MEDIUM', 'WARMING_UP', 'WARNING_PRICE_GAP', 'NO_COMPLETED_CANDLES', 'LOW_TICK_CONFIDENCE', 'PARTIAL', 'GAP_WARNING', 'GAP_WARNING_MODE', 'READY_WITH_GAP_WARNING', 'STALE_OR_PRICE_GAP', 'STARTING', 'RETRYING', 'NO_PRICE', 'WAITING', 'RANGE', 'MIXED', 'RESEARCH_ONLY', 'Waiting for Data', 'Waiting for Live Price', 'Waiting for Recent Candle History', 'Waiting for Recent History', 'Waiting for Liquidity Sweep', 'Waiting for Pullback to POI', 'Waiting for 5M Confirmation', 'LIVE_ONLY', 'LIVE_ONLY_MODE', 'LIVE ONLY', 'No History', 'NO_HISTORY', 'NO_DATA_MODE', 'Waiting for Live Tick', 'Partial Analysis Ready', 'Chart Ready - Test Mode', 'Test Mode Analysis', 'Test Data Mode', 'TEST_DATA_MODE'].includes(status)) return 'warn'
  if (['PRICE_GAP', 'CRITICAL_PRICE_GAP', 'PRICE_AND_TIME_GAP', 'TIME_GAP', 'STALE_HISTORY', 'FUTURE_HISTORY', 'INVALID', 'BEARISH', 'BLOCKED', 'NEWS_LOCK', 'NEWS_LOCKED', 'BLOCK_NEW_ENTRIES', 'No Trade', 'STOPPED', 'CONNECTION_FAILED', 'DNS_BLOCKED', 'DNS_FAILED', 'RATE_LIMIT', 'NO_CANDLES', 'NO_DATA', 'ERROR', 'Backend Offline', 'BACKEND_OFFLINE', 'BACKEND_OFFLINE_MODE', 'API Route Error'].includes(status)) return 'bad'
  return 'neutral'
}

function asPrice(value, fallback = '-') {
  const formatted = safePrice(value, 2)
  return formatted === '-' ? fallback : formatted
}

function asIndicatorValue(value, fallback = '-') {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallback
  const absolute = Math.abs(number)
  if (absolute >= 100) return number.toFixed(1)
  if (absolute >= 10) return number.toFixed(2)
  return number.toFixed(3)
}

function indicatorStateLabel(value) {
  const labels = {
    BULLISH_EXPANSION: 'Bull expand',
    BULLISH_FADE: 'Bull fade',
    BEARISH_EXPANSION: 'Bear expand',
    BEARISH_FADE: 'Bear fade',
    BULLISH_CROSS: 'Bull cross',
    BEARISH_CROSS: 'Bear cross',
    ABOVE_SIGNAL: 'Above signal',
    BELOW_SIGNAL: 'Below signal',
    CAUTION_DIVERGENCE: 'Divergence',
  }
  const normalized = String(value || '').toUpperCase()
  return labels[normalized] || normalized.replaceAll('_', ' ').toLowerCase().replace(/^./, letter => letter.toUpperCase()) || 'Waiting'
}

function macdBarColor(item) {
  const phase = String(item?.phase || item?.color || '').toUpperCase()
  if (phase.includes('BULLISH_EXPANSION') || phase.includes('BULL-STRONG')) return '#31d158'
  if (phase.includes('BULLISH_FADE') || phase.includes('BULL-FADE')) return '#168a42'
  if (phase.includes('BEARISH_EXPANSION') || phase.includes('BEAR-STRONG') || phase === 'RED') return '#ff453a'
  if (phase.includes('BEARISH_FADE') || phase.includes('BEAR-FADE')) return '#ff9f0a'
  return Number(item?.value) >= 0 ? '#31d158' : '#ff453a'
}

function rsiBarColor(item) {
  const value = Number(item?.raw_value ?? (Number(item?.value) + 50))
  if (value >= 70) return '#ff9f0a'
  if (value >= 55) return '#54e346'
  if (value <= 30) return '#20c8e8'
  if (value <= 45) return '#2f80ed'
  return '#7b8797'
}

function deriveIndicatorSnapshot(panelData) {
  const supplied = safeObject(panelData?.indicator_snapshot)
  if (supplied.status === 'READY') return supplied
  const macdItems = safeArray(panelData?.market_pressure || panelData?.boys_selling)
  const rsiItems = safeArray(panelData?.liquidity_pressure || panelData?.bearishness)
  if (!macdItems.length || !rsiItems.length) return supplied

  const latestMacd = Number(macdItems.at(-1)?.value)
  const previousMacd = Number(macdItems.at(-2)?.value ?? latestMacd)
  const latestRsiItem = rsiItems.at(-1)
  const previousRsiItem = rsiItems.at(-2) || latestRsiItem
  const latestRsi = Number(latestRsiItem?.raw_value ?? (Number(latestRsiItem?.value) + 50))
  const previousRsi = Number(previousRsiItem?.raw_value ?? (Number(previousRsiItem?.value) + 50))
  if (![latestMacd, previousMacd, latestRsi, previousRsi].every(Number.isFinite)) return supplied

  const rsiZone = latestRsi >= 70
    ? 'OVERBOUGHT'
    : latestRsi <= 30
      ? 'OVERSOLD'
      : latestRsi >= 55
        ? 'BULLISH'
        : latestRsi <= 45
          ? 'BEARISH'
          : 'NEUTRAL'
  return {
    status: 'READY',
    source: 'CLOSED_PROVIDER_CANDLES',
    macd: {
      histogram: latestMacd,
      bias: latestMacd > 0 ? 'BULLISH' : latestMacd < 0 ? 'BEARISH' : 'NEUTRAL',
      momentum: latestMacd > previousMacd ? 'RISING' : latestMacd < previousMacd ? 'FALLING' : 'FLAT',
    },
    rsi: {
      value: latestRsi,
      zone: rsiZone,
      momentum: latestRsi > previousRsi ? 'RISING' : latestRsi < previousRsi ? 'FALLING' : 'FLAT',
    },
    confluence: latestMacd > 0 && latestRsi >= 52
      ? 'ALIGNED_BULLISH'
      : latestMacd < 0 && latestRsi <= 48
        ? 'ALIGNED_BEARISH'
        : 'MIXED',
  }
}

function clampPercent(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}

function diamondVisibleFloor(...sources) {
  const explicit = sources
    .map(source => Number(source?.minimum_visible_diamond_score))
    .find(value => Number.isFinite(value) && value > 0)
  if (explicit) return explicit
  const symbol = sources.map(source => String(source?.symbol || '').toUpperCase()).find(Boolean)
  return symbol === 'XAUUSD' ? 45 : 50
}

function diamondGradeFromScore(value, invalidated = false, minimumScore = 50) {
  if (invalidated) return ''
  const score = clampPercent(value)
  if (score >= 90) return 'A+'
  if (score >= 80) return 'A'
  if (score >= 70) return 'B'
  if (score >= 60) return 'C'
  if (score >= minimumScore) return 'D'
  return ''
}

function diamondGradeLabel(grade, score, minimumScore = 50) {
  const normalizedGrade = String(grade || '').trim().toUpperCase()
  const numericScore = Number(score)
  const displayGrade = ['A+', 'A', 'B', 'C', 'D'].includes(normalizedGrade)
    ? normalizedGrade
    : diamondGradeFromScore(numericScore, false, minimumScore)
  if (!displayGrade || !Number.isFinite(numericScore) || numericScore < minimumScore) return ''
  return `${displayGrade} ${Number.isFinite(numericScore) ? clampPercent(numericScore) : '-'}`
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

function formatNewsTime(timestamp) {
  if (!timestamp) return '-'
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) return '-'
  return parsed.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })
}

function newsDateKey(timestamp) {
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) return 'UNKNOWN'
  const parts = new Intl.DateTimeFormat('en', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(parsed)
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

function newsDayLabel(timestamp, compact = false) {
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) return '-'
  return parsed.toLocaleDateString([], compact
    ? { weekday: 'short', day: 'numeric' }
    : { weekday: 'long', month: 'short', day: 'numeric' })
}

function newsClock(timestamp) {
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) return '-'
  return parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatFreshness(timestamp) {
  if (!timestamp) return '-'
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.getTime())) return '-'
  const minutes = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 60000))
  if (minutes < 1) return 'Now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function chartSnapshotSignature(chartData) {
  const active = safeArray(chartData?.segments?.active)
  const candles = active.length ? active : safeArray(chartData?.candles)
  const latest = candles.at(-1) || {}
  return [
    chartData?.symbol,
    chartData?.timeframe,
    candles.length,
    latest.time,
    latest.open,
    latest.high,
    latest.low,
    latest.close,
    latest.volume,
  ].join('|')
}

function chartSnapshotCandleCount(chartData) {
  const active = safeArray(chartData?.segments?.active)
  return active.length || safeArray(chartData?.candles).length
}

function isCandleSyncNotice(value) {
  return /candles are still synchronizing|candle synchronization paused|cached candles loaded/i.test(String(value || ''))
}

function analysisSnapshotSignature(analysis, automation) {
  const plan = safeObject(analysis?.trade_plan)
  const decision = safeObject(analysis?.decision_quality)
  const diamond = safeObject(analysis?.diamond_auto_entry)
  const alert = safeObject(analysis?.closed_candle_alert)
  return [
    analysis?.symbol,
    automation?.last_analyzed_candle_time,
    analysis?.final_decision,
    plan.status,
    plan.direction,
    decision.status,
    diamond.status,
    alert.id,
  ].join('|')
}

function autoAnalysisSignature(value) {
  return [value?.status, value?.mode, value?.ran, value?.last_analyzed_candle_time].join('|')
}

function liveSyncSignature(value) {
  return [
    value?.ok,
    value?.status,
    value?.provider,
    value?.timeframe,
    value?.last_candle?.timestamp || value?.last_candle?.time,
    value?.last_candle?.close,
    value?.forming_candle,
    value?.freshness_state,
    value?.provider_alignment?.status,
    value?.provider_alignment?.matched,
  ].join('|')
}

function healthSnapshotSignature(value) {
  return [
    value?.status,
    value?.backend_status,
    value?.provider_status,
    value?.data_mode,
    value?.database_connected,
    value?.btc_database_connected,
    safeArray(value?.supported_assets).join(','),
  ].join('|')
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

function getSavedTradingStyle() {
  try {
    const value = localStorage.getItem('sh_trading_style')
    return TRADING_STYLES[value] ? value : 'SCALPING'
  } catch (_) {
    return 'SCALPING'
  }
}

function getSavedChartMode() {
  try {
    const value = localStorage.getItem('sh_gold_chart_mode_v2')
    return Object.keys(CHART_MODES).includes(value) ? value : 'signal'
  } catch (_) {
    return 'signal'
  }
}

function getSavedTradingViewSymbol() {
  return MARKET_ASSETS[getSavedAsset()].tradingViewSymbol
}

function getSavedAsset() {
  try {
    const value = localStorage.getItem('sh_market_asset')
    return MARKET_ASSETS[value] ? value : 'XAUUSD'
  } catch (_) {
    return 'XAUUSD'
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

function SymbolBadge({ latestPrice, asset = 'XAUUSD' }) {
  const config = MARKET_ASSETS[asset] || MARKET_ASSETS.XAUUSD
  return (
    <div className="symbol-badge">
      <span>SH Market Analyzer <b>V3.8.7</b></span>
      <div><strong>{asset}</strong><em>{config.label}</em></div>
      <p>{asPrice(latestPrice)}</p>
    </div>
  )
}

function AccountControl() {
  const { user, signOut, openAuth } = useAuth()
  const [busy, setBusy] = useState(false)
  if (!user) {
    return (
      <button className="sign-in-action" type="button" onClick={openAuth} title="Sign in or create an account">
        <LogIn size={15} />
        <span>Sign in</span>
      </button>
    )
  }
  const name = String(user.user_metadata?.full_name || user.user_metadata?.name || user.email?.split('@')[0] || 'User')
  const initial = name.trim().charAt(0).toUpperCase() || 'U'

  async function handleSignOut() {
    setBusy(true)
    try {
      await signOut()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="account-control" title={user.email || name}>
      <i>{initial}</i>
      <span><strong>{name}</strong><small>Account</small></span>
      <button type="button" onClick={handleSignOut} disabled={busy} title="Sign out" aria-label="Sign out">
        <LogOut size={15} />
      </button>
    </div>
  )
}

function AccountDrawer({ open, onClose }) {
  const { user, signOut } = useAuth()
  const [busy, setBusy] = useState(false)
  if (!open) return null
  const name = String(user?.user_metadata?.full_name || user?.user_metadata?.name || user?.email?.split('@')[0] || 'User')
  const initial = name.trim().charAt(0).toUpperCase() || 'U'
  const handleSignOut = async () => {
    setBusy(true)
    try {
      await signOut()
      onClose()
    } finally {
      setBusy(false)
    }
  }
  return (
    <aside className="focus-drawer open" onMouseDown={event => event.target === event.currentTarget && onClose()}>
      <section className="focus-panel account-focus-panel" role="dialog" aria-modal="true" aria-label="Account">
        <header>
          <span><UserRound size={15} /> Account</span>
          <button onClick={onClose} title="Close account"><X size={17} /></button>
        </header>
        <div className="account-focus-identity">
          <i>{initial}</i>
          <span><strong>{name}</strong><small>{user?.email || 'Signed in'}</small></span>
        </div>
        <div className="account-focus-content">
          <div className="account-focus-status">
            <ShieldCheck size={16} />
            <span><strong>Protected workspace</strong><small>Your market preferences stay connected to this session.</small></span>
          </div>
          <button className="account-focus-signout" onClick={handleSignOut} disabled={busy}>
            <LogOut size={15} /><span>{busy ? 'Signing out' : 'Sign out'}</span>
          </button>
        </div>
      </section>
    </aside>
  )
}

function AlertCenterDrawer({ open, alerts, asset, onAcknowledge, onClose }) {
  const rows = safeArray(alerts?.alerts)
  const unread = Number(alerts?.stats?.unread ?? rows.filter(item => !item.acknowledged).length)
  const [notificationState, setNotificationState] = useState(() => {
    if (typeof Notification === 'undefined') return 'UNSUPPORTED'
    return Notification.permission === 'granted' && safeStorageGet('sh-device-alerts', '') === 'enabled' ? 'ENABLED' : Notification.permission.toUpperCase()
  })
  if (!open) return null
  const enableDeviceAlerts = async () => {
    if (typeof Notification === 'undefined') {
      setNotificationState('UNSUPPORTED')
      return
    }
    const permission = await Notification.requestPermission()
    if (permission === 'granted') {
      localStorage.setItem('sh-device-alerts', 'enabled')
      setNotificationState('ENABLED')
    } else {
      setNotificationState(permission.toUpperCase())
    }
  }
  return (
    <aside className="focus-drawer open" onMouseDown={event => event.target === event.currentTarget && onClose()}>
      <section className="focus-panel alert-focus-panel" role="dialog" aria-modal="true" aria-label="Smart Alert Center">
        <header>
          <span><Bell size={15} /> Smart Alerts <b>{unread}</b></span>
          <button onClick={onClose} title="Close alerts"><X size={17} /></button>
        </header>
        <div className="alert-focus-preferences">
          <span><strong>{asset}</strong><small>Grade B+ Diamond, confirmation, news lock and invalidation updates</small></span>
          <button className={notificationState === 'ENABLED' ? 'active' : ''} onClick={enableDeviceAlerts} disabled={notificationState === 'DENIED'}>
            {notificationState === 'ENABLED' ? 'Device alerts on' : notificationState === 'DENIED' ? 'Blocked by browser' : 'Enable device alerts'}
          </button>
        </div>
        <div className="alert-focus-list">
          {rows.length ? rows.map(item => (
            <article className={`${String(item.priority || 'WATCH').toLowerCase()} ${item.acknowledged ? 'read' : ''}`} key={item.id}>
              <i><Diamond size={13} /></i>
              <span>
                <strong>{item.title || 'Diamond update'}</strong>
                <small>{timeframeLabel(item.timeframe)} / {String(item.kind || item.priority || 'WATCH').replaceAll('_', ' ')}</small>
              </span>
              {!item.acknowledged && <button onClick={() => onAcknowledge?.(item.id)} title="Mark as reviewed"><CheckCircle2 size={15} /></button>}
            </article>
          )) : (
            <div className="alert-focus-empty"><Bell size={18} /><strong>No closed-candle alerts yet</strong><span>Only qualified engine events appear here.</span></div>
          )}
        </div>
        <footer>Alerts are deduplicated and never created from a forming candle.</footer>
      </section>
    </aside>
  )
}

function MobileFocusNav({ active, unread = 0, onSelect }) {
  const items = [
    ['chart', 'Chart', ChartSpline],
    ['history', 'History', Activity],
    ['news', 'News', CalendarClock],
    ['alerts', 'Alerts', Bell],
    ['account', 'Account', UserRound],
  ]
  return (
    <nav className="mobile-focus-nav" aria-label="Mobile workspace">
      {items.map(([id, label, Icon]) => (
        <button className={active === id ? 'active' : ''} onClick={() => onSelect(id)} key={id} aria-label={label}>
          <Icon size={17} />
          <span>{label}</span>
          {id === 'alerts' && unread > 0 && <b>{Math.min(unread, 99)}</b>}
        </button>
      ))}
    </nav>
  )
}

function useMarketNotifications(alerts) {
  const lastAlertRef = useRef('')
  useEffect(() => {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return
    if (safeStorageGet('sh-device-alerts', '') !== 'enabled') return
    const latest = safeArray(alerts?.alerts).find(item => !item.acknowledged)
    if (!latest?.id || latest.id === lastAlertRef.current) return
    lastAlertRef.current = latest.id
    const notification = new Notification(latest.title || 'SH Diamond Update', {
      body: `${timeframeLabel(latest.timeframe)} / ${String(latest.kind || latest.priority || 'WATCH').replaceAll('_', ' ')}`,
      icon: '/favicon.svg',
      tag: `sh-alert-${latest.id}`,
    })
    notification.onclick = () => window.focus()
  }, [alerts])
}

function DataModeBadge({ mode }) {
  const locked = mode?.data_mode_lock || mode
  const label = locked?.data_mode_label || locked?.locked_mode || locked?.data_mode || 'NO DATA'
  const backend = locked?.backend_status || 'ONLINE'
  const serviceLabel = String(backend).toUpperCase() === 'ONLINE' ? 'ONLINE' : 'UNAVAILABLE'
  const description = mode?.description || mode?.data_mode_description || 'Waiting for data mode'
  return (
    <div className={`data-mode-badge ${tone(locked?.locked_mode || locked?.data_mode || label)}`}>
      <span>Data Mode</span>
      <strong>{label}</strong>
      <em>{description}</em>
      <b className={tone(backend)}>{serviceLabel}</b>
    </div>
  )
}

function DataModeBanner({ lockedMode, chartMode = 'analysis', readiness }) {
  const mode = lockedMode?.locked_mode || lockedMode?.data_mode
  if (chartMode !== 'analysis') {
    return null
  }
  if (!mode) {
    return (
      <div className="data-mode-banner">
        <strong>Data Mode: NO DATA</strong>
        <span>Service: {lockedMode?.backend_status === 'ONLINE' ? 'ONLINE' : 'WAITING'} / Analysis: {engineAnalysisState(lockedMode, readiness)}</span>
      </div>
    )
  }
  if (mode === 'TEST_MODE') {
    return <div className="data-mode-banner test"><strong>TEST MODE</strong><span>Auto test scan only. Generated candles are never real signals.</span></div>
  }
  if (mode === 'LIVE_ONLY_MODE') {
    return <div className="data-mode-banner live-only"><strong>LIVE ONLY</strong><span>Chart and live price only. Full analysis is disabled until real candle history exists.</span></div>
  }
  if (mode === 'BACKEND_OFFLINE_MODE') {
    return <div className="data-mode-banner offline"><strong>SERVICE UNAVAILABLE</strong><span>Live updates are paused. Please try again shortly.</span></div>
  }
  if (mode === 'REAL_MODE') {
    return <div className="data-mode-banner real"><strong>REAL MODE</strong><span>Verified market history and live checks are active.</span></div>
  }
  return null
}

function publicNotice(value) {
  const text = String(value || '')
  if (/backend|api route|localhost|127\.0\.0\.1|invalid json|database path|history folder/i.test(text)) {
    return 'A market service is temporarily unavailable. Please try again shortly.'
  }
  return text
}

function AppNotice({ error, message, warnings, backendOffline }) {
  const items = safeArray(warnings)
  if (backendOffline) {
    return (
      <section className="app-notice offline">
        <div>
          <strong>Service unavailable</strong>
          <span>Live market updates are temporarily paused. Please try again shortly.</span>
        </div>
      </section>
    )
  }
  if (!error && !message && !items.length) return null
  const noticeText = publicNotice(error || message || items[0])
  return (
    <section className={`app-notice ${error ? 'bad' : message ? 'good' : 'warn'}`} title={noticeText} role="status">
      <div>
        <strong>{error ? 'Action Needed' : message ? 'Update' : 'Data Notice'}</strong>
        <span>{noticeText}</span>
      </div>
      {items.length > 1 && <em>+{items.length - 1} more</em>}
    </section>
  )
}

function BootScreen({ boot, health, apiError, onRetry, onContinueOffline }) {
  return (
    <main className="boot-screen">
      <section>
        <strong>Starting SH Market Analyzer...</strong>
        <p>{boot?.slow ? 'The workspace is taking longer than expected.' : 'Preparing your secure market workspace.'}</p>
        <div className="boot-checks">
          <span>Application <b>READY</b></span>
          <span>Market Service <b className={tone(health?.status || apiError?.code || 'STARTING')}>{health?.status === 'OK' ? 'READY' : 'CONNECTING'}</b></span>
          <span>Live Chart <b>READY</b></span>
        </div>
        {(boot?.slow || apiError) && (
          <div className="boot-actions">
            <button onClick={onRetry}>Retry</button>
            <button onClick={onContinueOffline}>Continue Offline</button>
          </div>
        )}
        {apiError && <em>{publicNotice(apiError.message)}</em>}
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

function TopToolbar({ asset, timeframe, tradingStyle, chartMode, latestPrice, onAsset, onTimeframe, onTradingStyle, onChartMode, onNews, onMenu, newsRisk, communityUrl }) {
  const activeCommunityUrl = String(communityUrl || DEFAULT_TELEGRAM_COMMUNITY_URL).trim()
  const communityReady = /^https:\/\/(t\.me|telegram\.me)\//i.test(activeCommunityUrl)
  return (
    <header className={`top-toolbar ${chartMode === 'signal' ? 'signal-mode' : 'tradingview-mode'}`}>
      <SymbolBadge asset={asset} latestPrice={latestPrice} />
      <div className="toolbar-controls">
        <div className="asset-control">
          <span>Market</span>
          <div className="asset-segmented" aria-label="Market asset">
            <button className={asset === 'XAUUSD' ? 'active' : ''} onClick={() => onAsset('XAUUSD')} aria-pressed={asset === 'XAUUSD'}>
              <CircleDollarSign size={15} />
              <span><strong>XAU</strong><small>Gold</small></span>
            </button>
            <button className={asset === 'BTCUSD' ? 'active' : ''} onClick={() => onAsset('BTCUSD')} aria-pressed={asset === 'BTCUSD'}>
              <Bitcoin size={15} />
              <span><strong>BTC</strong><small>Bitcoin</small></span>
            </button>
          </div>
        </div>
        <div className="position-control">
          <span>Position</span>
          <div className="position-segmented" aria-label="Trading position style">
            {Object.entries(TRADING_STYLES).map(([key, config]) => (
              <button
                className={tradingStyle === key ? 'active' : ''}
                key={key}
                onClick={() => onTradingStyle(key)}
                aria-pressed={tradingStyle === key}
                title={`${config.label}: ${config.timeframes}`}
              >
                <strong>{config.label}</strong>
                <small>{config.timeframes}</small>
              </button>
            ))}
          </div>
        </div>
        <label className="toolbar-field">
          <span>Timeframe</span>
          <select value={timeframe} onChange={event => onTimeframe(event.target.value)} aria-label="Timeframe">
            {TOOLBAR_TIMEFRAMES.map(item => <option key={item} value={item}>{timeframeLabel(item)}</option>)}
          </select>
        </label>
      </div>
      <div className="toolbar-actions">
        <button
          className="view-action"
          title={chartMode === 'signal' ? 'Open TradingView Live' : 'Open Signal View'}
          onClick={() => onChartMode(chartMode === 'signal' ? 'tradingview' : 'signal')}
        >
          {chartMode === 'signal' ? <BarChart3 size={16} /> : <Activity size={16} />}
          <span>{chartMode === 'signal' ? 'TradingView' : 'Signal View'}</span>
        </button>
        <button
          className={`weekly-news-action ${String(newsRisk || 'CLEAR').toLowerCase()}`}
          title="Open full weekly economic calendar"
          aria-label="Open weekly economic calendar"
          onClick={onNews}
        >
          <CalendarClock size={16} />
          <span>News</span>
          {['HIGH', 'ELEVATED'].includes(String(newsRisk || '').toUpperCase()) && <i aria-hidden="true" />}
        </button>
        <a
          className={`community-toolbar-action ${communityReady ? '' : 'unavailable'}`}
          href={communityReady ? activeCommunityUrl : undefined}
          target={communityReady ? '_blank' : undefined}
          rel={communityReady ? 'noreferrer' : undefined}
          aria-disabled={!communityReady}
          onClick={event => {
            if (!communityReady) event.preventDefault()
          }}
          title={communityReady ? 'Join the SH Telegram community' : 'Community invite is being prepared'}
        >
          <Send size={16} />
          <span><small>Community</small><strong>{communityReady ? 'Join Telegram' : 'Coming Soon'}</strong></span>
        </a>
        <button className="settings-action" title="Open settings" onClick={onMenu}>
          <Settings size={16} />
          <span>Settings</span>
        </button>
        <AccountControl />
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

function CompactStatusStrip({ asset = 'XAUUSD', analysis, providerAlignment, lockedMode, readiness, dataIntegrity, backendOffline }) {
  const hasActiveAnalysis = analysis?.symbol === asset
  const source = hasActiveAnalysis
    ? analysis?.analysis_data_source || 'REAL_HISTORY'
    : asset === 'BTCUSD' ? 'PENDING_SYNC' : engineSourceLabel(lockedMode, dataIntegrity)
  const analysisState = backendOffline
    ? 'Disabled'
    : hasActiveAnalysis ? analysis?.final_decision : asset === 'BTCUSD' ? 'Auto Engine Ready' : engineAnalysisState(lockedMode, readiness)
  return (
    <section className="compact-status-strip">
      <div>
        <span>Market</span>
        <strong>{asset} / TradingView</strong>
      </div>
      <div>
        <span>Analysis Data</span>
        <strong className={tone(String(source).includes('REAL') ? 'REAL_MODE' : source)}>{source}</strong>
      </div>
      <div>
        <span>Service</span>
        <strong className={tone(backendOffline ? 'BACKEND_OFFLINE' : lockedMode?.backend_status)}>{backendOffline ? 'UNAVAILABLE' : lockedMode?.backend_status === 'ONLINE' ? 'ONLINE' : 'CONNECTING'}</strong>
      </div>
      <div>
        <span>Engine</span>
        <strong className={tone(analysisState)}>{analysisState}</strong>
      </div>
      <div>
        <span>Feed Match</span>
        <strong className={providerAlignment?.matched ? 'good' : 'warn'}>{providerAlignment?.status || 'PENDING'}</strong>
      </div>
    </section>
  )
}

function MarketScanner({ overview, asset, onAsset, loading = false }) {
  const overviewAssets = safeArray(overview?.assets)
  const rows = Object.keys(MARKET_ASSETS).map(symbol => (
    overviewAssets.find(item => item?.symbol === symbol) || { symbol }
  ))

  return (
    <section className="market-scanner" aria-label="Market scanner">
      <header className="market-scanner-head">
        <div>
          <Activity size={15} />
          <strong>Market Scanner</strong>
        </div>
        <span>{loading ? 'Refreshing' : `Updated ${formatFreshness(overview?.generated_at)}`}</span>
      </header>
      <div className="market-scanner-assets">
        {rows.map(item => {
          const symbol = item.symbol
          const isActive = symbol === asset
          const AssetIcon = symbol === 'BTCUSD' ? Bitcoin : Coins
          const scoreValue = item.score === null || item.score === undefined ? '-' : clampPercent(item.score)
          const direction = safeText(item.direction, 'WAIT').toUpperCase()
          return (
            <button
              type="button"
              key={symbol}
              className={`market-scanner-card ${isActive ? 'active' : ''}`}
              onClick={() => onAsset(symbol)}
              aria-pressed={isActive}
            >
              <span className="market-scanner-icon"><AssetIcon size={17} /></span>
              <span className="market-scanner-symbol">
                <strong>{symbol}</strong>
                <small>{formatFreshness(item.latest_5m_candle)} candle</small>
              </span>
              <span className="market-scanner-price">{asPrice(item.price)}</span>
              <span className="market-scanner-state">
                <strong className={tone(item.decision)}>{item.bias || 'Waiting'}</strong>
                <small title={item.decision}>{item.decision || 'Auto scan ready'}</small>
              </span>
              <span className={`market-scanner-direction ${direction.toLowerCase()}`}>{direction}</span>
              <span className="market-scanner-score">{scoreValue === '-' ? '-' : scoreValue}</span>
              <ChevronRight size={15} />
            </button>
          )
        })}
      </div>
    </section>
  )
}

function signalViewCandles(chartData, expectedSymbol) {
  if (chartData?.symbol && expectedSymbol && chartData.symbol !== expectedSymbol) return []
  const segments = safeObject(chartData?.segments)
  const source = safeArray(segments.active).length ? safeArray(segments.active) : safeArray(chartData?.candles)
  return normalizeChartCandles(source, 500)
}

function decisionQualityLabel(status) {
  const labels = {
    DATA_BLOCKED: 'Data Check Required',
    NEWS_LOCKED: 'News Lock - No Entry',
    VOLATILITY_LOCKED: 'Volatility Lock - No Entry',
    ASSET_PROFILE_GUARD: 'Pro Analyze Alignment Required',
    SCANNING: 'Scanning Completed Candles',
    CONTEXT_ONLY: 'Context Only - No Entry',
    HISTORICAL_CONTEXT: 'Historical Diamond - No Entry',
    WAITING_CONFIRMATION: 'Waiting for Diamond Confirmation',
    REGIME_CONFLICT: 'Regime Conflict - No Entry',
    LOCATION_GUARD: 'Anti-Chase Guard - No Entry',
    RANGE_GUARD: 'Range Edge Required',
    REGIME_TRANSITION: 'Regime Transition - Waiting',
    WAITING_ENGINE_AGREEMENT: 'Waiting for Engine Agreement',
    RISK_REVIEW: 'Risk Map Incomplete',
    TRACKABLE_LIMITED_EVIDENCE: 'Research Setup - Limited Evidence',
    TRACKABLE_SETUP: 'Trackable Research Setup',
  }
  return labels[String(status || '').toUpperCase()] || null
}

function deriveSignalViewLevels(candles, overlays, analysis, sessionFramework, keyZones) {
  if (!candles.length) return []
  const last = candles[candles.length - 1]
  const ranges = candles.slice(-14).map(candle => Math.abs(Number(candle.high) - Number(candle.low))).filter(Number.isFinite)
  const atr = ranges.length ? ranges.reduce((total, value) => total + value, 0) / ranges.length : 0
  const overlayItems = safeObject(overlays?.overlays)
  const pivot = Number(overlayItems?.pivot_line?.price)
  const sessionLevels = safeObject(sessionFramework?.levels)
  const hasSessionLevels = sessionFramework?.status === 'READY' && Number.isFinite(Number(sessionLevels.op))
  const currentPrice = Number(last.close)
  const sessionCandidates = [
    { key: 'k_plus_3', label: 'K+3', price: Number(sessionLevels.k_plus_3), color: '#f4ea2a', style: 'dashed' },
    { key: 'k_plus_2', label: 'K+2', price: Number(sessionLevels.k_plus_2 ?? sessionLevels.dr_plus_2), color: '#f4c95d', style: 'dashed' },
    { key: 'k_plus_1', label: 'K+1', price: Number(sessionLevels.k_plus_1 ?? sessionLevels.dr_plus_1), color: '#76ff03', style: 'dashed' },
    { key: 'session_open', label: 'OP', price: Number(sessionLevels.op), color: '#f8fafc', style: 'dotted' },
    { key: 'mlp', label: 'MLP', price: Number(sessionLevels.mlp), color: '#f5e875', style: 'dotted' },
    { key: 'session_pivot', label: 'PIVOT', price: Number(sessionLevels.pivot), color: '#22d3ee', style: 'solid' },
    { key: 'k_minus_1', label: 'K-1', price: Number(sessionLevels.k_minus_1 ?? sessionLevels.dr_minus_1), color: '#76ff03', style: 'dashed' },
    { key: 'k_minus_2', label: 'K-2', price: Number(sessionLevels.k_minus_2 ?? sessionLevels.dr_minus_2), color: '#f4c95d', style: 'dashed' },
    { key: 'k_minus_3', label: 'K-3', price: Number(sessionLevels.k_minus_3), color: '#f4ea2a', style: 'dashed' },
  ].filter(level => Number.isFinite(level.price) && level.price > 0)
  const nearestKAbove = sessionCandidates
    .filter(level => level.key.startsWith('k_') && level.price > currentPrice)
    .sort((left, right) => left.price - right.price)[0]
  const nearestKBelow = sessionCandidates
    .filter(level => level.key.startsWith('k_') && level.price < currentPrice)
    .sort((left, right) => right.price - left.price)[0]
  const nearestSessionAnchors = sessionCandidates
    .filter(level => !level.key.startsWith('k_'))
    .sort((left, right) => Math.abs(left.price - currentPrice) - Math.abs(right.price - currentPrice))
    .slice(0, 2)
  const levels = hasSessionLevels ? [
    nearestKAbove,
    ...nearestSessionAnchors,
    nearestKBelow,
    { key: 'price', label: 'PRICE', price: currentPrice, color: '#a1a1aa', style: 'solid' },
  ].filter(Boolean) : [
    { key: 'range_plus', label: 'R+1', price: Number(last.close) + atr * 1.5, color: '#76ff03', style: 'dashed' },
    { key: 'price', label: 'PRICE', price: Number(last.close), color: '#a1a1aa', style: 'solid' },
    { key: 'open', label: 'OPEN', price: Number(last.open), color: '#f8fafc', style: 'dotted' },
    { key: 'pivot', label: 'PIVOT', price: pivot, color: '#22d3ee', style: 'solid' },
    { key: 'range_minus', label: 'R-1', price: Number(last.close) - atr * 1.5, color: '#76ff03', style: 'dashed' },
  ]
  const diamondZone = safeObject(keyZones?.primary_zone)
  const visibleDiamondFloor = diamondVisibleFloor(keyZones, diamondZone)
  if (
    keyZones?.status === 'READY'
    && keyZones?.diamond_display_status !== 'NO_QUALIFIED_DIAMOND'
    && diamondZone.strategy_confirmed_origin === true
    && diamondZone.display_as_diamond !== false
    && Number(diamondZone.diamond_score ?? keyZones?.diamond_score ?? 0) >= visibleDiamondFloor
    && Number.isFinite(Number(diamondZone.line))
  ) {
    const diamondRole = diamondZone.role === 'SUPPORT' ? 'SUP' : diamondZone.role === 'RESISTANCE' ? 'RES' : 'TEST'
    const diamondColor = diamondZone.role === 'SUPPORT'
      ? '#21d4d4'
      : diamondZone.role === 'RESISTANCE'
        ? '#ff9f72'
        : diamondZone.direction === 'BULLISH' ? '#21d4d4' : '#ff9f72'
    levels.push({
      key: 'diamond_line',
      label: `DL ${diamondRole}`,
      price: Number(diamondZone.line),
      color: diamondColor,
      style: 'dashed',
      hideLeftLabel: true,
    })
  }
  const unique = new Map()
  levels.filter(level => Number.isFinite(level.price) && level.price > 0).forEach(level => {
    const key = Math.round(level.price / Math.max(atr * .04, currentPrice * 1e-7))
    if (!unique.has(key) || level.key === 'price' || level.key === 'diamond_line') unique.set(key, level)
  })
  return [...unique.values()]
}

function crystalMarkerPrice(candle, buy) {
  if (!candle) return null
  const high = Number(candle.high)
  const low = Number(candle.low)
  const close = Number(candle.close)
  if (![high, low, close].every(Number.isFinite)) return null
  const range = Math.max(high - low, Math.abs(close) * .0002)
  return buy ? low - range * .42 : high + range * .42
}

function derivePersistedDiamondMarkers(candles, history, timeframe) {
  const candleByTime = new Map(candles.map(candle => [Number(candle.time), candle]))
  return safeArray(history?.entries)
    .filter(entry => String(entry?.timeframe || '').toUpperCase() === String(timeframe || '').toUpperCase())
    .map(entry => {
      const sourceClassification = String(entry.classification || 'CONTEXT').toUpperCase()
      const classification = String(entry.display_classification || sourceClassification).toUpperCase()
      const markerTime = diamondReplayTimestamp(entry)
      const buy = String(entry.entry_side || entry.direction).toUpperCase() === 'BUY'
        || String(entry.direction).toUpperCase() === 'BULLISH'
      const markerPrice = crystalMarkerPrice(candleByTime.get(markerTime), buy)
      if (!Number.isFinite(markerTime) || !Number.isFinite(markerPrice)) return null
      const qualityScore = clampPercent(diamondHistoricalScore(entry))
      const scoreFloor = diamondVisibleFloor(entry)
      const grade = entry.peak_diamond_grade || entry.diamond_grade || diamondGradeFromScore(qualityScore, false, scoreFloor)
      const gradeLabel = diamondGradeLabel(grade, qualityScore, scoreFloor)
      const rejected = classification === 'INVALIDATED_CONTEXT'
        || ['INVALIDATED_NO_ENTRY', 'CANCELLED', 'EXPIRED_NO_ENTRY'].includes(String(entry.verification_status || '').toUpperCase())
      if (!diamondWasVisible(entry)) return null
      return {
        id: `history-${entry.zone_key}`,
        zone_key: entry.zone_key,
        event_id: entry.event_id,
        time: markerTime,
        marker_price: markerPrice,
        entry_side: buy ? 'BUY' : 'SELL',
        direction: entry.direction,
        marker_kind: diamondMarkerKind(sourceClassification),
        marker_title: `${rejected ? 'Saved historical' : 'Historical'} ${buy ? 'BUY' : 'SELL'} Diamond / ${gradeLabel || 'saved zone'} / ${String(entry.verification_status || 'MONITORING').replaceAll('_', ' ')}`,
        marker_label: gradeLabel,
        quality_score: qualityScore,
        diamond_grade: grade,
        diamond_score: qualityScore,
        grade_status: entry.grade_status,
        verification_status: entry.verification_status,
        signal_tier: signalTier({ ...entry, classification: sourceClassification }),
        closed_candle_proof: entry.closed_candle_proof,
        persistent: true,
      }
    })
    .filter(Boolean)
    .sort((left, right) => Number(left.time) - Number(right.time))
}

function deriveValidationReplayMarkers(candles, validation, timeframe) {
  if (!['READY', 'NO_CONFIRMED_EVENTS'].includes(String(validation?.status || '').toUpperCase())) return []
  const normalizedTimeframe = String(timeframe || '').toUpperCase()
  const candleByTime = new Map(candles.map(candle => [Number(candle.time), candle]))
  return safeArray(validation?.replay_zones)
    .filter(zone => (
      zone?.strategy_confirmed_origin === true
      && zone?.display_as_diamond === true
      && String(zone?.timeframe || '').toUpperCase() === normalizedTimeframe
    ))
    .map(zone => {
      const markerTime = Number(zone.detected_time ?? zone.origin_time)
      const side = String(zone.entry_side || zone.direction).toUpperCase()
      const buy = side === 'BUY' || side === 'BULLISH'
      const markerPrice = crystalMarkerPrice(candleByTime.get(markerTime), buy)
      if (!Number.isFinite(markerTime) || !Number.isFinite(markerPrice)) return null
      const score = clampPercent(zone.diamond_score)
      const gradeLabel = diamondGradeLabel(zone.diamond_grade, score, diamondVisibleFloor(zone))
      const outcome = String(zone.outcome || 'WATCHING').replaceAll('_', ' ')
      return {
        ...zone,
        id: `engine-replay-${zone.zone_key || zone.zone_id}`,
        time: markerTime,
        marker_price: markerPrice,
        entry_side: buy ? 'BUY' : 'SELL',
        marker_kind: 'setup',
        marker_label: gradeLabel,
        marker_title: `Engine Replay ${buy ? 'BUY' : 'SELL'} Diamond / ${gradeLabel || 'confirmed setup'} / ${outcome}`,
        quality_score: score,
        signal_tier: 'QUALIFIED',
        verification_status: zone.outcome,
        persistent: true,
        engine_replay: true,
      }
    })
    .filter(Boolean)
    .sort((left, right) => Number(left.time) - Number(right.time))
}

function deriveCurrentDiamondMarkers(candles, zones) {
  const candleByTime = new Map(candles.map(candle => [Number(candle.time), candle]))
  return safeArray(zones).map(zone => {
    if (zone?.strategy_confirmed_origin !== true) return null
    const markerTime = Number(zone.time)
    const side = String(zone.entry_side || zone.direction).toUpperCase()
    const buy = side === 'BUY' || side === 'BULLISH'
    const markerPrice = crystalMarkerPrice(candleByTime.get(markerTime), buy)
    if (!Number.isFinite(markerTime) || !Number.isFinite(markerPrice)) return null
    const score = signalScore(zone)
    const scoreFloor = diamondVisibleFloor(zone)
    const gradeLabel = diamondGradeLabel(zone.diamond_grade || zone.quality_grade, score, scoreFloor)
    const tier = signalTier(zone)
    return {
      ...zone,
      id: `live-${zone.id}`,
      time: markerTime,
      marker_price: markerPrice,
      entry_side: buy ? 'BUY' : 'SELL',
      marker_kind: tier === 'QUALIFIED' ? 'setup' : 'context',
      marker_label: gradeLabel,
      marker_title: `${tier} ${buy ? 'BUY' : 'SELL'} Diamond / ${gradeLabel} / ${String(zone.origin_model || 'STRUCTURAL ORIGIN').replaceAll('_', ' ')}`,
      quality_score: score,
      signal_tier: tier,
      persistent: false,
    }
  }).filter(Boolean)
}

function mergeCrystalMarkers(markers, timeframe = '15M') {
  const merged = new Map()
  const markerRank = marker => marker.marker_kind === 'entry' ? 3 : marker.marker_kind === 'setup' ? 2 : 1
  const preferMarker = (current, candidate) => {
    if (!current) return candidate
    const rank = markerRank(candidate)
    const currentRank = markerRank(current)
    const score = Number(candidate.quality_score || candidate.strength || 0)
    const currentScore = Number(current.quality_score || current.strength || 0)
    if (rank !== currentRank) return rank > currentRank ? candidate : current
    if (score !== currentScore) return score > currentScore ? candidate : current
    return candidate.persistent ? candidate : current
  }
  markers.forEach(marker => {
    const side = String(marker.entry_side || marker.direction || '').toUpperCase()
    const key = marker.zone_key || marker.event_id || marker.id || `${Number(marker.time)}:${side}`
    merged.set(key, preferMarker(merged.get(key), marker))
  })

  const persistent = [...merged.values()]
    .filter(marker => marker.persistent)
    .sort((left, right) => Number(left.time) - Number(right.time))
  const persistentCoordinates = new Set(persistent.map(marker => (
    `${Number(marker.time)}:${String(marker.entry_side || marker.direction || '').toUpperCase()}`
  )))
  const timeframeSeconds = {
    '1M': 60,
    '5M': 300,
    '15M': 900,
    '1H': 3600,
    '4H': 14400,
    '1D': 86400,
  }[String(timeframe || '15M').toUpperCase()] || 900
  const clusterBars = {
    '1M': 4,
    '5M': 4,
    '15M': 3,
    '1H': 2,
    '4H': 2,
    '1D': 1,
  }[String(timeframe || '15M').toUpperCase()] || 3
  const clusterWindow = timeframeSeconds * clusterBars
  const clusters = []

  ;[...merged.values()]
    .filter(marker => !marker.persistent)
    .filter(marker => !persistentCoordinates.has(
      `${Number(marker.time)}:${String(marker.entry_side || marker.direction || '').toUpperCase()}`,
    ))
    .sort((left, right) => Number(left.time) - Number(right.time))
    .forEach(marker => {
      const side = String(marker.entry_side || marker.direction || '').toUpperCase()
      const time = Number(marker.time)
      const cluster = [...clusters].reverse().find(item => {
        return item.side === side && time - item.startTime <= clusterWindow
      })
      if (!cluster) {
        clusters.push({
          side,
          startTime: time,
          marker,
          count: 1,
          hasPersistent: Boolean(marker.persistent),
        })
        return
      }
      cluster.marker = preferMarker(cluster.marker, marker)
      cluster.count += 1
      cluster.hasPersistent = cluster.hasPersistent || Boolean(marker.persistent)
    })

  const compacted = clusters.map(cluster => ({
    ...cluster.marker,
    persistent: cluster.hasPersistent,
    cluster_count: cluster.count,
    marker_title: cluster.count > 1
      ? `${cluster.marker.marker_title || 'Diamond zone'} / strongest of ${cluster.count} nearby observations`
      : cluster.marker.marker_title,
  })).sort((left, right) => Number(left.time) - Number(right.time))

  const flipWindow = timeframeSeconds * ({
    '1M': 6,
    '5M': 5,
    '15M': 3,
    '1H': 2,
    '4H': 1,
    '1D': 1,
  }[String(timeframe || '15M').toUpperCase()] || 3)
  const compactedTransient = compacted.reduce((selected, marker) => {
    const previous = selected[selected.length - 1]
    if (!previous) return [marker]
    const previousSide = String(previous.entry_side || previous.direction || '').toUpperCase()
    const side = String(marker.entry_side || marker.direction || '').toUpperCase()
    if (side !== previousSide && Number(marker.time) - Number(previous.time) <= flipWindow) {
      const preferred = preferMarker(previous, marker)
      selected[selected.length - 1] = {
        ...preferred,
        cluster_count: Number(previous.cluster_count || 1) + Number(marker.cluster_count || 1),
        marker_title: `${preferred.marker_title || 'Diamond zone'} / strongest nearby reversal proof`,
      }
      return selected
    }
    selected.push(marker)
    return selected
  }, [])
  return [...persistent, ...compactedTransient]
    .sort((left, right) => Number(left.time) - Number(right.time))
}

function MtfMarketMap({ snapshot }) {
  const rows = safeArray(snapshot?.timeframes)
  if (!rows.length) return null
  return (
    <section className="mtf-market-map" aria-label="Multi-timeframe market map">
      <header>
        <span><Waypoints size={13} /> MTF Market Map</span>
        <strong className={tone(snapshot?.bias)}>{snapshot?.bias || 'MIXED'}</strong>
        <b>{Number(snapshot?.confluence_score) > 0 ? '+' : ''}{snapshot?.confluence_score ?? 0}</b>
        <em className={snapshot?.sources_matched ? 'good' : 'warn'}>{snapshot?.sources_matched ? 'MATCHED' : 'RESEARCH'}</em>
      </header>
      <div className="mtf-market-grid">
        {rows.map(row => (
          <div key={row.timeframe} className={tone(row.trend)}>
            <span>{timeframeLabel(row.timeframe)}</span>
            <strong>{row.trend || 'WAITING'}</strong>
            <small>RSI {Number.isFinite(Number(row.rsi_14)) ? Number(row.rsi_14).toFixed(1) : '-'}</small>
            <b>{Number(row.score) > 0 ? '+' : ''}{row.score ?? 0}</b>
          </div>
        ))}
      </div>
    </section>
  )
}

function ConfidenceEnginePanel({ analysis, governance, alerts, onAcknowledge }) {
  const governanceState = safeObject(governance?.status ? governance : analysis?.strategy_governance)
  const alertState = safeObject(alerts)
  const summary = confidenceEngineSummary(analysis, governanceState, alertState)
  const funnel = safeObject(analysis?.key_zones?.gate_funnel)
  const decisionBlockers = safeArray(analysis?.decision_quality?.top_blockers)
  const blockers = (decisionBlockers.length ? decisionBlockers : safeArray(funnel.top_blockers)).slice(0, 3)
  const reconciliation = safeObject(analysis?.feed_reconciliation)
  const execution = safeObject(analysis?.execution_reality)
  const regime = safeObject(analysis?.market_regime)
  const regimeMetrics = safeObject(regime.metrics)
  const assetIntelligence = safeObject(analysis?.asset_intelligence)
  const assetTimeframes = safeObject(assetIntelligence.timeframes)
  const assetGate = String(assetIntelligence.execution_gate || 'OBSERVE').toUpperCase()
  const assetTone = assetGate === 'OPEN' ? 'good' : assetGate.startsWith('BLOCK_') ? 'bad' : 'warn'
  const champion = safeObject(governanceState.champion)
  const challenger = safeObject(governanceState.challenger)
  const promotion = safeObject(governanceState.promotion_gate)
  const latestAlert = safeArray(alertState.alerts)[0]
  const stageLabel = value => String(value || 'waiting').replaceAll('_', ' ')
  const progress = Math.max(0, Math.min(100, Number(promotion.progress_percent) || 0))
  const score = summary.decisionScore
  return (
    <section className="confidence-engine" aria-label="Confidence Engine diagnostics and strategy governance">
      <header>
        <span><ShieldCheck size={14} /> Confidence Engine</span>
        <strong>V3.8.7</strong>
        <em className={summary.tone}>{stageLabel(summary.status)}</em>
        <small>{summary.readinessPassed}/{summary.readinessTotal} execution gates ready</small>
      </header>
      <div className="decision-quality-strip">
        <div className={`decision-quality-score ${summary.tone}`}>
          <span>Decision Quality</span>
          <strong>{score == null ? '-' : score}<small>/100</small></strong>
          <em>Grade {summary.decisionGrade} / ceiling {summary.scoreCeiling || '-'}</em>
        </div>
        <div className="decision-quality-components">
          {summary.qualityComponents.length ? summary.qualityComponents.map(component => (
            <article key={component.id} title={`${component.label}: ${component.score}/${component.max_score}`}>
              <span>{component.label}</span>
              <strong>{component.percent ?? 0}%</strong>
              <i><b style={{ width: `${Math.max(0, Math.min(100, Number(component.percent) || 0))}%` }} /></i>
            </article>
          )) : (
            <article className="waiting"><span>Reliability Matrix</span><strong>Waiting</strong><i><b /></i></article>
          )}
        </div>
        <div className="decision-quality-next">
          <span>Next Best Action</span>
          <strong>{summary.nextBestAction}</strong>
          <small>{summary.readinessPassed}/{summary.readinessTotal} ready / {stageLabel(summary.eventFreshness)} / closed candles</small>
        </div>
      </div>
      <div className="confidence-engine-body">
        <div className="confidence-funnel">
          <div className="confidence-funnel-head">
            <span><strong>Gate Funnel</strong><small>Completed candles only</small></span>
            <b>{stageLabel(summary.currentGate)}</b>
            <em>{summary.nextGate ? `Next: ${stageLabel(summary.nextGate)}` : 'Entry confirmed'}</em>
          </div>
          <div className="confidence-stage-list">
            {summary.stages.map((stage, index) => (
              <div className={confidenceStageState(stage, summary)} key={stage.id} title={`${stage.label}: ${stage.count} (${stage.percent_of_scan ?? 0}% of scan)`}>
                <i>{index + 1}</i>
                <span>{stage.label}</span>
                <b>{stage.count ?? 0}</b>
              </div>
            ))}
          </div>
          <div className="confidence-blockers">
            <span>Live blockers</span>
            {blockers.length ? blockers.map(blocker => (
              <p key={`${blocker.component || 'funnel'}-${blocker.id}`} title={blocker.reason || `${blocker.percent_of_scan ?? 0}% of scanned candles`}>
                <strong>{blocker.label}</strong><b>{blocker.priority || blocker.count}</b>
              </p>
            )) : <p><strong>No blocker evidence yet</strong><b>-</b></p>}
          </div>
        </div>
        <aside className="confidence-audit-grid">
          <article className={`pro-analyze-card ${assetTone}`} title={assetIntelligence.reason || 'Waiting for asset-specific MTF intelligence'}>
            <span><Waypoints size={11} /> Pro Analyze V5</span>
            <strong>{String(assetIntelligence.profile || 'ASSET PROFILE WAITING').replaceAll('_', ' ')}</strong>
            <small>{String(assetIntelligence.consensus || 'WAIT').replaceAll('_', ' ')} / {assetIntelligence.agreement_percent ?? 0}% agreement / Quality {assetIntelligence.quality_score ?? 0}</small>
            <div className="pro-analyze-timeframes">
              {['1D', '4H', '1H', '15M', '5M'].map(item => {
                const snapshot = safeObject(assetTimeframes[item])
                return <b className={String(snapshot.direction || 'wait').toLowerCase()} key={item}>{timeframeLabel(item)} <em>{snapshot.direction || 'WAIT'}</em></b>
              })}
            </div>
            <i>{String(assetGate).replaceAll('_', ' ')}</i>
          </article>
          <article
            className={`regime-guard-card ${['OPEN', 'OPEN_RANGE_EDGE'].includes(regime.execution_gate) ? 'good' : String(regime.execution_gate || '').startsWith('BLOCK_') ? 'bad' : 'warn'}`}
            title={regime.reason || 'Waiting for completed-candle regime classification'}
          >
            <span><Activity size={11} /> Regime Guard</span>
            <strong>{stageLabel(regime.regime || 'waiting')} / {regime.strength ?? 0}%</strong>
            <small>{stageLabel(regime.execution_gate || 'observe')} / {stageLabel(regimeMetrics.range_location || 'location waiting')}</small>
            <div className="regime-guard-metrics">
              <b>Efficiency {Number.isFinite(Number(regimeMetrics.efficiency_ratio)) ? Number(regimeMetrics.efficiency_ratio).toFixed(2) : '-'}</b>
              <b>Volatility {Number.isFinite(Number(regimeMetrics.volatility_ratio)) ? Number(regimeMetrics.volatility_ratio).toFixed(2) : '-'}x</b>
              <b>Shock {Number.isFinite(Number(regimeMetrics.latest_range_atr)) ? Number(regimeMetrics.latest_range_atr).toFixed(2) : '-'} ATR</b>
              <b>Extension {Number.isFinite(Number(regimeMetrics.directional_extension_atr)) ? Number(regimeMetrics.directional_extension_atr).toFixed(2) : '-'} ATR</b>
            </div>
          </article>
          <article className={summary.trusted ? 'good' : 'bad'}>
            <span>Feed reconciliation</span>
            <strong>{stageLabel(reconciliation.status)}</strong>
            <small>{reconciliation.chart_source || 'Waiting for matched provider candles'}</small>
          </article>
          <article className={execution.research_trackable ? 'good' : 'warn'}>
            <span>Execution reality</span>
            <strong>{stageLabel(execution.status)}</strong>
            <small>{summary.brokerExecutable ? 'Live Bid/Ask verified' : 'Research only; no broker order'}</small>
          </article>
          <article className="governance-card">
            <span>Champion / Challenger</span>
            <strong>{String(champion.version || 'DIAMOND_V8_STRONG_TREND_GUARD').replace('DIAMOND_', '')} / {String(challenger.version || 'DIAMOND_V7.1_SHADOW').replace('DIAMOND_', '')}</strong>
            <small>{summary.challengerResolved}/{summary.promotionMinimum} shadow events resolved</small>
            <i><b style={{ width: `${progress}%` }} /></i>
            <em className={promotion.status === 'ELIGIBLE_FOR_MANUAL_REVIEW' ? 'good' : 'warn'}>{stageLabel(promotion.status || 'shadow only')}</em>
          </article>
          <article className={`confidence-alert ${latestAlert?.priority?.toLowerCase() || ''}`}>
            <span><Bell size={11} /> Closed-candle alert</span>
            <strong>{latestAlert?.title || 'No confirmed alert yet'}</strong>
            <small>{latestAlert ? `${timeframeLabel(latestAlert.timeframe)} / ${stageLabel(latestAlert.priority)}` : 'Deduplicated and in-app only'}</small>
            {latestAlert && !latestAlert.acknowledged && (
              <button onClick={() => onAcknowledge?.(latestAlert.id)} title="Mark alert as reviewed" aria-label="Mark alert as reviewed">
                <CheckCircle2 size={14} />
              </button>
            )}
          </article>
        </aside>
      </div>
    </section>
  )
}

function DiamondValidationPanel({ validation, onRun, loading }) {
  const summary = safeObject(validation?.summary)
  const replay = safeObject(validation?.replay_summary)
  const confidence = safeObject(validation?.sample_confidence)
  const dataRange = safeObject(validation?.data_range)
  const directionRows = safeArray(validation?.segments?.direction)
  const failure = safeObject(validation?.failure_diagnostics)
  const finalBlockers = safeArray(failure.final_blockers).slice(0, 3)
  const status = validation?.status || 'NOT_RUN'
  const isMetric = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
  const metric = (value, suffix = '') => isMetric(value) ? `${Number(value).toFixed(suffix ? 1 : 2)}${suffix}` : '-'
  const hasRun = ['READY', 'NO_CONFIRMED_EVENTS'].includes(status)
  return (
    <section className="diamond-validation" aria-label="Diamond closed-candle walk-forward validation">
      <header>
        <span><ShieldCheck size={14} /> History Engine Replay</span>
        <strong>{String(validation?.engine_version || 'DIAMOND V6.1').replaceAll('_', ' ')}</strong>
        <em className={confidence.status === 'EVIDENCE_READY' ? 'good' : 'warn'}>{String(confidence.status || status).replaceAll('_', ' ')}</em>
        <button onClick={onRun} disabled={loading} title="Analyze chart history with the current Diamond engine">
          <RefreshCw className={loading ? 'spin' : ''} size={13} />
          <span>{loading ? 'Analyzing' : hasRun ? 'Analyze Again' : 'Analyze History'}</span>
        </button>
      </header>
      {hasRun ? (
        <>
          {status === 'NO_CONFIRMED_EVENTS' && (
            <div className="validation-sample-note validation-diagnostics">
              <ShieldCheck size={13} />
              <span>
                <strong>{Number(replay.strategy_confirmed_setups) > 0 ? `${replay.strategy_confirmed_setups} confirmed setups replayed.` : 'No confirmed strategy setup in this sample.'}</strong>
                <small>{failure.interpretation || `${validation?.scan_count ?? 0} historical checkpoints were tested; score-only observations were excluded.`}</small>
              </span>
              {finalBlockers.length > 0 && (
                <div className="validation-blockers" aria-label="Final confirmation blockers">
                  {finalBlockers.map(blocker => (
                    <b key={blocker.id} title={String(blocker.id || '').replaceAll('_', ' ')}>
                      {blocker.label || String(blocker.id || 'Waiting sequence').replaceAll('_', ' ')} <em>{blocker.count}</em>
                    </b>
                  ))}
                </div>
              )}
            </div>
          )}
          <div className="validation-metrics">
            <p><span>Setups</span><strong>{replay.strategy_confirmed_setups ?? 0}</strong><small>Strategy confirmed</small></p>
            <p><span>Respected</span><strong className="good">{replay.respected ?? 0}</strong><small>{metric(replay.respect_rate, '%')} resolved rate</small></p>
            <p><span>Failed</span><strong className={Number(replay.failed) > 0 ? 'bad' : ''}>{replay.failed ?? 0}</strong><small>{replay.watching ?? 0} watching</small></p>
            <p><span>Entry Proof</span><strong>{summary.resolved ?? 0}</strong><small>{summary.confirmed_events ?? 0} confirmed</small></p>
            <p><span>Direction</span><strong>{replay.buy_zones ?? 0} / {replay.sell_zones ?? 0}</strong><small>Buy / Sell</small></p>
            <p><span>Coverage</span><strong>{dataRange.candles ?? 0}</strong><small>{timeframeLabel(validation?.timeframe)}</small></p>
          </div>
          <div className="validation-progress" title={`${confidence.resolved ?? 0} of ${confidence.minimum_evidence_sample ?? 100} resolved events`}>
            <span style={{ width: `${Math.max(0, Math.min(100, Number(confidence.progress_percent) || 0))}%` }} />
          </div>
          {directionRows.length > 0 && (
            <div className="validation-segments">
              {directionRows.map(row => (
                <p key={row.side}>
                  <span><Diamond size={10} /> {row.side}</span>
                  <strong>{row.resolved} resolved</strong>
                  <b>{row.win_rate == null ? '-' : `${row.win_rate}%`}</b>
                  <em>{row.expectancy_r == null ? '-' : `${row.expectancy_r}R`}</em>
                </p>
              ))}
            </div>
          )}
          <footer>
            <span>{validation?.source || '-'}</span>
            <strong>{dataRange.from ? new Date(dataRange.from).toLocaleDateString() : '-'} - {dataRange.to ? new Date(dataRange.to).toLocaleDateString() : '-'}</strong>
            <em>{validation?.cached ? 'CACHED EVIDENCE' : 'NEW EVIDENCE'}</em>
          </footer>
        </>
      ) : (
        <div className="diamond-validation-empty">
          <ShieldCheck size={22} />
          <strong>{status === 'INSUFFICIENT_DATA' ? 'More matched candles required' : 'No validation evidence yet'}</strong>
          <span>{validation?.candle_count ?? 0} / {validation?.required_candles ?? 0} closed candles</span>
        </div>
      )}
    </section>
  )
}

function DiamondHistoryPanel({ history, onReplay, replayKey }) {
  const entries = safeArray(history?.entries).slice(0, 12)
  const stats = safeObject(history?.stats)
  const lifecycle = safeObject(stats.lifecycle)
  const calibration = safeObject(history?.calibration)
  const profiles = safeArray(calibration.profiles).slice(0, 3)
  const lifecycleStages = [
    { id: 'detected', label: 'Detected', value: lifecycle.detected ?? stats.total ?? 0 },
    { id: 'qualified', label: 'Qualified', value: lifecycle.qualified ?? 0 },
    { id: 'confirmed', label: 'Confirmed', value: lifecycle.confirmed ?? stats.confirmed ?? 0 },
    { id: 'active', label: 'Watching', value: Number(lifecycle.monitoring || 0) + Number(lifecycle.open || 0) },
    { id: 'resolved', label: 'Resolved', value: lifecycle.resolved ?? 0 },
  ]
  const resultTone = status => (
    status === 'WON' ? 'good'
      : status === 'LOST' ? 'bad'
        : ['AMBIGUOUS', 'EXPIRED', 'EXPIRED_NO_ENTRY', 'INVALIDATED_NO_ENTRY', 'CANCELLED'].includes(status) ? 'warn'
          : ''
  )
  return (
    <section className="diamond-history evidence-ledger" aria-label="V3 Diamond evidence and lifecycle ledger">
      <header>
        <span><ShieldCheck size={13} /> Evidence Ledger</span>
        <strong>Diamond Lifecycle V3</strong>
        <em>{stats.verified_accuracy == null ? 'Evidence sample developing' : `${stats.verified_accuracy}% verified win rate`}</em>
        <small>{stats.total ?? entries.length} preserved / {stats.matched ?? 0} matched / Eligible avg {stats.average_diamond_score ?? '-'} / {stats.rejected_observations ?? 0} internal rejects</small>
      </header>
      <div className="diamond-ledger-content">
        <div className="diamond-ledger-overview">
          <div className="diamond-lifecycle-strip" aria-label="Diamond lifecycle counts">
            {lifecycleStages.map((stage, index) => (
              <p key={stage.id}>
                <i>{index + 1}</i>
                <span>{stage.label}</span>
                <strong>{stage.value}</strong>
              </p>
            ))}
          </div>
          <div className="diamond-calibration-strip" aria-label="Scalp and Swing evidence calibration">
            {profiles.length ? profiles.map(profile => (
              <p key={profile.style}>
                <span>{profile.style === 'SCALPING' ? 'Scalp' : profile.style === 'SWING' ? 'Swing' : 'Position'} <small>{safeArray(profile.timeframes).join(' / ')}</small></span>
                <strong>{profile.resolved ?? 0} resolved</strong>
                <b>{profile.win_rate == null ? '-' : `${profile.win_rate}%`}</b>
                <em>{profile.expectancy_r == null ? '-' : `${profile.expectancy_r}R`}</em>
                <i className={profile.sample_status === 'EVIDENCE_READY' ? 'good' : 'warn'}>{String(profile.sample_status || 'INSUFFICIENT_SAMPLE').replaceAll('_', ' ')}</i>
              </p>
            )) : <p><span>Calibration</span><strong>Waiting for confirmed entries</strong><i className="warn">INSUFFICIENT SAMPLE</i></p>}
          </div>
        </div>
        {entries.length ? (
          <div className="diamond-history-list">
            {entries.map(entry => {
              const evidence = safeObject(entry.evidence_snapshot)
              const evidenceRegime = safeObject(evidence.regime)
              const evidenceDecision = safeObject(evidence.decision)
              const evidenceMarket = safeObject(evidence.market)
              const horizons = safeObject(entry.forward_returns?.horizons)
              const forwardPrefix = entry.forward_returns?.basis === 'EVENT_ENTRY' ? 'E' : 'C'
              const timeline = safeArray(entry.lifecycle_events).slice(-5)
              const diamondScore = clampPercent(entry.diamond_score ?? entry.event_quality ?? entry.zone_strength ?? entry.origin_quality)
              const scoreFloor = diamondVisibleFloor(entry)
              const diamondGrade = entry.diamond_grade || entry.precision_grade || diamondGradeFromScore(diamondScore, false, scoreFloor)
              const gradeLabel = diamondGradeLabel(diamondGrade, diamondScore, scoreFloor)
              const gradeTone = diamondGrade === 'A+' || diamondGrade === 'A'
                ? 'elite'
                : diamondGrade === 'B' ? 'strong' : gradeLabel ? 'developing' : 'failed'
              return (
                <article className={`${String(entry.entry_side || '').toLowerCase()} ${resultTone(entry.verification_status)} ${replayKey === entry.zone_key ? 'replaying' : ''}`} key={entry.zone_key} title={entry.note}>
                  <button className="diamond-history-replay" onClick={() => onReplay?.(entry)} title="Replay this Diamond on chart" aria-label={`Replay ${entry.entry_side} Diamond on chart`}>
                    <ChartSpline size={13} />
                  </button>
                  <div>
                    <time>{new Date(entry.origin_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time>
                    <b>{timeframeLabel(entry.timeframe)}</b>
                  </div>
                  <div className="diamond-history-grade-row">
                    <span>{String(entry.lifecycle_stage || entry.display_classification || entry.classification || 'CONTEXT').replaceAll('_', ' ')}</span>
                    <b className={gradeTone}>{gradeLabel ? `Grade ${diamondGrade} / ${diamondScore}` : 'Rejected by score gate'}</b>
                  </div>
                  <strong><Diamond size={11} /> {entry.entry_side} {asPrice(entry.line)}</strong>
                  <small>Zone {asPrice(entry.zone_low)} - {asPrice(entry.zone_high)}</small>
                  <p title="Historical audit levels, not a live trade recommendation"><i>AE</i>{asPrice(entry.entry_price)} <i>AS</i>{asPrice(entry.stop_price)} <i>AT</i>{asPrice(entry.target_price)}</p>
                  <div className="diamond-evidence-facts">
                    <span>{String(evidenceRegime.name || entry.evidence_regime || 'UNKNOWN').replaceAll('_', ' ')}</span>
                    <b>DQ {evidenceDecision.score ?? entry.evidence_decision_score ?? '-'}</b>
                    <em>{String(evidenceMarket.session || entry.evidence_market_session || 'UNKNOWN').replaceAll('_', ' ')}</em>
                  </div>
                  <div className="diamond-forward-returns" title={forwardPrefix === 'E' ? 'Confirmed-entry directional return after later completed candles' : 'Context movement only; not an entry outcome'}>
                    {['5', '10', '20'].map(bars => (
                      <span className={Number(horizons[bars]?.directional_pct) > 0 ? 'good' : Number(horizons[bars]?.directional_pct) < 0 ? 'bad' : ''} key={bars}>
                        {forwardPrefix}+{bars} {horizons[bars]?.available ? `${horizons[bars].directional_pct}%` : '-'}
                      </span>
                    ))}
                  </div>
                  <div className="diamond-lifecycle-timeline" aria-label="Diamond lifecycle timeline">
                    {timeline.map(item => <i className={resultTone(item.stage)} key={`${item.stage}-${item.at}`} title={`${String(item.stage).replaceAll('_', ' ')} / ${item.note}`}><b /></i>)}
                  </div>
                  <footer>
                    <em title={`${entry.strategy || 'Legacy Diamond'} / ${entry.profile || '-'} / ${entry.configuration_fingerprint || 'no fingerprint'}`}>Origin {entry.quality_grade || '-'} / {entry.origin_quality ?? '-'} / {String(entry.engine_version || 'LEGACY').replace('DIAMOND_', '')}</em>
                    <b className={resultTone(entry.verification_status)}>{String(entry.verification_status || 'MONITORING').replaceAll('_', ' ')}</b>
                    <small className={entry.feed_matched ? 'good' : 'warn'}>{entry.feed_matched ? 'MATCHED' : 'RESEARCH'}</small>
                  </footer>
                </article>
              )
            })}
          </div>
        ) : (
          <div className="diamond-history-empty">Diamond V7 proof begins after the first completed-candle context is preserved.</div>
        )}
      </div>
    </section>
  )
}

function SimpleDiamondHistory({ history, onReplay, replayKey }) {
  const [filter, setFilter] = useState('ALL')
  const [visibleCount, setVisibleCount] = useState(24)
  const entries = safeArray(history?.entries)
  const stats = safeObject(history?.stats)
  const lifecycle = safeObject(stats.lifecycle)
  const openCount = Number(lifecycle.monitoring || 0) + Number(lifecycle.open || 0)
  const invalidCount = Number(lifecycle.invalidated || 0) + Number(lifecycle.expired || 0) + Number(lifecycle.ambiguous || 0)
  const statusGroup = status => {
    const value = String(status || 'MONITORING').toUpperCase()
    if (value === 'WON') return 'HELD'
    if (['MONITORING', 'OPEN', 'WAITING_ENTRY'].includes(value)) return 'PENDING'
    return 'FAILED'
  }
  const filtered = entries.filter(entry => filter === 'ALL' || statusGroup(entry.verification_status) === filter)
  const visible = filtered.slice(0, visibleCount)
  const tone = status => statusGroup(status) === 'HELD' ? 'good' : statusGroup(status) === 'FAILED' ? 'bad' : 'warn'

  useEffect(() => {
    setFilter('ALL')
    setVisibleCount(24)
  }, [history?.symbol])

  return (
    <section className="diamond-audit" aria-label="Diamond Zone history">
      <header className="diamond-audit-head">
        <div>
          <span><Diamond size={14} /> Diamond History</span>
          <strong>Every saved zone stays available for review</strong>
          <small>Wins and losses use fixed audit targets on later completed candles. These are evidence levels, not live TP/SL recommendations.</small>
        </div>
        <div className="diamond-audit-stats">
          <p><span>Saved</span><strong>{stats.total ?? entries.length}</strong></p>
          <p className="good"><span>Held</span><strong>{stats.won ?? 0}</strong></p>
          <p className="bad"><span>Failed</span><strong>{Number(stats.lost || 0) + invalidCount}</strong></p>
          <p className="warn"><span>Pending</span><strong>{openCount}</strong></p>
          <p><span>Resolved</span><strong>{Number(stats.won || 0) + Number(stats.lost || 0)}</strong></p>
        </div>
      </header>
      <div className="diamond-audit-controls" role="group" aria-label="Filter Diamond history">
        {[
          ['ALL', 'All', stats.total ?? entries.length],
          ['HELD', 'Held', stats.won ?? 0],
          ['FAILED', 'Failed', Number(stats.lost || 0) + invalidCount],
          ['PENDING', 'Pending', openCount],
        ].map(([id, label, value]) => (
          <button className={filter === id ? 'active' : ''} key={id} onClick={() => { setFilter(id); setVisibleCount(24) }}>
            <span>{label}</span><b>{value}</b>
          </button>
        ))}
      </div>
      {visible.length ? (
        <div className="diamond-audit-list">
          {visible.map(entry => {
            const score = clampPercent(diamondHistoricalScore(entry))
            const grade = entry.peak_diamond_grade || entry.diamond_grade || diamondGradeFromScore(score, false, diamondVisibleFloor(entry)) || '-'
            const status = statusGroup(entry.verification_status)
            const side = String(entry.entry_side || entry.direction || 'WAIT').toUpperCase()
            return (
              <article className={`${side.toLowerCase()} ${tone(entry.verification_status)} ${replayKey === entry.zone_key ? 'replaying' : ''}`} key={entry.zone_key}>
                <div className="diamond-audit-identity">
                  <span><Diamond size={12} /> {side}</span>
                  <strong>{asPrice(entry.line)}</strong>
                  <b>Grade {grade} / {score}</b>
                </div>
                <div className="diamond-audit-meta">
                  <time>{new Date(entry.origin_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time>
                  <span>{timeframeLabel(entry.timeframe)}</span>
                  <em>{String(entry.origin_model || 'STRUCTURAL ZONE').replaceAll('_', ' ')}</em>
                </div>
                <div className="diamond-audit-levels">
                  <p><span>Audit Entry</span><strong>{asPrice(entry.entry_price)}</strong></p>
                  <p><span>Audit Stop</span><strong>{asPrice(entry.stop_price)}</strong></p>
                  <p><span>Audit Target</span><strong>{asPrice(entry.target_price)}</strong></p>
                </div>
                <footer>
                  <b className={tone(entry.verification_status)}>{status}</b>
                  <span>{entry.outcome_r == null ? 'Audit pending' : `${entry.outcome_r}R`}</span>
                  <em className={entry.feed_matched ? 'good' : 'warn'}>{entry.feed_matched ? 'MATCHED' : 'RESEARCH'}</em>
                  <button onClick={() => onReplay?.(entry)} title="Replay this Diamond on chart"><ChartSpline size={13} /><span>Replay</span></button>
                </footer>
              </article>
            )
          })}
        </div>
      ) : <div className="diamond-history-empty">No Diamond records match this filter.</div>}
      {filtered.length > visibleCount && (
        <button className="diamond-audit-more" onClick={() => setVisibleCount(count => count + 24)}>
          Show older Diamonds <b>{filtered.length - visibleCount}</b>
        </button>
      )}
    </section>
  )
}

function setupValidationGates(analysis) {
  const integrity = safeObject(analysis?.data_integrity_check)
  const htf = safeObject(analysis?.htf_bias)
  const liquidity = safeObject(analysis?.liquidity_map)
  const poi = safeObject(analysis?.poi_engine)
  const confirmation = safeObject(analysis?.confirmation_engine)
  const scoreEngine = safeObject(analysis?.score_engine || analysis?.smart_score_v2)
  const score = Number(scoreEngine.score ?? analysis?.signal?.score ?? analysis?.score)
  const bias = htf.bias || analysis?.bias
  const trustGate = safeObject(analysis?.trust_gate)
  const providerAlignment = safeObject(analysis?.provider_alignment)
  const news = safeObject(analysis?.news_intelligence)
  const xauPrecision = safeObject(analysis?.xau_confluence)
  const diamondAutoEntry = safeObject(analysis?.diamond_auto_entry)
  const smr = safeObject(analysis?.smr_model || analysis?.key_zones?.smr_model)
  const smrProfile = safeObject(smr.profile)
  const smrGate = String(smr.execution_gate || 'WATCH').toUpperCase()
  const dualCore = safeObject(analysis?.diamond_timeframe_model || analysis?.key_zones?.diamond_timeframe_model)
  const dualCoreGate = String(dualCore.execution_gate || 'WATCH').toUpperCase()
  const kTrend = safeObject(analysis?.session_framework?.k_trend)
  const intendedDirection = String(analysis?.trade_plan?.direction || analysis?.signal?.direction || 'WAIT').toUpperCase()
  const kTrendAligned = kTrend.status === 'READY' && kTrend.confirmation === 'CONFIRMED' && (
    (intendedDirection === 'BUY' && kTrend.regime === 'BULLISH') ||
    (intendedDirection === 'SELL' && kTrend.regime === 'BEARISH')
  )
  const integrityStatus = integrity.status || analysis?.data_mode || 'WAITING'
  const verifiedDataState = (
    providerAlignment.matched === true &&
    analysis?.data_mode === 'REAL_MODE' &&
    ['READY', 'VALID', 'REAL_MODE', 'FULL_ANALYSIS_READY'].includes(integrityStatus)
  )
  const liquiditySweep = liquidity.liquidity_sweep
  const normalizedSweep = String(liquiditySweep ?? '').trim().toLowerCase().replaceAll(' ', '_')
  const hasLiquiditySweep = liquiditySweep === true || (
    Boolean(normalizedSweep) && !['false', 'none', 'no_sweep', 'no_liquidity_sweep', 'waiting'].includes(normalizedSweep)
  )
  const gates = [
    {
      label: 'Data Trust',
      timeframe: 'All',
      pass: trustGate.trusted === true || verifiedDataState,
      reason: trustGate.reason || providerAlignment.reason || integrity.reason || 'Matched provider and clean timeframe audits are required.',
    },
    {
      label: 'Market Data',
      timeframe: 'All',
      pass: analysis?.analysis_ready === true || ['VALID', 'READY', 'REAL_MODE', 'FULL_ANALYSIS_READY'].includes(integrityStatus),
      reason: integrity.reason || (analysis ? `Source: ${analysis.analysis_data_source || analysis.data_mode || 'pending'}` : 'Auto Engine is waiting to validate candle history.'),
    },
    {
      label: 'HTF Direction',
      timeframe: '1D / 4H',
      pass: ['Bullish', 'Bearish'].includes(bias),
      reason: htf.reason || (bias ? `${bias} market structure.` : 'Waiting for a clear higher-timeframe bias.'),
    },
    {
      label: 'Liquidity Sweep',
      timeframe: '1H',
      pass: hasLiquiditySweep,
      reason: liquidity.reason || 'Waiting for mapped liquidity to be swept.',
    },
    {
      label: 'Valid POI',
      timeframe: '15M',
      pass: Boolean(poi.best_poi),
      reason: poi.reason || (poi.best_poi?.type ? `${poi.best_poi.type} detected.` : 'Waiting for a directional FVG, order block, or OTE zone.'),
    },
    {
      label: 'Entry Confirmation',
      compactLabel: 'Confirmation',
      timeframe: '5M',
      pass: confirmation.confirmation_ready === true,
      reason: confirmation.reason || 'Waiting for BOS/CHOCH with displacement or retest.',
    },
    {
      label: 'Quality Score',
      timeframe: 'All',
      pass: Number.isFinite(score) && score >= 75,
      reason: Number.isFinite(score) ? `${clampPercent(score)}/100. Minimum actionable score is 75.` : 'Score is available after analysis.',
    },
    ...(analysis?.symbol === 'XAUUSD' ? [{
      label: 'K-Range Trend',
      compactLabel: 'K Trend',
      timeframe: 'Session',
      pass: kTrendAligned,
      reason: kTrend.status === 'READY'
        ? `${kTrend.regime || 'RANGE'} ${kTrend.score ?? 0}; ${String(kTrend.confirmation || 'WAITING').replaceAll('_', ' ')}; next ${kTrend.next_target_label || '-'}.`
        : 'Waiting for 35 completed intraday candles.',
    }] : []),
    ...(xauPrecision.status === 'READY' ? [{
      label: 'XAU Confluence',
      compactLabel: 'XAU Matrix',
      timeframe: '1D - 5M',
      pass: xauPrecision.execution_gate === 'OPEN',
      reason: xauPrecision.next_trigger || 'All XAU engines must agree before execution.',
    }] : []),
    ...(smr.status ? [{
      label: 'SMR Timing Guard',
      compactLabel: 'SMR',
      timeframe: smrProfile.execution_timeframe || 'Closed',
      pass: !['WAIT_SESSION', 'BLOCK_CONFLICT'].includes(smrGate),
      reason: `${String(smr.pattern_state || smr.status).replaceAll('_', ' ')} / ${smr.next_trigger || 'Monitoring the next completed-candle sequence.'}`,
    }] : []),
    ...(dualCore.status ? [{
      label: 'Diamond Dual-Core',
      compactLabel: `${dualCore.focus_timeframe || 'Core'} Core`,
      timeframe: dualCore.focus_timeframe || '5M / 1H',
      pass: !['BLOCK_CONFLICT', 'WAIT_VOLATILITY', 'WAIT_SESSION'].includes(dualCoreGate),
      reason: `${String(dualCore.state || dualCore.status).replaceAll('_', ' ')} / ${dualCore.next_trigger || 'Monitoring completed-candle core alignment.'}`,
    }] : []),
    {
      label: 'Diamond Auto Entry',
      compactLabel: 'Auto Entry',
      timeframe: analysis?.key_zones?.timeframe || 'Closed',
      pass: diamondAutoEntry.status === 'AUTO_ARMED',
      reason: diamondAutoEntry.next_trigger || 'Waiting for a trusted Diamond retest and full engine agreement.',
    },
    {
      label: 'News Window',
      compactLabel: 'News Risk',
      timeframe: 'Live',
      pass: news.execution_gate !== 'BLOCK_NEW_ENTRIES',
      reason: news.summary || 'Scheduled macro-news risk is checked before entry.',
    },
  ]
  return gates
}

function ExecutionGateStrip({ analysis }) {
  const readinessGates = executionReadinessGates(analysis)
  const gates = readinessGates.length ? readinessGates : setupValidationGates(analysis)
  const passed = gates.filter(gate => gate.pass).length
  const nextGate = gates.find(gate => !gate.pass)
  const complete = passed === gates.length
  return (
    <section className={`execution-gate-strip ${complete ? 'ready' : ''}`} aria-label="Execution gate status">
      <header>
        <ShieldCheck size={15} />
        <span>
          <small>{readinessGates.length ? 'Execution Readiness' : 'Execution Gate'}</small>
          <strong>{complete ? 'Actionable setup ready' : nextGate ? `Next: ${nextGate.label}` : 'Auto Engine waiting'}</strong>
        </span>
        <b>{passed}/{gates.length}</b>
      </header>
      <div className="execution-gate-list" style={{ '--gate-count': gates.length }}>
        {gates.map(gate => (
          <div className={gate.pass ? 'pass' : 'wait'} key={gate.label} title={gate.reason}>
            {gate.pass ? <CheckCircle2 size={13} /> : <CircleDashed size={13} />}
            <span><strong>{gate.compactLabel || gate.label}</strong><small>{gate.timeframe}</small></span>
          </div>
        ))}
      </div>
    </section>
  )
}

function SetupTrackerPanel({ tracker }) {
  const setups = safeArray(tracker?.setups)
  const stats = safeObject(tracker?.stats)
  const current = setups.find(item => ['WAITING_ENTRY', 'OPEN'].includes(item.lifecycle_status)) || setups[0]
  const status = current?.lifecycle_status || 'NO_TRACKED_SETUP'
  const statusTone = ['WON', 'OPEN'].includes(status) ? 'good' : ['LOST'].includes(status) ? 'bad' : ['WAITING_ENTRY', 'AMBIGUOUS'].includes(status) ? 'warn' : ''
  return (
    <section className="setup-tracker" aria-label="Verified Diamond V7 outcome tracker">
      <header>
        <span>Diamond Tracker</span>
        <strong>V7 confirmed entries only</strong>
        <em>Closed candle verified</em>
      </header>
      <div className="setup-tracker-stats">
        <p><span>Active</span><strong>{stats.active ?? 0}</strong></p>
        <p><span>Won / Lost</span><strong>{stats.won ?? 0} / {stats.lost ?? 0}</strong></p>
        <p><span>Win Rate</span><strong>{stats.verified_win_rate == null ? '-' : `${stats.verified_win_rate}%`}</strong></p>
        <p><span>Net R</span><strong className={Number(stats.net_r) >= 0 ? 'good' : 'bad'}>{stats.net_r ?? 0}R</strong></p>
      </div>
      {current ? (
        <div className="setup-tracker-current">
          <div className="setup-tracker-state">
            <span className={statusTone}>{String(status).replaceAll('_', ' ')}</span>
            <strong>{current.direction} Diamond</strong>
            <small>{current.symbol} / {current.timeframe} / {current.quality_tier || '-'}</small>
          </div>
          <p><span>Entry</span><strong>{asPrice(current.entry_price)}</strong></p>
          <p><span>Stop</span><strong className="bad">{asPrice(current.stop_loss)}</strong></p>
          <p><span>Target</span><strong className="good">{asPrice(current.target_1)}</strong></p>
          <p><span>R:R</span><strong>{current.risk_reward ? `1:${Number(current.risk_reward).toFixed(2)}` : '-'}</strong></p>
          <em title={current.note}>{current.note || 'Waiting for a completed provider candle.'}</em>
        </div>
      ) : (
        <div className="setup-tracker-empty">
          No confirmed Diamond V7 entry yet. Context zones and generic limit candidates are not counted as wins or losses.
        </div>
      )}
    </section>
  )
}

function SessionFrameworkPanel({ framework }) {
  const levels = safeObject(framework?.levels)
  const kTrend = safeObject(framework?.k_trend)
  if (framework?.status !== 'READY') {
    return (
      <section className="session-framework waiting">
        <header><span><ChartSpline size={13} /> SH K-Range Trend</span><strong>Waiting for daily session data</strong></header>
      </section>
    )
  }
  return (
    <section className="session-framework" aria-label="Transparent SH K-Range trend and target levels">
      <header>
        <span><ChartSpline size={13} /> SH K-Range Trend</span>
        <strong className={tone(kTrend.regime || framework.stance)}>{kTrend.regime || framework.stance}</strong>
        <b>{Number(kTrend.score) > 0 ? '+' : ''}{kTrend.score ?? framework.confluence_score}</b>
        <em>{String(kTrend.confirmation || framework.position || '-').replaceAll('_', ' ')} / next {kTrend.next_target_label || '-'}</em>
      </header>
      <div className="session-framework-levels">
        <p><span>OP</span><strong>{asPrice(levels.op)}</strong></p>
        <p><span>K -1</span><strong className="bad">{asPrice(levels.k_minus_1 ?? levels.dr_minus_1)}</strong></p>
        <p><span>K +1</span><strong className="good">{asPrice(levels.k_plus_1 ?? levels.dr_plus_1)}</strong></p>
        <p><span>K -3 / K +3</span><strong>{asPrice(levels.k_minus_3)} / {asPrice(levels.k_plus_3)}</strong></p>
        <p><span>Next Target</span><strong className={kTrend.regime === 'BEARISH' ? 'bad' : kTrend.regime === 'BULLISH' ? 'good' : ''}>{kTrend.next_target_label || '-'} {asPrice(kTrend.next_target)}</strong></p>
        <p><span>ATR 14 / Strength</span><strong>{asPrice(framework.daily_atr_14)} / {kTrend.strength ?? 0}</strong></p>
      </div>
    </section>
  )
}

function NewsRiskPanel({ news }) {
  const event = safeObject(news?.primary_event || news?.next_high_impact_event || news?.next_event)
  const feed = safeObject(news?.feed)
  if (!news || news.status === 'UNAVAILABLE') {
    return (
      <section className="news-risk-panel waiting">
        <header>
          <CalendarClock size={15} />
          <span><small>Macro News Radar</small><strong>Scheduled calendar unavailable</strong></span>
          <b>UNKNOWN</b>
          <em>Technical analysis remains active without a news veto.</em>
        </header>
      </section>
    )
  }
  const risk = news.risk_level || 'CLEAR'
  const riskClass = risk === 'HIGH' ? 'high' : risk === 'ELEVATED' ? 'elevated' : 'clear'
  return (
    <section className={`news-risk-panel ${riskClass}`} aria-label="Scheduled macro-news risk intelligence">
      <header>
        <CalendarClock size={15} />
        <span><small>Macro News Radar</small><strong title={event.title}>{event.title || 'Calendar clear'}</strong></span>
        <b>{risk}</b>
        <em>{event.countdown || news.state?.replaceAll('_', ' ') || '-'} / {news.upcoming_event_count ?? 0} upcoming / {feed.status || '-'}</em>
      </header>
      <div className="news-risk-metrics">
        <p><span>Release</span><strong>{formatNewsTime(event.timestamp)}</strong></p>
        <p><span>Impact</span><strong className={riskClass === 'high' ? 'bad' : riskClass === 'elevated' ? 'warn' : 'good'}>{event.impact || '-'}</strong></p>
        <p><span>Relevance</span><strong>{event.relevance_score ?? 0}/100</strong></p>
        <p><span>Forecast</span><strong>{event.forecast || '-'}</strong></p>
        <p><span>Previous</span><strong>{event.previous || '-'}</strong></p>
        <p><span>Entry Gate</span><strong className={tone(news.execution_gate)}>{String(news.execution_gate || 'OPEN').replaceAll('_', ' ')}</strong></p>
        <p title={event.scenario || news.summary}><span>Scenario</span><strong>{event.scenario || news.summary || '-'}</strong></p>
      </div>
    </section>
  )
}

const NEWS_CALENDAR_FILTERS = [
  ['ALL', 'All'],
  ['RELEASED', 'Released'],
  ['RELEVANT', 'Relevant'],
  ['USD', 'USD'],
  ['HIGH', 'High'],
]

const flagDataUrl = markup => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`
const CURRENCY_FLAG_ASSETS = {
  AUD: flagDataUrl(AustraliaFlag),
  CAD: flagDataUrl(CanadaFlag),
  CHF: flagDataUrl(SwitzerlandFlag),
  CNY: flagDataUrl(ChinaFlag),
  EUR: flagDataUrl(EuropeFlag),
  GBP: flagDataUrl(UnitedKingdomFlag),
  JPY: flagDataUrl(JapanFlag),
  NZD: flagDataUrl(NewZealandFlag),
  USD: flagDataUrl(UnitedStatesFlag),
}

function CurrencyIdentity({ currency }) {
  const code = String(currency || 'ALL').toUpperCase()
  const flagAsset = CURRENCY_FLAG_ASSETS[code]
  return (
    <span className={`currency-identity ${code === 'USD' ? 'usd' : ''}`} title={`${code} economic event`}>
      <i aria-hidden="true">
        {flagAsset ? <img src={flagAsset} alt="" loading="lazy" decoding="async" /> : code === 'ALL' ? <Globe2 size={15} /> : <Coins size={15} />}
      </i>
      <b>{code}</b>
    </span>
  )
}

function WeeklyNewsDrawer({ open, asset, calendar, loading, error, onRefresh, onClose }) {
  const [day, setDay] = useState('ALL')
  const [filter, setFilter] = useState('ALL')
  const [query, setQuery] = useState('')
  const events = safeArray(calendar?.events)
  const stats = safeObject(calendar?.stats)
  const feed = safeObject(calendar?.feed)

  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = event => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  useEffect(() => {
    if (open) {
      setDay('ALL')
      setQuery('')
    }
  }, [open, asset, calendar?.week_start])

  const days = useMemo(() => {
    const seen = new Map()
    events.forEach(event => {
      const key = newsDateKey(event.timestamp)
      if (!seen.has(key)) seen.set(key, event.timestamp)
    })
    return [...seen.entries()].map(([key, timestamp]) => ({ key, timestamp }))
  }, [events])

  const visibleEvents = useMemo(() => events.filter(event => {
    if (day !== 'ALL' && newsDateKey(event.timestamp) !== day) return false
    if (filter === 'RELEASED' && event.release_status !== 'RELEASED') return false
    if (filter === 'RELEVANT' && !event.is_relevant) return false
    if (filter === 'USD' && event.currency !== 'USD') return false
    if (filter === 'HIGH' && event.impact !== 'HIGH') return false
    const needle = query.trim().toLowerCase()
    if (needle && !`${event.title || ''} ${event.currency || ''} ${event.category || ''}`.toLowerCase().includes(needle)) return false
    return true
  }), [events, day, filter, query])

  const groupedEvents = useMemo(() => {
    const groups = []
    visibleEvents.forEach(event => {
      const key = newsDateKey(event.timestamp)
      let group = groups.at(-1)
      if (!group || group.key !== key) {
        group = { key, timestamp: event.timestamp, events: [] }
        groups.push(group)
      }
      group.events.push(event)
    })
    return groups
  }, [visibleEvents])

  if (!open) return null
  const weekRange = events.length
    ? `${newsDayLabel(events[0]?.timestamp, true)} - ${newsDayLabel(events.at(-1)?.timestamp, true)}`
    : 'This week'
  return (
    <aside className="weekly-news-drawer open" onMouseDown={event => event.target === event.currentTarget && onClose()}>
      <section className="weekly-news-panel" role="dialog" aria-modal="true" aria-label="Weekly economic news calendar">
        <header className="weekly-news-head">
          <div>
            <span><CalendarClock size={14} /> Market Calendar</span>
            <strong>Weekly News</strong>
            <small>{asset} relevance / {weekRange} / device local time</small>
          </div>
          <nav>
            <button onClick={onRefresh} disabled={loading} title="Refresh calendar"><RefreshCw size={16} className={loading ? 'spin' : ''} /></button>
            <button onClick={onClose} title="Close calendar"><X size={17} /></button>
          </nav>
        </header>

        <div className="weekly-news-stats">
          <p><span>Events</span><strong>{stats.total ?? events.length}</strong></p>
          <p><span>{asset} Relevant</span><strong>{stats.relevant ?? 0}</strong></p>
          <p><span>High Impact</span><strong className="bad">{stats.high_impact ?? 0}</strong></p>
          <p><span>Released</span><strong>{stats.released ?? 0}</strong></p>
          <p><span>Actual Ready</span><strong className="good">{stats.actual_available ?? 0}</strong></p>
          <p><span>Feed</span><strong className={feed.status === 'LIVE' || feed.status === 'CACHED' ? 'good' : 'warn'}>{feed.status || '-'}</strong></p>
        </div>

        <div className="weekly-news-controls">
          <div className="weekly-news-primary-controls">
            <label className="weekly-news-search">
              <Search size={14} />
              <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search event or currency" aria-label="Search economic calendar" />
              {query && <button type="button" onClick={() => setQuery('')} title="Clear search"><X size={13} /></button>}
            </label>
            <div className="weekly-news-filters" aria-label="News filter">
              {NEWS_CALENDAR_FILTERS.map(([key, label]) => (
                <button key={key} className={filter === key ? 'active' : ''} onClick={() => setFilter(key)}>{label}</button>
              ))}
            </div>
          </div>
          <div className="weekly-news-days" aria-label="Calendar day">
            <button className={day === 'ALL' ? 'active' : ''} onClick={() => setDay('ALL')}>Week</button>
            {days.map(item => (
              <button key={item.key} className={day === item.key ? 'active' : ''} onClick={() => setDay(item.key)}>
                {newsDayLabel(item.timestamp, true)}
              </button>
            ))}
          </div>
        </div>

        <div className="weekly-news-list">
          {loading && !events.length && <div className="weekly-news-empty"><RefreshCw size={20} className="spin" /><strong>Loading weekly calendar</strong></div>}
          {error && !events.length && <div className="weekly-news-empty bad"><CalendarClock size={20} /><strong>Calendar unavailable</strong><span>{error}</span></div>}
          {!loading && !error && !visibleEvents.length && <div className="weekly-news-empty"><CalendarClock size={20} /><strong>No events match this filter</strong></div>}
          {groupedEvents.map(group => (
            <section className="weekly-news-day" key={group.key}>
              <header><strong>{newsDayLabel(group.timestamp)}</strong><span>{group.events.length} events</span></header>
              <div className="weekly-news-column-head"><span>Time</span><span>Currency</span><span>Event</span><span>Impact</span><span>Actual</span><span>Forecast</span><span>Previous</span></div>
              {group.events.map(event => {
                const impactBars = event.impact === 'HIGH' ? 3 : event.impact === 'MEDIUM' ? 2 : event.impact === 'LOW' ? 1 : 0
                return (
                  <article className={`weekly-news-event ${String(event.risk_window || '').toLowerCase()} ${String(event.release_status || 'UPCOMING').toLowerCase()} ${event.is_relevant ? 'relevant' : ''}`} key={event.id}>
                    <time dateTime={event.timestamp}>{newsClock(event.timestamp)}</time>
                    <CurrencyIdentity currency={event.currency} />
                    <div className="weekly-news-title">
                      <strong>{event.title}<b className={`news-release-badge ${String(event.release_status || 'UPCOMING').toLowerCase()}`}>{event.release_status === 'RELEASED' ? 'Released' : 'Upcoming'}</b></strong>
                      <small>{String(event.category || 'MACRO').replaceAll('_', ' ')} / {event.is_relevant ? `${event.relevance_score}% relevant` : 'context only'}</small>
                    </div>
                    <span className={`news-impact ${String(event.impact || 'LOW').toLowerCase()}`} title={`${event.impact || 'Low'} impact`}>
                      <i>{[1, 2, 3].map(level => <em className={level <= impactBars ? 'filled' : ''} key={level} />)}</i>
                      <b>{event.impact || '-'}</b>
                    </span>
                    <div className="weekly-news-values">
                      <p><span>Actual</span><strong className={event.actual ? 'actual' : event.release_status === 'RELEASED' ? 'updating' : ''}>{event.actual || (event.release_status === 'RELEASED' ? 'Updating' : 'Pending')}</strong></p>
                      <p><span>Forecast</span><strong>{event.forecast || '-'}</strong></p>
                      <p><span>Previous</span><strong>{event.previous || '-'}</strong></p>
                    </div>
                  </article>
                )
              })}
            </section>
          ))}
        </div>
        <footer>
          <span>{feed.source || 'Weekly economic calendar'} / refreshed {formatFreshness(feed.fetched_at)}</span>
          <strong>{visibleEvents.length} shown</strong>
        </footer>
      </section>
    </aside>
  )
}

function DiamondZonePanel({ keyZones, xauConfluence }) {
  const primary = safeObject(keyZones?.primary_zone)
  const precision = safeObject(xauConfluence)
  const precisionGate = safeObject(keyZones?.precision_gate)
  const smr = safeObject(keyZones?.smr_model)
  const smrSession = safeObject(smr.session)
  const smt = safeObject(keyZones?.smt_model)
  const dualCore = safeObject(keyZones?.diamond_timeframe_model)
  const primaryScore = Number(primary.diamond_score ?? keyZones?.diamond_score ?? 0)
  const visibleDiamondFloor = diamondVisibleFloor(keyZones, primary)
  if (
    keyZones?.status !== 'READY'
    || keyZones?.diamond_display_status === 'NO_QUALIFIED_DIAMOND'
    || primary.strategy_confirmed_origin !== true
    || primary.display_as_diamond === false
    || primaryScore < visibleDiamondFloor
    || !primary.line
  ) {
    return (
      <section className="diamond-zone-panel waiting">
        <header><Diamond size={16} /><span><small>SH Lead Diamond V7</small><strong>Scanning for a confirmed strategy setup</strong></span></header>
      </section>
    )
  }
  const direction = primary.direction === 'BULLISH' ? 'BULLISH' : 'BEARISH'
  const mtf = safeObject(keyZones?.mtf_confluence)
  const quality = keyZones?.quality_grade || primary.quality_grade || '-'
  const effectiveScore = primary.effective_score ?? primary.score ?? '-'
  const diamondScore = primary.diamond_score ?? keyZones?.diamond_score ?? primary.diamond_confidence_score ?? '-'
  const diamondGrade = primary.diamond_grade || keyZones?.diamond_grade || diamondGradeFromScore(diamondScore, false, visibleDiamondFloor)
  const strength = keyZones?.zone_strength_score ?? primary.zone_strength_score ?? '-'
  const executionQuality = keyZones?.execution_quality || primary.execution_quality || 'WAITING'
  const rejection = keyZones?.rejection_status || primary.rejection_status || 'WAITING'
  const rejectionScore = keyZones?.rejection_score ?? primary.rejection_score ?? 0
  const lifecycle = primary.lifecycle || '-'
  const latestEntry = safeObject(keyZones?.latest_entry_event)
  const entryPathway = String(latestEntry.entry_pathway || '').replaceAll('_', ' ')
  const entryPathwayLabel = entryPathway
    ? entryPathway
      .replace('SHALLOW PULLBACK CONTINUATION', 'Shallow Pullback')
      .replace('PULLBACK FOLLOW THROUGH', 'Deep Retest Follow-through')
      .replace('ORIGIN RECLAIM CLOSE', 'Origin Reclaim')
      .replace('RECLAIM CLOSE', 'Deep Reclaim')
    : 'Waiting Sequence'
  const entryStatus = String(keyZones?.entry_event_status || 'WAITING_CONFIRMATION').replaceAll('_', ' ')
  const entryCount = safeArray(keyZones?.entry_events).length
  const mtfState = mtf.state?.replaceAll('_', ' ') || 'WAITING'
  const requiredTimeframes = safeArray(mtf.required_timeframes)
  const mtfLabel = requiredTimeframes.length
    ? `MTF ${requiredTimeframes.join(' / ')}`
    : mtf.profile_label || keyZones?.profile_label || 'MTF Confirmation'
  const state = keyZones?.strategy_state?.replaceAll('_', ' ') || keyZones?.directional_bias?.replaceAll('_', ' ') || 'WAIT'
  const contextTone = primary.role === 'SUPPORT' ? 'buy' : primary.role === 'RESISTANCE' ? 'sell' : direction === 'BULLISH' ? 'buy' : 'sell'
  const displayRole = String(primary.display_role || (
    keyZones?.entry_event_status === 'CONFIRMED_ENTRY'
      ? 'CONFIRMED_ENTRY'
      : precisionGate.status === 'QUALIFIED' ? 'QUALIFIED_WATCH' : 'MARKET_CONTEXT'
  )).replaceAll('_', ' ')
  const entryStage = String(primary.entry_stage || keyZones?.entry_event_status || 'WAITING_RETEST').replaceAll('_', ' ')
  const entryBlocker = primary.entry_blocker_label || keyZones.next_trigger || 'Waiting for closed-candle sequence'
  const confidenceScore = diamondScore
  const confidenceTier = String(primary.diamond_confidence_tier || 'CONTEXT').replaceAll('_', ' ')
  const sideLabel = direction === 'BULLISH' ? 'BUY' : 'SELL'
  const reasonLabel = String(primary.origin_model || 'STRUCTURE REACTION').replaceAll('_', ' ')
  const statusLabel = primary.actionable_entry
    ? 'Confirmed'
    : primary.news_guard_suppressed
      ? 'News guard'
      : lifecycle === 'FLIPPED'
        ? 'Expired'
        : lifecycle === 'FRESH'
          ? 'Fresh'
          : lifecycle === 'TESTED'
            ? 'Tested'
            : 'Watching'
  const roleClass = primary.actionable_entry
    ? 'good'
    : ['INVALIDATED_CONTEXT', 'STALE_NO_RETEST'].includes(primary.display_role) || primary.entry_stage === 'INVALIDATED' ? 'bad' : 'warn'
  const smrState = String(smr.pattern_state || 'SCANNING').replaceAll('_', ' ')
  const smrTiming = `${smrState} / ${smrSession.name?.replaceAll('_', ' ') || 'WAITING'}`
  const smrTone = ['WAIT_SESSION', 'BLOCK_CONFLICT'].includes(String(smr.execution_gate || '').toUpperCase())
    ? 'bad'
    : smr.pattern_state === 'CONFIRMED' ? 'good' : 'warn'
  const smtState = String(smt.state || smt.status || 'WAITING').replaceAll('_', ' ')
  const smtTone = primary.smt_execution_gate === 'BLOCK_CONFLICT'
    ? 'bad'
    : primary.smt_execution_gate === 'CONFIRM' ? 'good' : 'warn'
  const dualCoreLabel = dualCore.status
    ? `${dualCore.focus_timeframe || 'Core'} ${dualCore.grade || '-'} ${dualCore.score ?? 0}`
    : 'Core waiting'
  return (
    <section className={`diamond-zone-panel ${contextTone} ${precision.status === 'READY' ? 'precision' : ''}`} aria-label="SH Diamond Zone strategy context">
      <header>
        <Diamond className="diamond-zone-icon" size={16} />
        <span><small>Diamond Detail</small><strong>{sideLabel} Key Zone</strong></span>
        <b title={`Grade ${diamondGrade || '-'} with ${diamondScore || 0}% confidence`}>Grade {diamondGrade || '-'} / {diamondScore || 0}%</b>
        <em>{statusLabel} / {keyZones.feed_matched ? 'Matched market data' : 'Data check required'}</em>
      </header>
      <div className="diamond-zone-metrics">
        <p><span>Side</span><strong className={contextTone === 'buy' ? 'good' : 'warn'}>{sideLabel}</strong></p>
        <p><span>Zone Price</span><strong>{asPrice(primary.line)}</strong></p>
        <p title={`Diamond confidence ${diamondScore || 0}%. ${dualCore.next_trigger || 'Dual-Core is warming up.'}`}><span>Quality / Core</span><strong>{diamondGrade || '-'} {diamondScore || 0} / {dualCoreLabel}</strong></p>
        <p title={reasonLabel}><span>Reason</span><strong>{reasonLabel}</strong></p>
        <p title={`${smr.next_trigger || smrTiming} SMT: ${smt.reason || smtState}`}><span>SMR / SMT</span><strong className={primary.smt_execution_gate ? smtTone : smrTone}>{smrState} / {smtState}</strong></p>
        <p title={entryBlocker}><span>Status</span><strong className={roleClass}>{statusLabel}</strong></p>
      </div>
    </section>
  )
}

function IntelligenceDock({ activeTab, onTab, collapsed, onToggle, analysis, tracker, snapshot, diamondHistory, diamondValidation, strategyGovernance, marketAlerts, validationLoading, onRunValidation, onAcknowledgeAlert, onReplayDiamond, replayKey, sessionFramework, keyZones, newsIntelligence }) {
  const trackerStats = safeObject(tracker?.stats)
  const historyStats = safeObject(diamondHistory?.stats)
  const tabs = [
    { id: 'setup', label: 'Trade Plan', icon: ListChecks, value: trackerStats.active ?? 0, signed: false },
    { id: 'market', label: 'Key Zones', icon: Layers3, value: snapshot?.confluence_score ?? 0, signed: true },
    { id: 'journal', label: 'Proof', icon: Activity, value: historyStats.total ?? 0, signed: false },
  ]
  return (
    <section className={`intelligence-dock ${collapsed ? 'collapsed' : 'expanded'}`}>
      <header className="intelligence-dock-head">
        <div>
          <span>Action Dock</span>
          <strong>{tabs.find(tab => tab.id === activeTab)?.label || 'Trade Plan'}</strong>
        </div>
        <nav aria-label="Intelligence panels">
          {tabs.map(tab => {
            const Icon = tab.icon
            return (
              <button
                className={activeTab === tab.id ? 'active' : ''}
                key={tab.id}
                onClick={() => onTab(tab.id)}
                aria-pressed={activeTab === tab.id}
              >
                <Icon size={14} />
                <span>{tab.label}</span>
                <b>{tab.signed && Number(tab.value) > 0 ? '+' : ''}{tab.value}</b>
              </button>
            )
          })}
        </nav>
        <button className="dock-collapse" onClick={onToggle} title={collapsed ? 'Expand action dock' : 'Collapse action dock'} aria-label={collapsed ? 'Expand action dock' : 'Collapse action dock'} aria-expanded={!collapsed}>
          <ChevronDown className={collapsed ? 'collapsed' : ''} size={16} />
        </button>
      </header>
      <div className="intelligence-dock-reveal" aria-hidden={collapsed}>
        <div className="intelligence-dock-content">
          {activeTab === 'setup' && (
            <div className="setup-dock-stack">
              <ExecutionGateStrip analysis={analysis} />
              <SetupTrackerPanel tracker={tracker} />
            </div>
          )}
          {activeTab === 'market' && (
            <div className="session-market-stack">
              <NewsRiskPanel news={newsIntelligence} />
              <DiamondZonePanel keyZones={keyZones} xauConfluence={analysis?.xau_confluence} />
              <SessionFrameworkPanel framework={sessionFramework} />
              <MtfMarketMap snapshot={snapshot} />
            </div>
          )}
          {activeTab === 'journal' && (
            <div className="proof-dock-stack">
              <DiamondValidationPanel validation={diamondValidation} onRun={onRunValidation} loading={validationLoading} />
              <SimpleDiamondHistory history={diamondHistory} onReplay={onReplayDiamond} replayKey={replayKey} />
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function DiamondStatusBar({ signal, decision, nextGate, adaptiveProfile, confidenceLabel, publicLifecycle, detailsOpen, onDetails, onHistory }) {
  const score = signal ? signalScore(signal) : 0
  const grade = signal ? signal.diamond_grade || diamondGradeFromScore(score, false, diamondVisibleFloor(signal)) : ''
  const rawSide = String(signal?.entry_side || signal?.direction || '').toUpperCase()
  const side = rawSide === 'BULLISH' ? 'BUY' : rawSide === 'BEARISH' ? 'SELL' : rawSide || 'WAIT'
  const zonePrice = signal?.line ?? signal?.marker_price
  const origin = String(signal?.origin_model || 'Scanning').replaceAll('_', ' ')
  const lifecycle = String(publicLifecycle || signal?.lifecycle || 'Watching').replaceAll('_', ' ')
  const regime = String(adaptiveProfile?.regime || 'WAITING').replaceAll('_', ' ')
  const simpleLabel = confidenceLabel || (side === 'WAIT' ? 'Wait for Rejection' : 'Trend Check')
  return (
    <section className={`diamond-status-bar ${side.toLowerCase()}`} aria-label="Diamond Zone status">
      <div className="diamond-status-decision">
        <span><Diamond size={13} /> Diamond Zone</span>
        <strong>{decision}</strong>
        <small className="diamond-status-next">{simpleLabel} / {lifecycle}</small>
      </div>
      <div className="diamond-status-signal">
        <span className={side.toLowerCase()}>{side}</span>
        <strong>{grade ? `Grade ${grade}` : 'Scanning'}</strong>
        <b>{score || 0}%</b>
      </div>
      <div className="diamond-status-context">
        <p><span>Lifecycle</span><strong>{lifecycle}</strong></p>
        <p title={`${origin} / Diamond ${asPrice(zonePrice)}`}><span>Market</span><strong>{regime}</strong></p>
        <p title={`${origin} / ${lifecycle} / ${regime} / Diamond ${asPrice(zonePrice)}`}><span>Next</span><strong>{nextGate || 'Watching closed candles'}</strong></p>
      </div>
      <div className="diamond-status-actions">
        <button onClick={onHistory} title="Open preserved Diamond proof"><ChartSpline size={14} /><span>Proof</span></button>
        <button className={detailsOpen ? 'active' : ''} onClick={onDetails} title={detailsOpen ? 'Close panels' : 'Open panels'}><Layers3 size={14} /><span>Panels</span></button>
      </div>
    </section>
  )
}

function SignalChartView({ asset, timeframe, timeframeTransition, chartData, overlays, panels, analysis, providerAlignment, liveSync, mtfSnapshot, diamondHistory, diamondValidation, strategyGovernance, marketAlerts, validationLoading, setupTracker, sessionFramework, keyZones, newsIntelligence, focusRequest, onRunValidation, onAcknowledgeAlert, onTimeframe, onTradingView, onNews }) {
  const sectionRef = useRef(null)
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const candleSeriesRef = useRef(null)
  const flowSeriesRef = useRef(null)
  const pressureSeriesRef = useRef(null)
  const priceLinesRef = useRef([])
  const levelsRef = useRef([])
  const diamondContextZonesRef = useRef([])
  const diamondPrimitiveRef = useRef(null)
  const replayAppliedRef = useRef('')
  const candleDatasetRef = useRef('')
  const [chartEngine, setChartEngine] = useState(null)
  const [chartReady, setChartReady] = useState(false)
  const [chartLoadError, setChartLoadError] = useState('')
  const [levelPositions, setLevelPositions] = useState([])
  const [diamondVisuals, setDiamondVisuals] = useState({ bands: [] })
  const [dockTab, setDockTab] = useState('setup')
  const [dockCollapsed, setDockCollapsed] = useState(true)
  const [replayEntry, setReplayEntry] = useState(null)
  const feedTrusted = providerAlignment?.matched !== false
  const candles = useMemo(
    () => feedTrusted ? signalViewCandles(chartData, asset) : [],
    [chartData, asset, feedTrusted],
  )
  const levels = useMemo(
    () => feedTrusted ? deriveSignalViewLevels(candles, overlays, analysis, sessionFramework, keyZones) : [],
    [candles, overlays, analysis, sessionFramework, keyZones, feedTrusted],
  )
  const diamondContextZones = useMemo(() => {
    if (!feedTrusted) return []
    const primary = safeObject(keyZones?.primary_zone)
    const visibleDiamondFloor = diamondVisibleFloor(keyZones, primary)
    const sourceZones = Array.isArray(keyZones?.live_zones)
      ? keyZones.live_zones
      : Array.isArray(keyZones?.visible_zones) ? keyZones.visible_zones : safeArray(keyZones?.zones)
    const visible = sourceZones.filter(zone => (
      zone?.id
      && zone.strategy_confirmed_origin === true
      && zone.display_as_diamond !== false
      && Number(zone.diamond_score ?? zone.diamond_confidence_score ?? 0) >= visibleDiamondFloor
      && !['INVALIDATED_CONTEXT', 'INTERNAL_REJECTED'].includes(String(zone.display_role || '').toUpperCase())
    ))
    const visiblePrimary = visible.find(zone => zone.id === primary.id)
    const remaining = visible.filter(zone => zone.id !== visiblePrimary?.id)
    const zones = visiblePrimary ? [visiblePrimary, ...remaining] : visible
    return zones.slice(0, 1).map(zone => ({ ...zone, isPrimary: zone.id === primary.id }))
  }, [keyZones, feedTrusted])
  const diamondEntryEvents = useMemo(
    () => feedTrusted ? safeArray(keyZones?.entry_events)
      .filter(event => (
        event?.id
        && Number(event.diamond_score ?? event.quality_score ?? 0) >= 60
        && Number.isFinite(Number(event.time))
        && Number.isFinite(Number(event.marker_price ?? event.line))
      ))
      .slice(-4) : [],
    [keyZones, feedTrusted],
  )
  const persistedDiamondMarkers = useMemo(
    () => derivePersistedDiamondMarkers(candles, diamondHistory, timeframe),
    [candles, diamondHistory, timeframe],
  )
  const validationReplayMarkers = useMemo(
    () => deriveValidationReplayMarkers(candles, diamondValidation, timeframe),
    [candles, diamondValidation, timeframe],
  )
  const currentDiamondMarkers = useMemo(
    () => deriveCurrentDiamondMarkers(candles, diamondContextZones),
    [candles, diamondContextZones],
  )
  const crystalMarkers = useMemo(() => mergeCrystalMarkers([
    ...diamondEntryEvents.map(event => ({
      ...event,
      marker_kind: 'entry',
      marker_label: event.marker_label || diamondGradeLabel(
        event.diamond_grade || event.quality_grade || event.precision_grade,
        event.diamond_score ?? event.quality_score,
      ),
      marker_title: event.marker_title || `Confirmed ${event.entry_side || event.direction || ''} entry / ${diamondGradeLabel(
        event.diamond_grade || event.quality_grade || event.precision_grade,
        event.diamond_score ?? event.quality_score,
      )}`.trim(),
    })),
    ...currentDiamondMarkers,
    ...persistedDiamondMarkers,
    ...validationReplayMarkers,
  ], timeframe), [diamondEntryEvents, currentDiamondMarkers, persistedDiamondMarkers, validationReplayMarkers, timeframe])
  const savedDiamondHistoryCount = useMemo(
    () => safeArray(diamondHistory?.entries).filter(
      entry => String(entry?.timeframe || '').toUpperCase() === String(timeframe || '').toUpperCase(),
    ).length,
    [diamondHistory, timeframe],
  )
  const crystalSummary = useMemo(() => ({
    total: crystalMarkers.length,
    saved: savedDiamondHistoryCount,
    replayed: validationReplayMarkers.length,
  }), [crystalMarkers, savedDiamondHistoryCount, validationReplayMarkers])
  const primarySignal = keyZones?.entry_event_status === 'CONFIRMED_ENTRY' && diamondEntryEvents.length
    ? diamondEntryEvents[diamondEntryEvents.length - 1]
    : diamondContextZones[0] || null
  const latestCandlePrice = Number(candles[candles.length - 1]?.close)
  const diamondRiskGuide = useMemo(
    () => deriveDiamondRiskGuide(primarySignal, keyZones, sessionFramework, latestCandlePrice),
    [primarySignal, keyZones, sessionFramework, latestCandlePrice],
  )
  levelsRef.current = levels
  diamondContextZonesRef.current = diamondContextZones
  const panelData = feedTrusted ? safeObject(panels?.indicator_panels) : {}
  const indicatorSnapshot = deriveIndicatorSnapshot(panelData)
  const macdSnapshot = safeObject(indicatorSnapshot.macd)
  const rsiSnapshot = safeObject(indicatorSnapshot.rsi)
  const macdTone = String(macdSnapshot.bias || 'neutral').toLowerCase()
  const rsiTone = String(rsiSnapshot.zone || 'neutral').toLowerCase()
  const macdDetail = macdSnapshot.divergence && macdSnapshot.divergence !== 'NONE'
    ? `${macdSnapshot.divergence} divergence`
    : macdSnapshot.cross || macdSnapshot.phase || macdSnapshot.momentum
  const rsiDetail = rsiSnapshot.divergence && rsiSnapshot.divergence !== 'NONE'
    ? `${rsiSnapshot.divergence} divergence`
    : rsiSnapshot.momentum
  const candleAudit = safeObject(liveSync?.history_provenance?.audit)
  const decisionQuality = safeObject(analysis?.decision_quality)
  const newsEvent = safeObject(newsIntelligence?.primary_event)

  useEffect(() => {
    if (!focusRequest?.id) return
    if (focusRequest.target === 'history') {
      setDockTab('journal')
      setDockCollapsed(false)
    } else if (focusRequest.target === 'chart') {
      setDockCollapsed(true)
    }
    const frame = requestAnimationFrame(() => {
      const target = focusRequest.target === 'history'
        ? sectionRef.current?.querySelector('.intelligence-dock')
        : sectionRef.current
      target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
    return () => cancelAnimationFrame(frame)
  }, [focusRequest])
  const decision = !feedTrusted
    ? 'Waiting for Matched Data'
    : newsIntelligence?.execution_gate === 'BLOCK_NEW_ENTRIES'
    ? `News Lock - ${newsEvent.title || 'High Impact Event'}`
    : decisionQualityLabel(decisionQuality.status) || analysis?.final_decision || 'Waiting for Analysis'
  const readiness = safeObject(decisionQuality.execution_readiness)
  const primaryBlocker = safeObject(decisionQuality.primary_blocker || readiness.current_gate)
  const locationGuard = safeObject(decisionQuality.location_guard || analysis?.market_regime?.location_guard)
  const nextGate = !feedTrusted ? 'Data Trust' : readiness.next_gate_label || primaryBlocker.label || 'Engine Diagnostics'
  const timeframeSwitching = Boolean(timeframeTransition?.active && timeframeTransition?.target === timeframe)
  const timeframeTransitionLabel = timeframeTransition?.phase === 'analysis'
    ? `Updating ${timeframeLabel(timeframe)} setup`
    : `Loading ${timeframeLabel(timeframe)} candles`

  const focusReplayEntry = entry => {
    const chart = chartRef.current
    const series = candleSeriesRef.current
    if (!chart || !series || !entry) return false
    const replayTime = diamondReplayTimestamp(entry)
    const candleIndex = candles.findIndex(candle => Number(candle.time) === replayTime)
    if (candleIndex < 0) return false
    chart.timeScale().setVisibleLogicalRange({
      from: Math.max(0, candleIndex - 32),
      to: Math.min(candles.length + 4, candleIndex + 32),
    })
    const replayPrice = Number(entry.entry_price ?? entry.line)
    if (Number.isFinite(replayPrice)) chart.setCrosshairPosition(replayPrice, replayTime, series)
    replayAppliedRef.current = `${entry.zone_key}:${timeframe}:${candles[0]?.time || 0}`
    return true
  }

  const handleReplayDiamond = entry => {
    if (!entry) return
    replayAppliedRef.current = ''
    setReplayEntry(entry)
    setDockCollapsed(true)
    const replayTimeframe = String(entry.timeframe || timeframe).toUpperCase()
    if (replayTimeframe !== timeframe) {
      onTimeframe(replayTimeframe)
      return
    }
    requestAnimationFrame(() => focusReplayEntry(entry))
  }

  const clearReplay = () => {
    setReplayEntry(null)
    replayAppliedRef.current = ''
    chartRef.current?.clearCrosshairPosition()
    if (candles.length) chartRef.current?.timeScale().setVisibleLogicalRange({ from: Math.max(0, candles.length - 78), to: candles.length + 5 })
  }

  const updateLevelPositions = () => {
    const series = candleSeriesRef.current
    const chart = chartRef.current
    if (!series || !chart) return
    const paneHeight = chart.paneSize(0)?.height || containerRef.current?.clientHeight || 0
    const positioned = levelsRef.current
      .map(level => ({ ...level, top: series.priceToCoordinate(level.price) }))
      .filter(level => Number.isFinite(level.top) && level.top >= 0 && level.top <= paneHeight)
      .sort((a, b) => a.top - b.top)
    let previousTop = -30
    const adjusted = positioned.map(level => {
      const top = Math.min(Math.max(level.top, previousTop + 23), Math.max(0, paneHeight - 24))
      previousTop = top
      return { ...level, top }
    })
    setLevelPositions(adjusted)
    const bands = diamondContextZonesRef.current.slice(0, 3).map(zone => {
      const high = series.priceToCoordinate(Number(zone.high))
      const low = series.priceToCoordinate(Number(zone.low))
      if (!Number.isFinite(high) || !Number.isFinite(low)) return null
      const rawTop = Math.min(high, low)
      const rawBottom = Math.max(high, low)
      if (rawBottom < 0 || rawTop > paneHeight) return null
      const top = Math.max(0, rawTop)
      const bottom = Math.min(paneHeight, rawBottom)
      return { ...zone, top, height: Math.max(6, bottom - top), primary: zone.isPrimary }
    }).filter(Boolean)
    setDiamondVisuals({ bands })
  }

  useEffect(() => {
    let active = true
    loadChartEngine()
      .then(engine => {
        if (active) setChartEngine(engine)
      })
      .catch(err => {
        if (active) setChartLoadError(err?.message || 'Chart engine could not be loaded.')
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!chartEngine || !containerRef.current || chartRef.current) return undefined
    const { CandlestickSeries, createChart, HistogramSeries } = chartEngine
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: { background: { color: '#061321' }, textColor: '#d4dde8', fontFamily: 'Inter, ui-sans-serif, system-ui' },
      grid: {
        vertLines: { color: 'rgba(97, 130, 162, .17)' },
        horzLines: { color: 'rgba(97, 130, 162, .17)' },
      },
      rightPriceScale: { borderColor: '#3d5268', scaleMargins: { top: .08, bottom: .08 } },
      timeScale: { borderColor: '#3d5268', timeVisible: true, secondsVisible: false, rightOffset: 7, barSpacing: 9, minBarSpacing: 4 },
      crosshair: {
        mode: 0,
        vertLine: { color: 'rgba(113, 222, 248, .55)', style: LINE_STYLE.dashed, labelBackgroundColor: '#163447' },
        horzLine: { color: 'rgba(113, 222, 248, .55)', style: LINE_STYLE.dashed, labelBackgroundColor: '#163447' },
      },
    })
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#fff21f',
      downColor: '#ff4738',
      borderUpColor: '#fff21f',
      borderDownColor: '#ff4738',
      wickUpColor: '#fff77a',
      wickDownColor: '#ff7468',
      priceFormat: { type: 'price', precision: asset === 'BTCUSD' ? 2 : 2, minMove: .01 },
    }, 0)
    const flowSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceLineVisible: false,
      lastValueVisible: false,
      base: 0,
    }, 1)
    const pressureSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'custom', minMove: .1, formatter: value => Math.round(value).toString() },
      priceLineVisible: false,
      lastValueVisible: false,
      base: 50,
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
    }, 2)
    flowSeries.createPriceLine({
      price: 0,
      color: 'rgba(203, 213, 225, .28)',
      lineWidth: 1,
      lineStyle: LINE_STYLE.dotted,
      axisLabelVisible: false,
      title: '',
    })
    ;[70, 50, 30].forEach(value => pressureSeries.createPriceLine({
      price: value,
      color: value === 50 ? 'rgba(203, 213, 225, .28)' : 'rgba(226, 196, 95, .22)',
      lineWidth: 1,
      lineStyle: value === 50 ? LINE_STYLE.dotted : LINE_STYLE.dashed,
      axisLabelVisible: false,
      title: '',
    }))
    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    flowSeriesRef.current = flowSeries
    pressureSeriesRef.current = pressureSeries
    setChartReady(true)
    setChartLoadError('')
    const diamondPrimitive = new DiamondMarkersPrimitive()
    candleSeries.attachPrimitive(diamondPrimitive)
    diamondPrimitiveRef.current = diamondPrimitive
    const panes = chart.panes()
    panes[0]?.setStretchFactor(.84)
    panes[1]?.setStretchFactor(.08)
    panes[2]?.setStretchFactor(.08)
    const sizeIndicatorPanes = () => {
      const compact = (containerRef.current?.clientWidth || window.innerWidth) <= 720
      const currentPanes = chart.panes()
      currentPanes[1]?.setHeight(compact ? 46 : 56)
      currentPanes[2]?.setHeight(compact ? 44 : 52)
    }
    sizeIndicatorPanes()
    chart.timeScale().subscribeVisibleLogicalRangeChange(updateLevelPositions)
    const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
      requestAnimationFrame(() => {
        sizeIndicatorPanes()
        updateLevelPositions()
      })
    })
    resizeObserver?.observe(containerRef.current)
    return () => {
      resizeObserver?.disconnect()
      try { candleSeries.detachPrimitive(diamondPrimitive) } catch (_) { /* Chart cleanup is best-effort. */ }
      try { chart.remove() } catch (_) { /* Chart cleanup is best-effort. */ }
      chartRef.current = null
      candleSeriesRef.current = null
      flowSeriesRef.current = null
      pressureSeriesRef.current = null
      diamondPrimitiveRef.current = null
    }
  }, [chartEngine])

  useEffect(() => {
    const chart = chartRef.current
    const candleSeries = candleSeriesRef.current
    if (!chart || !candleSeries) return
    const datasetIdentity = `${asset}:${chartData?.symbol || 'unknown'}:${timeframe}:${candles.length}:${candles[0]?.time || 0}:${candles[0]?.close || 0}:${candles.at(-1)?.time || 0}`
    const sameDataset = candleDatasetRef.current === datasetIdentity
    if (sameDataset && candles.length) {
      candleSeries.update(candles[candles.length - 1])
    } else {
      candleSeries.setData(candles)
      candleDatasetRef.current = datasetIdentity
    }
    flowSeriesRef.current?.setData(normalizeChartSeries(panelData.market_pressure, item => ({
      time: item.time,
      value: Number(item.value) || 0,
      color: macdBarColor(item),
    })))
    pressureSeriesRef.current?.setData(normalizeChartSeries(panelData.liquidity_pressure, item => {
      const rawValue = Number(item.raw_value ?? (Number(item.value) + 50))
      const value = Number.isFinite(rawValue) ? rawValue : 50
      return {
        time: item.time,
        value,
        color: rsiBarColor(item),
      }
    }))
    if (candles.length && !sameDataset) {
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, candles.length - 78), to: candles.length + 5 })
    }
    let secondFrame = null
    const firstFrame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(updateLevelPositions)
    })
    const settleTimer = setTimeout(updateLevelPositions, 180)
    const finalTimer = setTimeout(updateLevelPositions, 700)
    return () => {
      cancelAnimationFrame(firstFrame)
      if (secondFrame !== null) cancelAnimationFrame(secondFrame)
      clearTimeout(settleTimer)
      clearTimeout(finalTimer)
    }
  }, [asset, timeframe, candles, panelData, analysis, diamondEntryEvents, chartReady])

  useEffect(() => {
    const series = candleSeriesRef.current
    if (!series) return
    priceLinesRef.current.forEach(line => {
      try { series.removePriceLine(line) } catch (_) { /* Ignore stale lines. */ }
    })
    priceLinesRef.current = levels.map(level => series.createPriceLine({
      price: level.price,
      color: level.color,
      lineWidth: level.key === 'price' ? 2 : 1,
      lineStyle: LINE_STYLE[level.style] ?? LINE_STYLE.solid,
      axisLabelVisible: true,
      title: level.label,
    }))
    requestAnimationFrame(updateLevelPositions)
  }, [levels, chartReady])

  useEffect(() => {
    diamondPrimitiveRef.current?.setMarkers(crystalMarkers)
    const frame = requestAnimationFrame(updateLevelPositions)
    return () => cancelAnimationFrame(frame)
  }, [crystalMarkers, chartReady])

  useEffect(() => {
    if (!replayEntry || String(replayEntry.timeframe || '').toUpperCase() !== timeframe || !candles.length) return
    const replayKey = `${replayEntry.zone_key}:${timeframe}:${candles[0]?.time || 0}`
    if (replayAppliedRef.current === replayKey) return
    const frame = requestAnimationFrame(() => focusReplayEntry(replayEntry))
    return () => cancelAnimationFrame(frame)
  }, [candles, replayEntry, timeframe, chartReady])

  return (
    <section className="signal-view" ref={sectionRef}>
      <header className="signal-view-toolbar">
        <div className="signal-view-symbol">
          <strong>{asset}</strong>
          <span>{liveSync?.source || MARKET_ASSETS[asset]?.label} / {providerAlignment?.matched ? 'matched feed' : 'unmatched fallback'}</span>
        </div>
        <div className={`signal-live-state ${liveSync?.forming_candle ? 'forming' : ''}`}>
          <i />
          <span>{liveSync?.forming_candle ? 'LIVE CANDLE' : liveSync?.ok ? 'FEED LIVE' : liveSync?.status === 'SYNC_PAUSED' ? 'SYNC PAUSED' : 'SYNCING'}</span>
          {liveSync?.synced_at && <time>{new Date(liveSync.synced_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time>}
          {Number.isFinite(Number(liveSync?.provider_latency_ms)) && <em title="Market feed response time">{Math.round(Number(liveSync.provider_latency_ms))}ms</em>}
          {candleAudit.status && <b className={candleAudit.status === 'OHLC_CLEAN' ? 'verified' : 'review'}>{candleAudit.status.replace('_', ' ')}</b>}
        </div>
        <div
          className="signal-crystal-guide"
          title="Saved Diamond history remains visible while new setup-confirmed zones are added automatically."
          aria-label={`${crystalSummary.total} Diamond key zones on chart, ${crystalSummary.saved} saved history records`}
        >
          <span className="buy"><Diamond size={11} />Buy Zone</span>
          <span className="sell"><Diamond size={11} />Sell Zone</span>
          <b>{crystalSummary.total} on chart</b>
          <em>{crystalSummary.replayed ? `${crystalSummary.replayed} replayed` : `${crystalSummary.saved} saved history`}</em>
        </div>
        <div className="signal-view-timeframes">
          {['5M', '15M', '1H', '4H', '1D'].map(item => (
            <button
              className={`${timeframe === item ? 'active' : ''} ${timeframeSwitching && timeframe === item ? 'pending' : ''}`}
              key={item}
              onClick={() => {
                clearReplay()
                onTimeframe(item)
              }}
              aria-pressed={timeframe === item}
              aria-busy={timeframeSwitching && timeframe === item}
            >
              <span>{timeframeLabel(item)}</span>
              {timeframeSwitching && timeframe === item && <RefreshCw size={11} />}
            </button>
          ))}
        </div>
        <button className="signal-view-tv" onClick={onTradingView} title="Open TradingView Live">
          <BarChart3 size={16} />
          <span>TradingView</span>
        </button>
      </header>
      {!providerAlignment?.matched && (
        <div className="signal-feed-warning">
          <strong>UNMATCHED FEED</strong>
          <span>{liveSync?.source || 'Fallback history'} differs from {providerAlignment?.visual_symbol || MARKET_ASSETS[asset]?.tradingViewSymbol}. The chart and analysis remain locked.</span>
        </div>
      )}
      <DiamondStatusBar
        signal={primarySignal}
        decision={decision}
        nextGate={nextGate}
        riskGuide={diamondRiskGuide}
        adaptiveProfile={keyZones?.adaptive_profile}
        confidenceLabel={keyZones?.confidence_label}
        publicLifecycle={keyZones?.public_lifecycle}
        detailsOpen={!dockCollapsed}
        onDetails={() => setDockCollapsed(value => !value)}
        onHistory={() => {
          setDockTab('journal')
          setDockCollapsed(false)
        }}
      />
      <div className={`signal-chart-shell ${candles.length ? 'has-data' : 'empty'} ${timeframeSwitching ? `switching ${timeframeTransition?.phase || 'snapshot'}` : ''}`}>
        <div ref={containerRef} className="signal-chart-canvas" />
        {chartLoadError && (
          <div className="signal-timeframe-transition chart-load-error" role="alert">
            <X size={12} />
            <span>{chartLoadError}</span>
          </div>
        )}
        <div className="signal-chart-brand" aria-hidden="true">
          <span className="signal-chart-brand-mark">
            <Diamond className="buy-crystal" size={22} />
            <Diamond className="sell-crystal" size={18} />
          </span>
          <span className="signal-chart-brand-copy">
            <strong><b>SH</b><em>SIGNAL</em></strong>
            <small>{asset} / {timeframeLabel(timeframe)}</small>
          </span>
          <i />
        </div>
        {['HIGH', 'ELEVATED'].includes(String(newsIntelligence?.risk_level || '').toUpperCase()) && (
          <button className={`signal-news-chip ${String(newsIntelligence?.risk_level).toLowerCase()}`} onClick={onNews} title={newsEvent.title || 'Open market calendar'}>
            <CalendarClock size={12} />
            <span>{newsIntelligence.risk_level}</span>
            <strong>{newsEvent.countdown || formatNewsTime(newsEvent.timestamp)}</strong>
          </button>
        )}
        {replayEntry && (
          <div className="signal-replay-state" role="status">
            <ChartSpline size={13} />
            <span>Replay</span>
            <strong>{timeframeLabel(replayEntry.timeframe)} / {replayEntry.entry_side} / {asPrice(replayEntry.line)}</strong>
            <button onClick={clearReplay} title="Return to live candles" aria-label="Return to live candles"><X size={13} /></button>
          </div>
        )}
        {timeframeSwitching && (
          <div className="signal-timeframe-transition" role="status" aria-live="polite">
            <RefreshCw size={12} />
            <span>{timeframeTransitionLabel}</span>
          </div>
        )}
        <div className="signal-diamond-bands">
          {diamondVisuals.bands.map(zone => (
            <div
              className={`signal-diamond-band ${String(zone.direction).toLowerCase()} ${String(zone.role || '').toLowerCase()} ${String(zone.lifecycle || '').toLowerCase()} ${zone.primary ? 'primary' : ''}`}
              key={zone.id}
              style={{ top: zone.top, height: zone.height }}
              title={`${zone.role || zone.direction} Diamond Zone ${asPrice(zone.low)} - ${asPrice(zone.high)} / ${zone.lifecycle || '-'} / Grade ${zone.diamond_grade || zone.quality_grade || '-'} / Score ${zone.diamond_score ?? zone.diamond_confidence_score ?? zone.effective_score ?? '-'}`}
            >
              {zone.primary && <span><Diamond size={8} /><b>{zone.role === 'SUPPORT' ? 'SUP' : zone.role === 'RESISTANCE' ? 'RES' : 'TEST'}</b> {zone.diamond_grade || zone.quality_grade || '-'} {zone.diamond_score ?? zone.diamond_confidence_score ?? zone.effective_score ?? zone.score}</span>}
            </div>
          ))}
        </div>
        <div
          className={`signal-pane-label flow ${macdTone}`}
          title={`MACD 12/26/9 / ${indicatorStateLabel(macdSnapshot.phase)} / ${indicatorStateLabel(macdDetail)} / Strength ${macdSnapshot.strength ?? 0}%`}
        >
          <span><strong>MACD</strong><b>{asIndicatorValue(macdSnapshot.histogram)}</b><small>{indicatorStateLabel(macdSnapshot.phase)}</small></span>
          <em>{indicatorStateLabel(macdDetail)}</em>
        </div>
        <div
          className={`signal-pane-label pressure ${rsiTone}`}
          title={`RSI 14 / ${indicatorStateLabel(rsiSnapshot.zone)} / ${indicatorStateLabel(rsiDetail)} / Average ${asIndicatorValue(rsiSnapshot.average)}`}
        >
          <span><strong>RSI 14</strong><b>{asIndicatorValue(rsiSnapshot.value)}</b><small>{indicatorStateLabel(rsiSnapshot.zone)}</small></span>
          <em>{indicatorStateLabel(rsiDetail)}</em>
        </div>
        <div className="signal-level-labels">
          {levelPositions.filter(level => !level.hideLeftLabel).map(level => (
            <span key={level.key} style={{ top: level.top, '--level-color': level.color }}>{level.label}</span>
          ))}
        </div>
        {!candles.length && (
          <div className="signal-chart-empty">
            <div>
              <Activity size={18} />
              <strong>Waiting for matched candles</strong>
              <span>Auto Engine has paused the chart until trusted market data is ready.</span>
              <button type="button" onClick={() => onTimeframe(timeframe)} title="Retry candle synchronization">
                <RefreshCw size={14} />
                <span>Retry sync</span>
              </button>
            </div>
          </div>
        )}
      </div>
      <IntelligenceDock
        activeTab={dockTab}
        onTab={tab => {
          setDockTab(tab)
          setDockCollapsed(false)
        }}
        collapsed={dockCollapsed}
        onToggle={() => setDockCollapsed(value => !value)}
        analysis={analysis}
        keyZones={keyZones}
        tracker={setupTracker}
        snapshot={mtfSnapshot}
        diamondHistory={diamondHistory}
        diamondValidation={diamondValidation}
        strategyGovernance={strategyGovernance}
        marketAlerts={marketAlerts}
        validationLoading={validationLoading}
        onRunValidation={onRunValidation}
        onAcknowledgeAlert={onAcknowledgeAlert}
        onReplayDiamond={handleReplayDiamond}
        replayKey={replayEntry?.zone_key}
        sessionFramework={sessionFramework}
        newsIntelligence={newsIntelligence}
      />
    </section>
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
        <span>Market Service</span>
        <strong className={tone(backendOffline ? 'BACKEND_OFFLINE' : lockedMode?.backend_status)}>{backendOffline ? 'UNAVAILABLE' : lockedMode?.backend_status === 'ONLINE' ? 'ONLINE' : 'CONNECTING'}</strong>
      </div>
      <div>
        <span>Analysis</span>
        <strong className={tone(analysisState)}>{analysisState}</strong>
      </div>
    </section>
  )
}

function tradingViewEmbedUrl(symbol, interval) {
  const params = new URLSearchParams({
    symbol,
    interval,
    theme: 'dark',
    style: '1',
    timezone: 'Etc/UTC',
    withdateranges: '1',
    hide_side_toolbar: '0',
    allow_symbol_change: '1',
    saveimage: '1',
    locale: 'en',
    studies: '[]',
  })
  return `https://s.tradingview.com/widgetembed/?${params.toString()}`
}

function TradingViewLiveChart({ symbol = 'OANDA:XAUUSD', timeframe = '5M', internalReady = false, compact = false, showHeader = false }) {
  const [widgetError, setWidgetError] = useState('')
  const interval = TRADINGVIEW_INTERVALS[timeframe] || '5'
  const src = tradingViewEmbedUrl(symbol, interval)

  return (
    <section className={`tradingview-live-card ${compact ? 'compact' : ''}`}>
      {showHeader && (
        <>
          <div className="tradingview-live-head">
            <div>
              <strong>TradingView Live Chart</strong>
              <span>{symbol} / {timeframeLabel(timeframe)} / visual reference only</span>
            </div>
            <b>{internalReady ? 'SH Engine Data Ready' : 'SH Internal Data Waiting'}</b>
          </div>
          <VisualReferenceNotice chartMode="tradingview" internalReady={internalReady} />
        </>
      )}
      {widgetError && <div className="terminal-alert bad">{widgetError}</div>}
      <div className="tradingview-widget-frame">
        <iframe
          key={`${symbol}-${interval}`}
          title={`TradingView ${symbol}`}
          src={src}
          onLoad={() => setWidgetError('')}
          onError={() => setWidgetError('TradingView Live Chart failed to load. Check internet connection.')}
          allowFullScreen
        />
      </div>
    </section>
  )
}

function AnalysisResultDrawer({ open, onClose, onExport, analysis, lockedMode, dataIntegrity, explanation }) {
  const [resultTab, setResultTab] = useState('overview')
  const mode = analysis?.data_mode || lockedMode?.locked_mode || lockedMode?.data_mode
  const signal = safeObject(analysis?.signal)
  const explanationPayload = analysis?.analysis_explanation || explanation?.analysis_explanation || explanation || {}
  const liquidity = safeObject(analysis?.liquidity_map)
  const poi = safeObject(analysis?.poi_engine)
  const confirmation = safeObject(analysis?.confirmation_engine)
  const score = safeObject(analysis?.score_engine || analysis?.smart_score_v2)
  const liveSync = safeObject(analysis?.live_ohlc_sync)
  const tradePlan = safeObject(analysis?.trade_plan)
  const planTargets = safeArray(tradePlan.take_profit_levels)
  const trustGate = safeObject(analysis?.trust_gate)
  const keyZones = safeObject(analysis?.key_zones)
  const primaryDiamondZone = safeObject(keyZones.primary_zone)
  const diamondMtf = safeObject(keyZones.mtf_confluence)
  const news = safeObject(analysis?.news_intelligence)
  const xauPrecision = safeObject(analysis?.xau_confluence)
  const kTrend = safeObject(analysis?.session_framework?.k_trend)
  const smr = safeObject(analysis?.smr_model || analysis?.key_zones?.smr_model)
  const smrSession = safeObject(smr.session)
  const smt = safeObject(analysis?.smt_model || analysis?.key_zones?.smt_model)
  const dualCore = safeObject(analysis?.diamond_timeframe_model || analysis?.key_zones?.diamond_timeframe_model)
  const newsEvent = safeObject(news.primary_event || news.next_high_impact_event || news.next_event)
  const primaryDiamondScore = Number(primaryDiamondZone.diamond_score ?? keyZones.diamond_score ?? primaryDiamondZone.diamond_confidence_score ?? 0)
  const visibleDiamondFloor = diamondVisibleFloor(keyZones, primaryDiamondZone, analysis)
  const primaryDiamondGrade = primaryDiamondZone.diamond_grade || keyZones.diamond_grade || diamondGradeFromScore(primaryDiamondScore, false, visibleDiamondFloor)
  const publishedDiamond = Boolean(
    keyZones.diamond_display_status !== 'NO_QUALIFIED_DIAMOND'
    && primaryDiamondZone.strategy_confirmed_origin === true
    && primaryDiamondZone.display_as_diamond !== false
    && primaryDiamondScore >= visibleDiamondFloor
    && primaryDiamondGrade
  )
  const note = mode === 'TEST_MODE'
    ? 'Test Mode Analysis - not real market signal.'
    : mode === 'REAL_MODE'
      ? 'Real Data Analysis.'
      : 'Analysis waiting for internal SH data.'
  const overviewRows = [
    ['Asset', analysis?.symbol || '-'],
    ['Bias', analysis?.bias || signal.direction || '-'],
    ['Market State', analysis?.market_state || analysis?.structure?.market_state || analysis?.status || '-'],
    ['Score', signal.score ?? score.score ?? analysis?.score ?? '-'],
  ]
  const evidenceRows = [
    ['Data Mode', analysis?.data_mode_label || lockedMode?.data_mode_label || mode || '-'],
    ['Visual Source', analysis?.visual_source || 'TradingView Live'],
    ['Analysis Source', analysis?.analysis_data_source || '-'],
    ['Feed Match', analysis?.provider_alignment?.status || '-'],
    ['Live Sync', liveSync.status || (liveSync.ok ? 'SYNCED' : '-')],
    ['Liquidity', liquidity.reason || liquidity.stage || analysis?.liquidity || analysis?.liquidity_state || '-'],
    ['POI', poi.reason || poi.best_poi?.type || signal.setup_type || '-'],
    ['Confirmation', confirmation.reason || confirmation.confirmation_type || signal.confirmation_status || '-'],
    ['Session Stance', analysis?.session_framework?.stance || signal.session_stance || '-'],
    ['Session Position', analysis?.session_framework?.position || signal.session_position || '-'],
    ['K-Range Trend', `${kTrend.regime || '-'} (${kTrend.score ?? 0}) / ${kTrend.confirmation?.replaceAll('_', ' ') || '-'}`],
    ['K-Range Target', `${kTrend.next_target_label || '-'} ${asPrice(kTrend.next_target)}`],
    ['SMR Model', `${String(smr.pattern_state || smr.status || '-').replaceAll('_', ' ')} / ${smr.score ?? 0}`],
    ['SMR Timing', `${smrSession.name?.replaceAll('_', ' ') || '-'} (${smrSession.quality || '-'}) / ${smr.execution_gate || '-'}`],
    ['SMR Next', smr.next_trigger || '-'],
    ['SMT Companion', `${smt.companion_symbol || '-'} / ${String(smt.state || smt.status || '-').replaceAll('_', ' ')}`],
    ['SMT Confidence', smt.direction && smt.direction !== 'WAIT' ? `${smt.direction} / ${smt.confidence ?? 0}%` : 'No active divergence'],
    ['SMT Feed', `${smt.matched_candles ?? 0} matched / ${Math.round(Number(smt.coverage || 0) * 100)}% coverage`],
    ['Dual-Core', `${dualCore.focus_timeframe || '-'} / ${String(dualCore.state || '-').replaceAll('_', ' ')} / ${dualCore.grade || '-'} ${dualCore.score ?? 0}`],
    ['Core Agreement', `${dualCore.agreement?.aligned ?? 0}/${dualCore.agreement?.total ?? 0} aligned / ${dualCore.execution_gate || '-'}`],
    ['Core Next', dualCore.next_trigger || '-'],
    ['Diamond State', publishedDiamond ? keyZones.strategy_state?.replaceAll('_', ' ') || keyZones.directional_bias?.replaceAll('_', ' ') || 'WATCHING' : `Scanning for ${visibleDiamondFloor}+ quality`],
    ['Diamond Line', publishedDiamond ? asPrice(primaryDiamondZone.line) : '-'],
    ['Diamond Grade', publishedDiamond ? `${primaryDiamondGrade} / ${primaryDiamondScore}` : 'Not published'],
    ['Diamond Lifecycle', publishedDiamond ? primaryDiamondZone.lifecycle?.replaceAll('_', ' ') || '-' : '-'],
    ['Diamond Confirmation', publishedDiamond ? keyZones.confirmation_state?.replaceAll('_', ' ') || '-' : '-'],
    ['Diamond Rejection', publishedDiamond ? `${keyZones.rejection_status?.replaceAll('_', ' ') || '-'} (${keyZones.rejection_score ?? 0})` : '-'],
    ['Diamond Strength', publishedDiamond ? `${keyZones.zone_strength_score ?? '-'} / ${keyZones.execution_quality?.replaceAll('_', ' ') || '-'}` : '-'],
    ['Diamond MTF', `${diamondMtf.state?.replaceAll('_', ' ') || '-'} (${diamondMtf.score ?? 0})`],
    ['Diamond Invalidation', publishedDiamond ? asPrice(keyZones.invalidation_level) : '-'],
    ...(xauPrecision.status === 'READY' ? [
      ['XAU Confluence', `${xauPrecision.state?.replaceAll('_', ' ') || '-'} / Grade ${xauPrecision.quality_grade || '-'}`],
      ['Engine Agreement', `${xauPrecision.agreement?.passed ?? 0}/${xauPrecision.agreement?.total ?? 0} (${xauPrecision.validation_score ?? 0}/100)`],
      ['XAU Execution Gate', xauPrecision.execution_gate || '-'],
      ['XAU Next Trigger', xauPrecision.next_trigger || '-'],
    ] : []),
    ['News Risk', news.risk_level || '-'],
    ['News Gate', news.execution_gate?.replaceAll('_', ' ') || '-'],
    ['News Event', newsEvent.title || '-'],
    ['News Release', formatNewsTime(newsEvent.timestamp)],
  ]
  const summary = explanationPayload.summary || signal.explanation || signal.final_action || analysis?.message || analysis?.error || 'No analysis explanation is available yet.'
  const nextTrigger = explanationPayload.next_trigger || explanationPayload.waiting_condition
  const warnings = safeArray(explanationPayload.warnings || signal.warnings)
  const decision = analysis?.final_decision || signal.status || 'Waiting for analysis'
  const resultScore = signal.score ?? score.score ?? analysis?.score ?? 0
  useEffect(() => {
    if (!open) return
    const hasSetup = ['ACTIONABLE', 'CANDIDATE'].includes(String(tradePlan.status || '').toUpperCase())
    setResultTab(hasSetup ? 'setup' : 'overview')
  }, [open, analysis?.journal_entry?.id, tradePlan.status])
  return (
    <aside className={`analysis-result-drawer ${open ? 'open' : ''}`}>
      <div className="analysis-result-panel">
        <header className="analysis-result-head">
          <div>
            <span>Analysis Result</span>
            <strong>{analysis?.symbol || 'Market'} Intelligence</strong>
            <small>{note}</small>
          </div>
          <nav className="analysis-result-actions" aria-label="Analysis result actions">
            <button aria-label="Export analysis result" title="Export analysis" onClick={onExport} disabled={!analysis}>
              <Download size={16} />
            </button>
            <button aria-label="Close analysis result" title="Close" onClick={onClose}>
              <X size={17} />
            </button>
          </nav>
        </header>
        <nav className="analysis-result-tabs" aria-label="Analysis result sections">
          {['overview', 'setup', 'evidence'].map(tab => (
            <button className={resultTab === tab ? 'active' : ''} key={tab} onClick={() => setResultTab(tab)}>
              {tab}
            </button>
          ))}
        </nav>
        {resultTab === 'overview' && (
          <div className="analysis-result-view">
            <section className="analysis-result-hero">
              <span>Final Decision</span>
              <strong className={tone(decision)}>{decision}</strong>
              <div>
                <p><span>Score</span><b>{clampPercent(resultScore)}</b></p>
                <p><span>Trust</span><b className={tone(trustGate.status)}>{trustGate.status || analysis?.provider_alignment?.status || '-'}</b></p>
              </div>
            </section>
            <div className="analysis-result-grid compact">
              {overviewRows.map(([label, value]) => (
                <p key={label}><span>{label}</span><strong>{safeText(value, '-')}</strong></p>
              ))}
            </div>
            <section className="analysis-reason-panel">
              <span>Reason</span>
              <p>{summary}</p>
              {nextTrigger && <em>{nextTrigger}</em>}
            </section>
          </div>
        )}
        {resultTab === 'setup' && (
          <div className="analysis-result-view">
            {tradePlan.status ? (
              <section className={`analysis-trade-plan ${tone(tradePlan.status)}`}>
                <div className="analysis-trade-plan-head">
                  <div>
                    <span>Best Available Setup</span>
                    <strong>{tradePlan.label || `${tradePlan.direction} ${tradePlan.order_type}`}</strong>
                  </div>
                  <em>{safeText(tradePlan.status, 'PENDING').replaceAll('_', ' ')}</em>
                </div>
                {tradePlan.status !== 'NO_VALID_SETUP' && tradePlan.status !== 'BLOCKED_BY_DATA_TRUST' && (
                  <div className="analysis-trade-plan-grid">
                    <p><span>Order</span><strong>{tradePlan.order_type || '-'}</strong></p>
                    <p><span>Entry</span><strong>{asPrice(tradePlan.entry_price)}</strong></p>
                    <p><span>Stop Loss</span><strong className="bad">{asPrice(tradePlan.stop_loss)}</strong></p>
                    <p><span>TP1</span><strong className="good">{asPrice(planTargets[0])}</strong></p>
                    <p><span>TP2</span><strong className="good">{asPrice(planTargets[1])}</strong></p>
                    <p><span>Risk : Reward</span><strong>{tradePlan.risk_reward ? `1 : ${tradePlan.risk_reward}` : '-'}</strong></p>
                  </div>
                )}
                <p className="analysis-trade-plan-evidence"><b>Evidence:</b> {tradePlan.zone_source || 'No valid market-structure entry evidence.'}</p>
                {tradePlan.stop_model && <p className="analysis-trade-plan-model"><b>Risk model:</b> {tradePlan.stop_model} / {tradePlan.target_model}</p>}
                {safeArray(tradePlan.missing_conditions).length > 0 && (
                  <p className="analysis-trade-plan-trigger"><b>Next condition:</b> {safeArray(tradePlan.missing_conditions).join(' / ')}</p>
                )}
              </section>
            ) : (
              <section className="analysis-result-empty"><strong>No validated setup</strong><p>{summary}</p></section>
            )}
          </div>
        )}
        {resultTab === 'evidence' && (
          <div className="analysis-result-view">
            <div className="analysis-result-grid">
              {evidenceRows.map(([label, value]) => (
                <p key={label}><span>{label}</span><strong>{safeText(value, '-')}</strong></p>
              ))}
            </div>
            {warnings.length > 0 && (
              <section className="analysis-warning-panel">
                <span>Warnings</span>
                <ul>{warnings.slice(0, 5).map(item => <li key={item}>{item}</li>)}</ul>
              </section>
            )}
          </div>
        )}
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
  onFixGap,
  onImportHistory,
  onGenerateTestHistory,
  onLiveOnlyMode,
  onArchiveStale,
  onClearTestHistory,
  actionsDisabled,
}) {
  if (!alignment || !alignment.alignment_status || alignment.healthy) return null
  const status = alignment.alignment_status
  if (status === 'TEST_MODE') return null
  return (
    <div className={`history-alignment-panel ${tone(status)}`}>
      <div className="history-alignment-head">
        <strong>{status.replaceAll('_', ' ')}</strong>
        <span>{alignment.warning_message || 'History candles do not match current live price.'}</span>
      </div>
      <div className="history-alignment-grid">
        <span>Live Price <strong>{asPrice(alignment.latest_live_price ?? alignment.live_price)}</strong></span>
        <span>History Close <strong>{asPrice(alignment.latest_history_close)}</strong></span>
        <span>Gap <strong>{asPrice(alignment.price_gap)}</strong></span>
        <span>Action <strong>{String(alignment.recommended_action || '-').replaceAll('_', ' ')}</strong></span>
      </div>
      <div className="history-alignment-actions">
        <button onClick={onFixGap} disabled={actionsDisabled}>Fix Data</button>
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
      <strong>LIVE SERVICE PAUSED</strong>
      <span>The last chart remains visible while live updates reconnect.</span>
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
      <div><span>Service</span><strong className={tone(locked.backend_status)}>{locked.backend_status === 'ONLINE' ? 'ONLINE' : 'UNAVAILABLE'}</strong></div>
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
  onRefresh,
  resetSignal,
  onResetScale,
  onTimeframeChange,
  onOpenOverlayMenu,
  onOpenDataHub,
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
  const [chartEngine, setChartEngine] = useState(null)
  const [chartReady, setChartReady] = useState(false)
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
    let active = true
    loadChartEngine()
      .then(engine => {
        if (active) setChartEngine(engine)
      })
      .catch(err => {
        if (active) setChartError(err?.message || 'Chart engine could not be loaded.')
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!chartEngine || !containerRef.current || chartRef.current) return undefined
    const { CandlestickSeries, createChart, LineSeries } = chartEngine
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
      setChartReady(true)
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
  }, [chartEngine])

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
  }, [datasetKey, chartGapDetected, historyCandles, liveCandles, activeCandles, displayCandles, showStaleHistory, showMovingAverage, chartReady])

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
  }, [overlayItems, overlayVisibility, chartGapDetected, liveCandles.length, activeCandles.length, displayCandles, latestPrice, showSetupLevels, chartReady])

  useEffect(() => {
    savedRangeRef.current = null
    focusLiveSegment()
    updateGapMarker()
  }, [resetSignal, chartReady])

  useEffect(() => {
    updateGapMarker()
  }, [chartData?.gap_marker, chartReady])

  return (
    <div className="chart-wrap">
      <div className="chart-headline">
        <div className="chart-titlebar">
          <strong>XAUUSD</strong>
          <span>{timeframeLabel(datasetKey)} candle chart</span>
        </div>
        <div className="chart-head-actions">
          <span className={`chart-live-badge ${dataIntegrity?.test_data_present ? 'test' : 'live'}`}>
            <i />
            {chartSourceLabel}
          </span>
          {Number.isFinite(Number(latestPrice)) && <PriceMarker price={latestPrice} status={backendOffline ? 'STALE' : providerStatus?.status || 'LIVE'} />}
        </div>
      </div>

      <div className="tv-chart-shell">
        <LiveCandleInfoBar health={candleHealth} latestPrice={latestPrice} timeframe={datasetKey} />
        <WarmupNotice health={candleHealth} timeframe={datasetKey} />
        <HistoryAlignmentPanel
          alignment={alignment}
          onFixGap={onFixGap}
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
              <strong>{backendOffline ? 'Live chart paused' : chartError ? 'Chart unavailable' : 'Market history is not ready'}</strong>
              <p>{backendOffline ? 'Live updates are temporarily unavailable. Please try again shortly.' : publicNotice(emptyMessage || 'Refresh to load the latest market history.')}</p>
            </div>
            <div className="chart-empty-actions">
              <button onClick={onSmartSetup} disabled={actionsDisabled}>Smart Setup</button>
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

function HistogramPanel({ title, subtitle = 'positive / negative', data = [], mode = 'pressure', snapshot = {} }) {
  const items = safeArray(data)
  const values = items.map(item => Number(item?.value)).filter(Number.isFinite)
  const maxAbs = mode === 'rsi' ? 50 : Math.max(...values.map(Math.abs), 1)
  const top = maxAbs
  const bottom = -maxAbs
  const snapshotValue = mode === 'rsi' ? snapshot.value : snapshot.histogram
  const snapshotState = mode === 'rsi' ? snapshot.zone : snapshot.bias
  const snapshotMomentum = snapshot.momentum || 'WAITING'
  const snapshotDetail = snapshot.divergence && snapshot.divergence !== 'NONE'
    ? `${snapshot.divergence} divergence`
    : mode === 'rsi' ? snapshotMomentum : snapshot.cross || snapshot.phase || snapshotMomentum
  const stateClass = String(snapshotState || 'neutral').toLowerCase()
  return (
    <section className={`indicator-panel ${stateClass}`}>
      <div className="indicator-title">
        <div><strong>{title}</strong><b>{asIndicatorValue(snapshotValue)}</b></div>
        <span>{subtitle}</span>
        <em>{indicatorStateLabel(snapshotState)} / {indicatorStateLabel(snapshotMomentum)}</em>
        <small>{indicatorStateLabel(snapshotDetail)}</small>
      </div>
      <div className="histogram-body">
        <div className="histogram-bars">
          <span className="zero-line" />
          {mode === 'rsi' && <><span className="rsi-guide upper">70</span><span className="rsi-guide lower">30</span></>}
          {items.slice(-64).map((item, idx) => {
            const value = Number(item?.value) || 0
            const height = Math.max(8, Math.min(50, Math.abs(value) / maxAbs * 48))
            const positive = value >= 0
            const color = mode === 'rsi' ? rsiBarColor(item) : macdBarColor(item)
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
          <span>{mode === 'rsi' ? '70' : Math.round(top)}</span>
          <span>{mode === 'rsi' ? '50' : '0'}</span>
          <span>{mode === 'rsi' ? '30' : Math.round(bottom)}</span>
        </div>
      </div>
    </section>
  )
}

function IndicatorPanel({ panels, dataIntegrity }) {
  const panelData = safeObject(panels?.indicator_panels)
  const indicatorMeta = safeObject(panelData.indicator_meta)
  const indicatorSnapshot = deriveIndicatorSnapshot(panelData)
  const macdSnapshot = safeObject(indicatorSnapshot.macd)
  const rsiSnapshot = safeObject(indicatorSnapshot.rsi)
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
          <HistogramPanel
            title={indicatorMeta.market_pressure?.name || 'MACD Histogram'}
            subtitle={indicatorMeta.market_pressure?.parameters || 'EMA 12 / 26 / 9'}
            data={panelData.market_pressure || panelData.boys_selling || []}
            snapshot={macdSnapshot}
          />
          <HistogramPanel
            title={indicatorMeta.liquidity_pressure?.name || 'RSI 14'}
            subtitle={indicatorMeta.liquidity_pressure?.parameters || 'Centered at 50'}
            mode="rsi"
            data={panelData.liquidity_pressure || panelData.balance || panelData.bearishness || []}
            snapshot={rsiSnapshot}
          />
          {!!safeArray(panelData.setup_quality).length && <HistogramPanel title="Setup Quality" data={panelData.setup_quality} />}
        </>
      )}
      <section className={`indicator-confluence ${String(indicatorSnapshot.confluence || 'waiting').toLowerCase()}`}>
        <Activity size={14} />
        <div><span>Indicator Confluence</span><strong>{String(indicatorSnapshot.confluence || 'WAITING').replaceAll('_', ' ')}</strong></div>
        <small>{indicatorSnapshot.quality_grade || '-'} / {clampPercent(indicatorSnapshot.quality_score)}%</small>
      </section>
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
      <div><span>Service</span><strong className={tone(locked.backend_status)}>{locked.backend_status === 'ONLINE' ? 'ONLINE' : 'UNAVAILABLE'}</strong></div>
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
        <p>{signal.final_action || analysis?.analysis_explanation?.reason || 'Auto Engine refreshes the setup after each completed candle.'}</p>
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
  if (!rows.length) return null
  return (
    <section className="workflow-panel">
      <header>
        <strong>Institutional Workflow</strong>
        <span>Data Integrity to Final Decision</span>
      </header>
      {rows.map((row, index) => (
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

function LiveAnalysisPanel({ asset = 'XAUUSD', analysis, explanation, lockedMode, latestPrice, timeframe, loading, backendOffline }) {
  const signal = safeObject(analysis?.signal)
  const tradePlan = safeObject(analysis?.trade_plan)
  const planTargets = safeArray(tradePlan.take_profit_levels)
  const scoreEngine = safeObject(analysis?.score_engine || analysis?.smart_score_v2)
  const liquidity = safeObject(analysis?.liquidity_map)
  const poi = safeObject(analysis?.poi_engine)
  const payload = analysis?.analysis_explanation || explanation?.analysis_explanation || explanation || {}
  const trustGate = safeObject(analysis?.trust_gate)
  const decision = loading
    ? 'Syncing Live Market Data'
    : backendOffline
      ? 'Service Unavailable'
      : analysis?.final_decision || signal.status || lockedMode?.analysis_state || 'Ready for Live Analysis'
  const direction = safeText(tradePlan.direction || signal.direction || payload.direction, 'WAIT').toUpperCase()
  const directionClass = direction === 'BUY' ? 'buy' : direction === 'SELL' ? 'sell' : 'wait'
  const scoreValue = tradePlan.confidence ?? signal.score ?? scoreEngine.score ?? analysis?.score
  const score = scoreValue === null || scoreValue === undefined ? '-' : clampPercent(scoreValue)
  const setup = tradePlan.status === 'BLOCKED_BY_DATA_TRUST'
    ? 'Research only'
    : tradePlan.status === 'NO_VALID_SETUP'
    ? 'No evidence-backed entry'
    : tradePlan.order_type
    ? `${tradePlan.order_type} / ${tradePlan.setup_type || 'Setup'}`
    : signal.setup_type && signal.setup_type !== 'None'
      ? signal.setup_type
    : poi.best_poi?.type || 'Waiting'
  const summary = payload.summary || signal.explanation || signal.final_action || (
    loading
      ? `Refreshing 5M, 15M, 1H, 4H, and 1D ${asset} candles before analysis.`
      : `The engine is ready to sync the latest ${asset} candles and scan for a setup.`
  )
  const nextTrigger = payload.next_trigger || payload.waiting_condition || liquidity.reason || signal.confirmation_status

  return (
    <section className={`live-analysis-panel ${tone(decision)} ${loading ? 'loading' : ''}`} aria-live="polite">
      <header className="live-analysis-header">
        <div>
          <span>Live Analysis</span>
          <strong>{decision}</strong>
        </div>
        <div className="live-analysis-badges">
          <b className={directionClass}>{direction}</b>
          <em>{score === '-' ? 'Score -' : `Score ${score}`}</em>
        </div>
      </header>

      {trustGate.status && (
        <div className={`analysis-trust-gate ${trustGate.trusted ? 'trusted' : 'blocked'}`}>
          <ShieldCheck size={15} />
          <span><strong>{trustGate.status}</strong><small>{trustGate.reason}</small></span>
        </div>
      )}

      <div className="live-analysis-metrics">
        <p><span>Bias</span><strong>{analysis?.bias || 'Waiting'}</strong></p>
        <p><span>Order Setup</span><strong title={setup}>{setup}</strong></p>
        <p><span>Entry</span><strong>{asPrice(tradePlan.status ? tradePlan.entry_price : analysis?.current_price || latestPrice)}</strong></p>
        <p><span>Stop Loss</span><strong className="bad">{asPrice(tradePlan.stop_loss)}</strong></p>
        <p><span>Take Profit 1</span><strong className="good">{asPrice(planTargets[0])}</strong></p>
        <p><span>Risk : Reward</span><strong>{tradePlan.risk_reward ? `1 : ${tradePlan.risk_reward}` : '-'}</strong></p>
      </div>

      <div className="live-analysis-summary">
        <p>{summary}</p>
        {nextTrigger && <span><b>Next:</b> {nextTrigger}</span>}
      </div>
    </section>
  )
}

function SetupValidationPanel({ analysis, loading = false }) {
  const gates = setupValidationGates(analysis)
  const passed = gates.filter(gate => gate.pass).length

  return (
    <section className="setup-validation-panel" aria-label="Setup validation">
      <header className="setup-validation-head">
        <div>
          <ShieldCheck size={16} />
          <span>
            <strong>Setup Validation</strong>
            <small>Evidence required before execution</small>
          </span>
        </div>
        <b className={passed === gates.length ? 'good' : 'warn'}>{loading ? 'Checking' : `${passed}/${gates.length}`}</b>
      </header>
      <div className="setup-validation-progress" aria-label={`${passed} of ${gates.length} setup checks passed`}>
        <span style={{ width: `${(passed / gates.length) * 100}%` }} />
      </div>
      <div className="setup-validation-list">
        {gates.map(gate => (
          <div className={`setup-validation-row ${gate.pass ? 'pass' : 'wait'}`} key={gate.label}>
            {gate.pass ? <CheckCircle2 size={16} /> : <CircleDashed size={16} />}
            <span>
              <strong>{gate.label}</strong>
              <small title={gate.reason}>{gate.reason}</small>
            </span>
            <em>{gate.timeframe}</em>
            <b>{gate.pass ? 'Pass' : 'Wait'}</b>
          </div>
        ))}
      </div>
    </section>
  )
}

function OverlayMenuDrawer({ open, onClose, overlays = {}, visibility = {}, onToggle }) {
  const groups = ['Core', 'Liquidity', 'Session', 'Setup', 'Moving Average', 'Other']
  const grouped = Object.entries(safeObject(overlays)).reduce((acc, [key, item]) => {
    const group = item.group === 'Debug' ? 'Other' : item.group || 'Other'
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
          <p><span>Service</span><strong className={tone(dataHub?.backend_status)}>{dataHub?.backend_status === 'ONLINE' ? 'ONLINE' : 'UNAVAILABLE'}</strong></p>
          <p><span>Provider</span><strong className={tone(dataHub?.provider_status)}>{dataHub?.provider_status || '-'}</strong></p>
          <p><span>Candle Source</span><strong>{dataHub?.candle_source || '-'}</strong></p>
          <p><span>Latest Price</span><strong>{asPrice(dataHub?.latest_live_price)}</strong></p>
          <p><span>Latest 15M</span><strong>{dataHub?.latest_primary_candle_time || '-'}</strong></p>
          <p><span>Freshness</span><strong className={tone(dataHub?.history_freshness)}>{dataHub?.history_freshness || '-'}</strong></p>
          <p><span>Gap Status</span><strong className={tone(dataHub?.gap_status)}>{dataHub?.gap_status || '-'}</strong></p>
          <p><span>Readiness</span><strong className={readiness.ready ? 'good' : 'warn'}>{readiness.state || '-'}</strong></p>
          <p><span>Update Status</span><strong>{dataHub?.last_error ? 'Needs attention' : 'Ready'}</strong></p>
        </section>
        <section className="drawer-section">
          <h3>Actions</h3>
          <div className="drawer-grid">
            <label className="drawer-button file-label">
              Import Real History
              <input type="file" accept=".csv" onChange={onImportReal} />
            </label>
            <button onClick={onLiveOnly} disabled={actionsDisabled}>Live Only Mode</button>
            <button onClick={onFixGap} disabled={actionsDisabled}>Fix Gap</button>
            <button onClick={onSmartSetup} disabled={actionsDisabled}>Smart Setup</button>
            <button onClick={onExport} disabled={actionsDisabled}>Export Candles</button>
            <button onClick={onWizard} disabled={actionsDisabled}>Market Data Setup</button>
            <button onClick={onReset} disabled={actionsDisabled}>Reset Market History</button>
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
          <h3>Market Data Setup</h3>
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
  counts = {},
  onStart = () => {},
  onStop = () => {},
  onSeed = () => {},
  onDownload = () => {},
  onRefresh = () => {},
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
  chartMode = 'tradingview',
  onChartMode = () => {},
  tvSymbol = 'OANDA:XAUUSD',
  onTvSymbol = () => {},
  engineMode = 'balanced',
  onEngineMode = () => {},
  oandaToken = '',
  setOandaToken = () => {},
  oandaEnvironment = 'practice',
  setOandaEnvironment = () => {},
  onSaveOanda = () => {},
  oandaVerification = null,
  telegramSettings = null,
  telegramBotToken = '',
  setTelegramBotToken = () => {},
  telegramChatId = '',
  setTelegramChatId = () => {},
  telegramEnabled = false,
  setTelegramEnabled = () => {},
  telegramVerification = null,
  onSaveTelegram = () => {},
  telegramCommunity = null,
  telegramCommunityInput = '',
  setTelegramCommunityInput = () => {},
  telegramCommunitySave = null,
  onSaveTelegramCommunity = () => {},
  providerAlignment = null,
  onUploadCsv = () => {},
  onImportHistory = () => {},
  onClearLocalStorage = () => {},
  asset = 'XAUUSD',
}) {
  const { isAdmin } = useAuth()
  const canManageFeed = isAdmin
  const [settingsGroup, setSettingsGroup] = useState('Analysis')
  const [replaceTelegramConnection, setReplaceTelegramConnection] = useState(false)
  const oandaCredentialState = status?.settings?.oanda_credential_state || (status?.settings?.oanda_api_token ? 'SAVED' : 'NOT_CONFIGURED')
  const oandaCredentialSaved = Boolean(status?.settings?.oanda_api_token)
  const oandaRestore = status?.oanda_restore || null
  const activeCredentialSaved = oandaCredentialSaved
  const activeRestore = oandaRestore
  const activeToken = oandaToken
  const setActiveToken = setOandaToken
  const activeEnvironment = oandaEnvironment
  const setActiveEnvironment = setOandaEnvironment
  const environmentOptions = ['practice', 'live']
  const activeVerification = oandaVerification
  const saveActiveProvider = onSaveOanda
  const activeVisualSymbol = 'OANDA:XAUUSD'
  const selectedFeedMatched = providerAlignment?.matched === true && providerAlignment?.visual_symbol === activeVisualSymbol
  const telegramConnectionSaved = Boolean(telegramSettings?.bot_token_saved && telegramSettings?.chat_id_saved)
  const showTelegramCredentials = !telegramConnectionSaved || replaceTelegramConnection
  const menuActions = createMenuActions({
    'chart.tradingview': () => onChartMode('tradingview'),
    'chart.resetScale': onResetScale,
    'data.hub': onOpenDataHub,
    'data.realModeWizard': onRealModeWizard,
    'data.importRealHistory': onImportHistory,
    'data.generateTestHistory': onGenerateTestHistory,
    'data.clearTestHistory': onClearTestHistory,
    'data.liveOnlyMode': onLiveOnlyMode,
    'analysis.smartSetup': onSmartSetup,
    'analysis.fixGap': onFixGap,
    'analysis.clearCache': onClearCache,
    'system.backendHealth': onRefresh,
    'system.clearLocalStorage': onClearLocalStorage,
  }, {
    actionsDisabled,
    backendOffline,
    chartMode,
  })
  const baseMenuGroups = groupMenuActions(menuActions)
    .filter(section => isAdmin || !['Data', 'System'].includes(section.group))
    .map(section => asset === 'BTCUSD'
      ? { ...section, actions: section.actions.filter(action => ['chart.tradingview', 'system.backendHealth', 'system.clearLocalStorage'].includes(action.id)) }
      : section)
    .filter(section => section.actions.length)
  const menuGroups = canManageFeed
    ? [
        ...baseMenuGroups,
        ...(asset === 'XAUUSD' ? [{ group: 'Feed', actions: [] }] : []),
        { group: 'Alerts', actions: [] },
      ]
    : baseMenuGroups
  const activeMenuGroup = menuGroups.find(section => section.group === settingsGroup)
    || menuGroups.find(section => section.group === 'Analysis')
    || menuGroups[0]
  const ActiveGroupIcon = MENU_GROUP_ICONS[activeMenuGroup?.group] || Settings
  const activeActionId = 'chart.tradingview'
  const runAction = action => {
    if (!action.enabled) return
    action.handler()
    onClose()
  }

  return (
    <aside className={`mobile-drawer ${open ? 'open' : ''}`}>
      <div className="drawer-panel">
        <div className="drawer-head">
          <div>
            <span>Workspace</span>
            <strong>Settings</strong>
            <small>{asset} / {MARKET_ASSETS[asset]?.label}</small>
          </div>
          <button title="Close settings" aria-label="Close settings" onClick={onClose}><X size={18} /></button>
        </div>
        <nav className="settings-tabs" aria-label="Settings sections">
          {menuGroups.map(section => {
            const GroupIcon = MENU_GROUP_ICONS[section.group] || Settings
            return (
              <button
                className={activeMenuGroup?.group === section.group ? 'active' : ''}
                key={section.group}
                onClick={() => setSettingsGroup(section.group)}
              >
                <GroupIcon size={15} />
                <span>{section.group}</span>
              </button>
            )
          })}
        </nav>
        {activeMenuGroup?.actions?.length > 0 && (
          <section className="drawer-section settings-command-section">
            <h3><ActiveGroupIcon size={15} /> {activeMenuGroup.group}</h3>
            <div className="settings-command-list">
              {activeMenuGroup.actions.map(action => {
                const isImport = action.id === 'data.importRealHistory'
                const active = action.id === activeActionId
                if (isImport) {
                  return (
                    <label
                      className={`settings-command file-label ${active ? 'active' : ''} ${!action.enabled ? 'disabled' : ''}`}
                      key={action.id}
                      title={action.description}
                    >
                      <span className="settings-command-icon"><ActiveGroupIcon size={16} /></span>
                      <span className="settings-command-copy"><strong>{action.label}</strong><small>{action.description}</small></span>
                      <ChevronRight size={16} />
                      <input type="file" accept=".csv" onChange={action.handler} disabled={!action.enabled} />
                    </label>
                  )
                }
                return (
                  <button
                    className={`settings-command ${active ? 'active' : ''}`}
                    disabled={!action.enabled}
                    key={action.id}
                    onClick={() => runAction(action)}
                    title={action.description}
                  >
                    <span className="settings-command-icon"><ActiveGroupIcon size={16} /></span>
                    <span className="settings-command-copy"><strong>{action.label}</strong><small>{action.description}</small></span>
                    <ChevronRight size={16} />
                  </button>
                )
              })}
            </div>
          </section>
        )}
        {canManageFeed && activeMenuGroup?.group === 'Feed' && (
          <section className="drawer-section provider-config-section">
            <h3><ShieldCheck size={15} /> Matched Market Feed</h3>
            {asset === 'XAUUSD' ? (
              <div className="provider-config-form">
                <div className="provider-config-status">
                  <span>TradingView</span>
                  <strong>{activeVisualSymbol}</strong>
                  <b className={selectedFeedMatched ? 'good' : 'warn'}>{selectedFeedMatched ? 'MATCHED' : 'VERIFY'}</b>
                </div>
                <div className={`provider-credential-state ${activeCredentialSaved ? 'saved' : 'missing'}`}>
                  <ShieldCheck size={15} />
                  <span>
                    <strong>{activeRestore?.running ? 'RESTORING CONNECTION' : activeCredentialSaved ? 'CONNECTION SAVED' : 'CONNECTION NEEDED'}</strong>
                    <small>
                      {activeRestore?.running
                        ? 'Synchronizing matched OANDA candle history.'
                        : activeCredentialSaved
                          ? `Saved securely / ${activeEnvironment}`
                          : 'Add an OANDA access token once.'}
                    </small>
                  </span>
                </div>
                <label>
                  <span>OANDA connection key</span>
                  <input
                    type="password"
                    value={activeToken}
                    onChange={event => setActiveToken(event.target.value)}
                    placeholder={activeCredentialSaved ? 'Saved securely - enter only to replace' : 'Access token'}
                    autoComplete="new-password"
                  />
                </label>
                <div className="provider-environment" aria-label="OANDA environment">
                  {environmentOptions.map(environment => (
                    <button
                      type="button"
                      className={activeEnvironment === environment ? 'active' : ''}
                      key={environment}
                      onClick={() => setActiveEnvironment(environment)}
                    >
                      {environment}
                    </button>
                  ))}
                </div>
                <button
                  className="provider-save-button"
                  onClick={saveActiveProvider}
                  disabled={(!activeToken.trim() && !activeCredentialSaved) || actionsDisabled || activeVerification?.status === 'VERIFYING'}
                >
                  {activeVerification?.status === 'VERIFYING'
                    ? 'Verifying and syncing...'
                    : activeCredentialSaved && !activeToken.trim()
                      ? 'Re-check Saved OANDA'
                      : 'Verify & Save OANDA'}
                </button>
                {activeVerification && activeVerification.status !== 'VERIFYING' && (
                  <div className={`provider-verification ${activeVerification.ok ? 'good' : 'bad'}`}>
                    <strong>{activeVerification.status || 'NOT VERIFIED'}</strong>
                    <span>{activeVerification.message || 'Provider verification failed.'}</span>
                    {activeVerification.ok && (
                      <small>{activeVerification.environment} / {activeVerification.latency_ms}ms / {activeVerification.latest_candle_time || '-'}</small>
                    )}
                  </div>
                )}
                <small>Your connection is restored automatically. The saved key stays private and is never displayed.</small>
              </div>
            ) : (
              <div className="provider-config-form">
                <div className="provider-config-status">
                  <span>TradingView</span>
                  <strong>BINANCE:BTCUSDT</strong>
                  <b className={providerAlignment?.matched ? 'good' : 'warn'}>{providerAlignment?.status || 'AUTO SYNC'}</b>
                </div>
                <p>Binance public BTCUSDT candles require no connection key. Auto Engine synchronizes each completed candle.</p>
              </div>
            )}
          </section>
        )}
        {canManageFeed && activeMenuGroup?.group === 'Alerts' && (
          <section className="drawer-section provider-config-section telegram-config-section">
            <h3><Bell size={15} /> Telegram Group Alerts</h3>
            <div className="provider-config-form">
              <div className="telegram-community-admin">
                <div className="telegram-community-admin-head">
                  <i><Send size={16} /></i>
                  <span>
                    <strong>Community Join Link</strong>
                    <small>Shown to every user inside the Account panel.</small>
                  </span>
                  <b className={telegramCommunity?.configured ? 'good' : 'warn'}>
                    {telegramCommunity?.configured ? 'LIVE' : 'HIDDEN'}
                  </b>
                </div>
                <label>
                  <span>Telegram group invite link</span>
                  <input
                    type="url"
                    value={telegramCommunityInput}
                    onChange={event => setTelegramCommunityInput(event.target.value)}
                    placeholder="https://t.me/your_group"
                    autoComplete="url"
                    spellCheck="false"
                  />
                </label>
                <div className="telegram-community-admin-actions">
                  {telegramCommunity?.configured && (
                    <a href={telegramCommunity.url} target="_blank" rel="noreferrer">
                      <Globe2 size={14} /> Open group
                    </a>
                  )}
                  <button
                    type="button"
                    className="provider-save-button"
                    onClick={onSaveTelegramCommunity}
                    disabled={backendOffline || telegramCommunitySave?.status === 'SAVING'}
                  >
                    {telegramCommunitySave?.status === 'SAVING'
                      ? 'Saving...'
                      : telegramCommunityInput.trim() ? 'Save Community Link' : 'Remove Community Link'}
                  </button>
                </div>
                {telegramCommunitySave && telegramCommunitySave.status !== 'SAVING' && (
                  <div className={`provider-verification ${telegramCommunitySave.ok ? 'good' : 'bad'}`}>
                    <strong>{telegramCommunitySave.status || 'NOT SAVED'}</strong>
                    <span>{telegramCommunitySave.message || 'Could not save the community link.'}</span>
                  </div>
                )}
              </div>
              <div className="provider-config-status">
                <span>Delivery</span>
                <strong>Confirmed Diamonds</strong>
                <b className={telegramSettings?.status === 'READY' ? 'good' : 'warn'}>
                  {telegramSettings?.status || 'SETUP'}
                </b>
              </div>
              <div className={`provider-credential-state ${telegramConnectionSaved ? 'saved' : 'missing'}`}>
                {telegramConnectionSaved ? <CheckCircle2 size={15} /> : <Bell size={15} />}
                <span>
                  <strong>{telegramSettings?.enabled ? 'AUTO CONNECTED' : telegramConnectionSaved ? 'CONNECTION SAVED' : 'SETUP REQUIRED'}</strong>
                  <small>
                    {telegramConnectionSaved
                      ? `Group ${telegramSettings?.chat_id || 'saved securely'}${telegramSettings?.bot_username ? ` · @${telegramSettings.bot_username}` : ''}`
                      : 'Connect a Telegram bot and group chat.'}
                  </small>
                  {telegramConnectionSaved && <small>Restored automatically whenever the analyzer starts.</small>}
                </span>
              </div>
              {showTelegramCredentials && (
                <div className="telegram-credential-fields">
                  <label>
                    <span>Telegram bot token</span>
                    <input
                      type="password"
                      value={telegramBotToken}
                      onChange={event => setTelegramBotToken(event.target.value)}
                      placeholder={telegramConnectionSaved ? 'Enter a new token to replace' : 'BotFather token'}
                      autoComplete="new-password"
                    />
                  </label>
                  <label>
                    <span>Group chat ID</span>
                    <input
                      type="text"
                      value={telegramChatId}
                      onChange={event => setTelegramChatId(event.target.value)}
                      placeholder={telegramConnectionSaved ? 'Enter a new group chat ID' : '-100...'}
                      autoComplete="off"
                    />
                  </label>
                </div>
              )}
              <label className="telegram-enable-row">
                <input
                  type="checkbox"
                  checked={telegramEnabled}
                  onChange={event => setTelegramEnabled(event.target.checked)}
                />
                <span>
                  <strong>Alert new confirmed Diamonds</strong>
                  <small>One group message per unique completed-candle confirmation.</small>
                </span>
              </label>
              <div className="telegram-connection-actions">
                <button
                  className="provider-save-button"
                  onClick={onSaveTelegram}
                  disabled={
                    actionsDisabled
                    || telegramVerification?.status === 'VERIFYING'
                    || (telegramEnabled && !telegramBotToken.trim() && !telegramSettings?.bot_token_saved)
                    || (telegramEnabled && !telegramChatId.trim() && !telegramSettings?.chat_id_saved)
                  }
                >
                  {telegramVerification?.status === 'VERIFYING'
                    ? 'Checking Telegram...'
                    : telegramConnectionSaved && telegramEnabled && !replaceTelegramConnection
                      ? 'Check saved connection'
                      : telegramEnabled ? 'Test, Save & Enable' : 'Save Alert Settings'}
                </button>
                {telegramConnectionSaved && (
                  <button
                    type="button"
                    className="telegram-replace-button"
                    onClick={() => setReplaceTelegramConnection(current => !current)}
                    disabled={actionsDisabled || telegramVerification?.status === 'VERIFYING'}
                  >
                    {replaceTelegramConnection ? 'Cancel replace' : 'Replace connection'}
                  </button>
                )}
              </div>
              {telegramVerification && telegramVerification.status !== 'VERIFYING' && (
                <div className={`provider-verification ${telegramVerification.ok ? 'good' : 'bad'}`}>
                  <strong>{telegramVerification.status || 'NOT VERIFIED'}</strong>
                  <span>{telegramVerification.message || 'Telegram connection failed.'}</span>
                </div>
              )}
              <small>The saved connection remains active across refresh and restart. The bot token is never shown in the browser.</small>
            </div>
          </section>
        )}
        <div className="drawer-status">
          <div className="drawer-status-head"><Server size={15} /><span>Workspace status</span></div>
          <p><span>Asset</span><strong>{asset}</strong></p>
          <p><span>Data Mode</span><strong>{asset === 'XAUUSD' ? dataMode?.data_mode_label || '-' : 'AUTO SYNC'}</strong></p>
          <p><span>Service</span><strong>{backendOffline ? 'UNAVAILABLE' : health?.status === 'OK' ? 'ONLINE' : 'CONNECTING'}</strong></p>
          <p><span>Analysis Feed</span><strong>{providerAlignment?.provider || (asset === 'XAUUSD' ? 'OANDA' : 'Binance')}</strong></p>
          <p><span>Feed Match</span><strong className={providerAlignment?.matched ? 'good' : 'warn'}>{providerAlignment?.status || 'PENDING'}</strong></p>
          <p><span>Market Data</span><strong>{providerAlignment?.matched ? 'Ready' : 'Waiting'}</strong></p>
          {isAdmin && <p><span>Bot Guard</span><strong>{health?.human_verification?.configured ? 'TURNSTILE' : 'NOT CONFIGURED'}</strong></p>}
          {isAdmin && <p><span>Engine Core</span><strong>{health?.diamond_timeframe_engine || '-'}</strong></p>}
        </div>
        {asset === 'XAUUSD' && activeMenuGroup?.group === 'Feed' && (
          <div className="drawer-counts">
            {['1M', '5M', '15M', '1H', '4H', '1D'].map(tf => (
              <span key={tf}>{tf} <strong>{counts?.[tf] || 0}</strong></span>
            ))}
          </div>
        )}
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
  const { user, isAdmin } = useAuth()
  const initialViewRef = useRef(null)
  if (initialViewRef.current === null) {
    const initialAsset = getSavedAsset()
    const initialTimeframe = getSavedTimeframe()
    let cachedSnapshot = null
    try {
      cachedSnapshot = readChartSnapshot(localStorage, initialAsset, initialTimeframe)
    } catch (_) {
      // The local database snapshot will hydrate the chart when storage is blocked.
    }
    initialViewRef.current = { asset: initialAsset, timeframe: initialTimeframe, snapshot: cachedSnapshot }
  }
  const initialView = initialViewRef.current
  const initialChartCandles = safeArray(initialView.snapshot?.chart_data?.segments?.active).length
    ? safeArray(initialView.snapshot?.chart_data?.segments?.active)
    : safeArray(initialView.snapshot?.chart_data?.candles)
  const initialLatestPrice = initialView.snapshot?.chart_data?.latest_live_price
    ?? initialChartCandles.at(-1)?.close
  const [status, setStatus] = useState(() => initialView.snapshot ? ({
    status: 'RESTORED_SNAPSHOT',
    latest_price: initialLatestPrice,
    provider_name: initialView.snapshot.history_provenance?.source || '-',
  }) : null)
  const [health, setHealth] = useState(null)
  const [backendStatus, setBackendStatus] = useState(null)
  const [analysisState, setAnalysisState] = useState(null)
  const [apiErrorInfo, setApiErrorInfo] = useState(null)
  const [engineStatus, setEngineStatus] = useState(null)
  const [dataReadiness, setDataReadiness] = useState(null)
  const [dataIntegrity, setDataIntegrity] = useState(() => initialView.snapshot?.chart_data?.data_integrity || null)
  const [dataMode, setDataMode] = useState(null)
  const [dataHub, setDataHub] = useState(null)
  const [dataState, setDataState] = useState(null)
  const [gapDiagnosis, setGapDiagnosis] = useState(null)
  const [overlays, setOverlays] = useState(() => initialView.snapshot?.overlays || null)
  const [overlayStatus, setOverlayStatus] = useState(() => initialView.snapshot?.overlays?.overlay_status || null)
  const [panels, setPanels] = useState(() => initialView.snapshot?.panels || null)
  const [analysis, setAnalysis] = useState(null)
  const [analysisExplanation, setAnalysisExplanation] = useState(null)
  const [marketOverview, setMarketOverview] = useState(null)
  const [chartData, setChartData] = useState(() => initialView.snapshot?.chart_data || null)
  const [liveChartState, setLiveChartState] = useState(() => initialView.snapshot ? ({
    ok: true,
    status: 'RESTORED_SNAPSHOT',
    provider_alignment: initialView.snapshot.provider_alignment || null,
    history_provenance: initialView.snapshot.history_provenance || null,
  }) : null)
  const [mtfSnapshot, setMtfSnapshot] = useState(null)
  const [diamondHistory, setDiamondHistory] = useState(() => initialView.snapshot?.diamond_history || null)
  const [diamondValidation, setDiamondValidation] = useState(null)
  const [strategyGovernance, setStrategyGovernance] = useState(null)
  const [marketAlerts, setMarketAlerts] = useState(null)
  const [validationLoading, setValidationLoading] = useState(false)
  const [setupTracker, setSetupTracker] = useState(null)
  const [sessionFramework, setSessionFramework] = useState(null)
  const [keyZones, setKeyZones] = useState(null)
  const [newsIntelligence, setNewsIntelligence] = useState(null)
  const [newsCalendar, setNewsCalendar] = useState(null)
  const [newsCalendarOpen, setNewsCalendarOpen] = useState(false)
  const [newsCalendarLoading, setNewsCalendarLoading] = useState(false)
  const [newsCalendarError, setNewsCalendarError] = useState('')
  const [autoAnalysisStatus, setAutoAnalysisStatus] = useState(null)
  const [overlayVisibility, setOverlayVisibility] = useState({})
  const [timeframe, setTimeframe] = useState(initialView.timeframe)
  const [timeframeTransition, setTimeframeTransition] = useState({ active: false, target: null, phase: 'idle' })
  const [tradingStyle, setTradingStyle] = useState(getSavedTradingStyle)
  const [chartMode, setChartMode] = useState(getSavedChartMode)
  const [asset, setAsset] = useState(initialView.asset)
  const [tvSymbol, setTvSymbol] = useState(getSavedTradingViewSymbol)
  const [mobileTab, setMobileTab] = useState('live')
  const [isMobileLayout, setIsMobileLayout] = useState(false)
  const [oandaToken, setOandaToken] = useState('')
  const [oandaEnvironment, setOandaEnvironment] = useState('practice')
  const [oandaVerification, setOandaVerification] = useState(null)
  const [telegramSettings, setTelegramSettings] = useState(null)
  const [telegramBotToken, setTelegramBotToken] = useState('')
  const [telegramChatId, setTelegramChatId] = useState('')
  const [telegramEnabled, setTelegramEnabled] = useState(false)
  const [telegramVerification, setTelegramVerification] = useState(null)
  const [telegramCommunity, setTelegramCommunity] = useState({
    configured: /^https:\/\/(t\.me|telegram\.me)\//i.test(DEFAULT_TELEGRAM_COMMUNITY_URL),
    url: DEFAULT_TELEGRAM_COMMUNITY_URL || null,
  })
  const [telegramCommunityInput, setTelegramCommunityInput] = useState(DEFAULT_TELEGRAM_COMMUNITY_URL)
  const [telegramCommunitySave, setTelegramCommunitySave] = useState(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [isDataHubOpen, setIsDataHubOpen] = useState(false)
  const [overlayMenuOpen, setOverlayMenuOpen] = useState(false)
  const [analysisDrawerOpen, setAnalysisDrawerOpen] = useState(false)
  const [fixGapOpen, setFixGapOpen] = useState(false)
  const [alertCenterOpen, setAlertCenterOpen] = useState(false)
  const [accountPanelOpen, setAccountPanelOpen] = useState(false)
  const [mobileFocus, setMobileFocus] = useState('chart')
  const [mobileFocusRequest, setMobileFocusRequest] = useState(null)
  const [wizardResult, setWizardResult] = useState(null)
  const [boot, setBoot] = useState({ phase: 'STARTING', slow: false, continueOffline: false })
  const [showStaleHistory, setShowStaleHistory] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [resetSignal, setResetSignal] = useState(0)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const refreshInFlightRef = useRef(false)
  const chartLivePollRef = useRef(false)
  const liveCandleSignatureRef = useRef('')
  const liveAnalysisSignatureRef = useRef('')
  const oandaSettingsHydratedRef = useRef(false)
  const telegramCommunityDirtyRef = useRef(false)
  const timeframeSwitchIdRef = useRef(0)
  const chartViewCacheRef = useRef(new Map(initialView.snapshot
    ? [[`${initialView.asset}:${initialView.timeframe}`, initialView.snapshot]]
    : []))
  const chartViewPrefetchRef = useRef(new Map())
  const chartBootstrapPendingRef = useRef(!initialView.snapshot)
  const viewSelectionRef = useRef({ asset, timeframe, tradingStyle })
  useMarketNotifications(marketAlerts)

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
  const autoScanning = autoAnalysisStatus?.status === 'SCANNING'
  const actionsDisabled = autoScanning || backendOffline
  const internalDataReady = chartReady && lockedMode.can_analyze !== false && !alignmentBlocksAnalysis && !backendOffline
  const activeAnalysis = analysis?.symbol === asset ? analysis : null
  const activeExplanation = analysisExplanation?.symbol === asset ? analysisExplanation : null
  const activeMarketOverview = safeArray(marketOverview?.assets).find(item => item?.symbol === asset)
  const activeProviderAlignment = liveChartState?.provider_alignment || activeAnalysis?.provider_alignment || activeExplanation?.provider_alignment || activeMarketOverview?.provider_alignment || null
  const activeLatestPrice = activeAnalysis?.current_price ?? (asset === 'XAUUSD' ? status?.latest_price || dataIntegrity?.latest_live_price : null)
  const activeLockedMode = asset === 'XAUUSD' ? lockedMode : {
    ...DEFAULT_LOCKED_MODE,
    locked_mode: activeAnalysis?.data_mode || 'NO_DATA_MODE',
    data_mode: activeAnalysis?.data_mode || 'NO_DATA_MODE',
    data_mode_label: activeAnalysis?.data_mode === 'REAL_MODE' ? 'REAL' : 'AUTO SYNC',
    backend_status: backendOffline ? 'BACKEND_OFFLINE' : 'ONLINE',
    analysis_state: activeAnalysis?.final_decision || `Ready for ${asset} Analysis`,
    can_analyze: !backendOffline,
  }
  const chartMessage = chartReady ? '' : NO_HISTORY_MESSAGE
  const providerStopped = status?.status === 'STOPPED'
  const fullAnalysisDisabled = dataReadiness?.chart_ready && !dataReadiness?.full_analysis_ready
  const routeError = apiErrorInfo?.code === 'ROUTE_NOT_FOUND'

  const warnings = useMemo(() => {
    const items = []
    if (backendOffline) return items
    if (routeError) items.push('A feature update is required. Please refresh and try again.')
    if (alignmentBlocksAnalysis) items.push(historyAlignment.warning_message || 'History candles are not aligned with current live price.')
    if (dataIntegrity?.gap_detected) items.push(dataIntegrity.gap_warning || GAP_MESSAGE)
    if (!chartReady) items.push(NO_HISTORY_MESSAGE)
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
      console.group('SH Market Analyzer Boot')
      console.error('Boot error', err)
      console.groupEnd()
    }
    if (info.code === 'BACKEND_OFFLINE' || info.code === 'TIMEOUT') {
      const offlineMode = {
        locked_mode: 'BACKEND_OFFLINE_MODE',
        data_mode: 'BACKEND_OFFLINE_MODE',
        data_mode_label: 'SERVICE UNAVAILABLE',
        backend_status: 'BACKEND_OFFLINE',
        provider_status: 'OFFLINE',
        provider_name: '-',
        candle_source: 'LAST_KNOWN_CHART',
        analysis_state: 'Service Unavailable',
        can_analyze: false,
        can_refresh: false,
        can_smart_setup: false,
        description: 'Live updates are temporarily paused. The last chart remains visible.',
      }
      setHealth({ status: 'OFFLINE', version: '-', backend_status: 'BACKEND_OFFLINE' })
      setBackendStatus({ backend_status: 'BACKEND_OFFLINE', data_mode_lock: offlineMode })
      setDataMode(offlineMode)
      setDataState({ data_state: 'BACKEND_OFFLINE_MODE', analysis_state: 'Service Unavailable', data_mode_lock: offlineMode })
      setStatus({ status: 'OFFLINE', provider_name: '-', latest_price: null })
      return
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
        console.warn(`SH Market Analyzer API fallback: ${label}`, info)
      }
      return fallback
    }
  }

  async function loadNewsCalendar(forceRefresh = false) {
    setNewsCalendarLoading(true)
    setNewsCalendarError('')
    try {
      const result = await getMarketNewsCalendar(asset, forceRefresh)
      setNewsCalendar(result)
      if (result?.status === 'UNAVAILABLE') {
        setNewsCalendarError(result?.feed?.error || 'Weekly economic calendar provider is temporarily unavailable.')
      }
    } catch (err) {
      setNewsCalendarError(err?.message || 'Weekly economic calendar is unavailable.')
    } finally {
      setNewsCalendarLoading(false)
    }
  }

  function applyChartViewSnapshot(result, nextAsset, nextTimeframe, includeAnalysis = false) {
    if (!result?.chart_data) return false
    const key = `${nextAsset}:${nextTimeframe}`
    const cachedChart = chartViewCacheRef.current.get(key)?.chart_data
    const incomingCount = chartSnapshotCandleCount(result.chart_data)
    const cachedCount = chartSnapshotCandleCount(cachedChart)
    if (incomingCount < 30 && cachedCount >= 30) {
      chartBootstrapPendingRef.current = false
      return false
    }
    liveCandleSignatureRef.current = chartSnapshotSignature(result.chart_data)
    setChartData(result.chart_data)
    setDataIntegrity(result.chart_data.data_integrity || null)
    setOverlays(result.overlays || { overlays: {} })
    setOverlayStatus(result.overlays?.overlay_status || null)
    const nextPanels = result.panels || { indicator_panels: {} }
    setPanels(nextPanels)
    if (result.diamond_history) setDiamondHistory(result.diamond_history)
    if (incomingCount >= 35 && isIndicatorSnapshotReady(nextPanels)) {
      setMessage(current => isCandleSyncNotice(current) ? '' : current)
    }
    setLiveChartState(state => ({
      ...safeObject(state),
      ok: true,
      status: result.status || state?.status || 'CACHE_READY',
      source: result.history_provenance?.source || state?.source,
      provider_alignment: result.provider_alignment || state?.provider_alignment || null,
      history_provenance: result.history_provenance || state?.history_provenance || null,
    }))
    if (includeAnalysis) {
      setSessionFramework(result.session_framework || null)
      setKeyZones(result.key_zones || result.analysis?.key_zones || null)
      setNewsIntelligence(result.news_intelligence || result.analysis?.news_intelligence || null)
      if (result.analysis?.symbol) {
        liveAnalysisSignatureRef.current = analysisSnapshotSignature(result.analysis, result.auto_analysis)
        setAnalysis(result.analysis)
        setAnalysisExplanation(result.analysis.analysis_explanation || null)
        if (result.analysis.strategy_governance) setStrategyGovernance(result.analysis.strategy_governance)
      }
    }
    chartViewCacheRef.current.set(key, {
      chart_data: result.chart_data,
      overlays: result.overlays,
      panels: result.panels,
      diamond_history: result.diamond_history,
      provider_alignment: result.provider_alignment,
      history_provenance: result.history_provenance,
      status: result.status,
    })
    chartBootstrapPendingRef.current = false
    try {
      writeChartSnapshot(localStorage, result, nextAsset, nextTimeframe)
    } catch (_) {
      // An in-memory snapshot still keeps this session responsive.
    }
    return true
  }

  function loadCachedChartSnapshot(nextAsset, nextTimeframe, forceNetwork = false) {
    const key = `${nextAsset}:${nextTimeframe}`
    const cached = chartViewCacheRef.current.get(key)
    if (cached && !forceNetwork) return Promise.resolve(cached)
    const pending = chartViewPrefetchRef.current.get(key)
    if (pending) return pending
    const request = getMarketChartSnapshot(nextAsset, nextTimeframe, 500)
      .then(result => {
        chartViewCacheRef.current.set(key, result)
        return result
      })
      .finally(() => chartViewPrefetchRef.current.delete(key))
    chartViewPrefetchRef.current.set(key, request)
    return request
  }

  async function refresh(nextTimeframe = timeframe, includeStale = showStaleHistory, nextAsset = asset, nextTradingStyle = tradingStyle) {
    if (refreshInFlightRef.current) return
    refreshInFlightRef.current = true
    const refreshSelection = { asset: nextAsset, timeframe: nextTimeframe, tradingStyle: nextTradingStyle }
    const selectionIsCurrent = () => {
      const current = viewSelectionRef.current
      return current.asset === refreshSelection.asset
        && current.timeframe === refreshSelection.timeframe
        && current.tradingStyle === refreshSelection.tradingStyle
    }
    setRefreshing(true)
    setError('')
    setApiErrorInfo(null)
    try {
      const healthResult = await getHealth()
      setHealth(healthResult)
      setBoot(state => ({ ...state, phase: 'READY', slow: false }))
      if (import.meta.env.DEV) {
        console.group('SH Market Analyzer Boot')
        console.log('Backend health', healthResult)
        console.groupEnd()
      }
      if (healthResult.status === 'OFFLINE') {
        throw Object.assign(new Error('Market service is temporarily unavailable.'), {
          code: 'BACKEND_OFFLINE',
          apiBaseUrl: API_BASE_URL,
        })
      }
      const signalViewPromise = safeCall('market-signal-view', () => getMarketSignalView(nextAsset, nextTimeframe, 500, nextTradingStyle, false), {
        chart_data: { status: 'NO_HISTORY', candles: [], segments: {}, data_integrity: { status: 'NO_HISTORY' } },
        overlays: { status: 'NO_CANDLES', overlays: {}, chart_overlays: {}, overlay_status: {} },
        panels: { status: 'WAITING_FOR_HISTORY', indicator_panels: {}, badge: null },
      })
      const mtfSnapshotPromise = signalViewPromise.then(() => safeCall('market-mtf-snapshot', () => getMarketMtfSnapshot(nextAsset), {
        status: 'PARTIAL', symbol: nextAsset, bias: 'MIXED', confluence_score: 0, timeframes: [],
      }))
      const diamondHistoryPromise = signalViewPromise.then(() => safeCall('diamond-history', () => getDiamondHistory(nextAsset, 200), {
        status: 'OK', symbol: nextAsset, entries: [], stats: { total: 0, context: 0, qualified: 0, confirmed: 0, won: 0, lost: 0 },
      }))
      const diamondValidationPromise = signalViewPromise.then(() => safeCall('diamond-validation', () => getDiamondValidation(nextAsset, nextTimeframe), {
        status: 'NOT_RUN', symbol: nextAsset, timeframe: nextTimeframe,
      }))
      const setupTrackerPromise = safeCall('setup-tracker', () => getTrackedSetups(nextAsset, 20), {
        status: 'OK', symbol: nextAsset, setups: [], stats: { total: 0, active: 0, won: 0, lost: 0, net_r: 0 },
      })
      const strategyGovernancePromise = signalViewPromise.then(() => safeCall('strategy-governance', () => getStrategyGovernance(nextAsset, nextTimeframe), {
        status: 'WAITING_FIRST_OBSERVATION', symbol: nextAsset, timeframe: nextTimeframe,
      }))
      const marketAlertsPromise = signalViewPromise.then(() => safeCall('market-alerts', () => getMarketAlerts(nextAsset, 20), {
        status: 'OK', symbol: nextAsset, alerts: [], stats: { total: 0, unread: 0, action_count: 0 },
      }))
      const telegramSettingsPromise = isAdmin
        ? safeCall('telegram-alert-settings', getTelegramAlertSettings, { telegram: { status: 'DISABLED', enabled: false } })
        : Promise.resolve({ telegram: null })
      const telegramCommunityPromise = safeCall('telegram-community', getTelegramCommunity, {
        community: {
          configured: /^https:\/\/(t\.me|telegram\.me)\//i.test(DEFAULT_TELEGRAM_COMMUNITY_URL),
          url: DEFAULT_TELEGRAM_COMMUNITY_URL || null,
        },
      })
      signalViewPromise.then(result => {
        if (!selectionIsCurrent()) return
        applyChartViewSnapshot(result, nextAsset, nextTimeframe, true)
      })
      const [backendStatusResult, provider, engine, readiness, modeResult, stateResult, integrityResult, signalViewResult, explanationResult, overviewResult, mtfResult, diamondHistoryResult, diamondValidationResult, setupTrackerResult, governanceResult, alertsResult, providerCredentials, telegramResult, telegramCommunityResult] = await Promise.all([
        safeCall('backend-status', getBackendStatus, { backend_status: 'ONLINE', data_mode_lock: DEFAULT_LOCKED_MODE }),
        safeCall('provider-status', getProviderStatus, { status: 'NO_DATA', provider_name: '-', latest_price: null, settings: {} }),
        safeCall('engine-status', getEngineStatus, { engine_mode: 'balanced', engine_core_version: 'V4' }),
        safeCall('data-readiness', getDataReadiness, { ...DEFAULT_LOCKED_MODE, candle_counts: {}, data_mode_lock: DEFAULT_LOCKED_MODE }),
        safeCall('data-mode', getDataMode, DEFAULT_LOCKED_MODE),
        safeCall('data-state', getDataState, { data_state: 'NO_DATA_MODE', data_mode_lock: DEFAULT_LOCKED_MODE }),
        safeCall('data-integrity', () => getDataIntegrity(nextTimeframe, 300), { status: 'NO_HISTORY', warnings: [] }),
        signalViewPromise,
        safeCall('analysis-explanation', () => getAnalysisExplanation(nextAsset), { analysis_explanation: null }),
        safeCall('market-overview', getMarketOverview, { status: 'NO_DATA', assets: [] }),
        mtfSnapshotPromise,
        diamondHistoryPromise,
        diamondValidationPromise,
        setupTrackerPromise,
        strategyGovernancePromise,
        marketAlertsPromise,
        safeCall('provider-credentials', getProviderCredentials, { settings: {}, oanda_restore: null }),
        telegramSettingsPromise,
        telegramCommunityPromise,
      ])
      if (!selectionIsCurrent()) return
      const credentialSettings = Object.keys(safeObject(providerCredentials?.settings)).length
        ? providerCredentials.settings
        : provider?.settings
      const hydratedProvider = {
        ...safeObject(provider),
        settings: safeObject(credentialSettings),
        oanda_restore: providerCredentials?.oanda_restore || provider?.oanda_restore || null,
        provider_restore: providerCredentials?.provider_restore || provider?.provider_restore || null,
        data_readiness: provider?.data_readiness,
      }
      setBackendStatus(backendStatusResult)
      setAnalysisState({ analysis_state: readiness?.analysis_state || stateResult?.analysis_state || 'Waiting for Data' })
      setStatus(hydratedProvider)
      const savedOandaEnvironment = hydratedProvider?.settings?.oanda_environment
      if (!oandaSettingsHydratedRef.current) {
        if (['practice', 'live'].includes(savedOandaEnvironment)) setOandaEnvironment(savedOandaEnvironment)
        oandaSettingsHydratedRef.current = true
      }
      setEngineStatus(engine)
      setDataReadiness(readiness)
      setDataMode(modeResult?.data_mode_lock || modeResult || DEFAULT_LOCKED_MODE)
      setDataState(stateResult)
      const chartResult = signalViewResult?.chart_data || { candles: [], segments: {} }
      const overlayResult = signalViewResult?.overlays || { overlays: {} }
      const panelResult = signalViewResult?.panels || { indicator_panels: {} }
      const nextIntegrity = chartResult?.data_integrity || integrityResult
      if (nextIntegrity?.gap_detected) {
        const diagnosisResult = await safeCall('gap-diagnosis', () => getGapDiagnosis(nextTimeframe), { status: 'GAP_WARNING' })
        setGapDiagnosis(diagnosisResult)
      } else {
        setGapDiagnosis(null)
      }
      const incomingChartCount = chartSnapshotCandleCount(chartResult)
      setChartData(current => (
        incomingChartCount >= 30 || chartSnapshotCandleCount(current) < 30
          ? chartResult
          : current
      ))
      if (incomingChartCount >= 30) {
        setDataIntegrity(chartResult?.data_integrity || integrityResult)
        setOverlays(overlayResult || { overlays: {} })
        setOverlayStatus(chartResult?.overlay_status || overlayResult?.overlay_status || null)
        setPanels(panelResult)
      } else {
        setDataIntegrity(current => current || chartResult?.data_integrity || integrityResult)
        setOverlays(current => current || overlayResult || { overlays: {} })
        setOverlayStatus(current => current || chartResult?.overlay_status || overlayResult?.overlay_status || null)
        setPanels(current => current || panelResult)
      }
      setAnalysisExplanation(explanationResult)
      setMarketOverview(overviewResult)
      setMtfSnapshot(mtfResult)
      setDiamondHistory(diamondHistoryResult)
      setDiamondValidation(diamondValidationResult)
      setStrategyGovernance(governanceResult)
      setMarketAlerts(alertsResult)
      if (telegramResult?.telegram) {
        setTelegramSettings(telegramResult.telegram)
        setTelegramEnabled(Boolean(telegramResult.telegram.enabled))
      }
      if (telegramCommunityResult?.community) {
        const nextCommunity = telegramCommunityResult.community
        setTelegramCommunity(nextCommunity)
        if (!telegramCommunityDirtyRef.current) {
          setTelegramCommunityInput(nextCommunity.url || '')
        }
      }
      setSetupTracker(setupTrackerResult)
      setSessionFramework(signalViewResult?.session_framework || null)
      setKeyZones(signalViewResult?.key_zones || signalViewResult?.analysis?.key_zones || null)
      setNewsIntelligence(signalViewResult?.news_intelligence || signalViewResult?.analysis?.news_intelligence || null)
      if (signalViewResult?.analysis?.symbol) setAnalysis(signalViewResult.analysis)
      else if (explanationResult?.trade_plan) setAnalysis(explanationResult)
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

  async function validateDiamondEvidence() {
    if (backendOffline || validationLoading) return
    setValidationLoading(true)
    setError('')
    try {
      const result = await runDiamondValidation(asset, timeframe, {
        lookbackBars: 1000,
        refreshMarket: true,
        force: true,
      })
      setDiamondValidation(result)
      const replay = safeObject(result?.replay_summary)
      setMessage(
        `${asset} ${timeframeLabel(timeframe)} history analyzed: ${replay.strategy_confirmed_setups ?? 0} confirmed setups, ${replay.respected ?? 0} respected, ${replay.failed ?? 0} failed.`,
      )
    } catch (err) {
      setError(err?.message || 'Diamond validation failed.')
    } finally {
      setValidationLoading(false)
    }
  }

  async function handleAcknowledgeAlert(alertId) {
    if (!alertId || backendOffline) return
    try {
      const result = await acknowledgeMarketAlert(alertId)
      const acknowledged = result?.alert
      if (!acknowledged) return
      setMarketAlerts(current => ({
        ...safeObject(current),
        alerts: safeArray(current?.alerts).map(alert => alert.id === acknowledged.id ? acknowledged : alert),
        stats: {
          ...safeObject(current?.stats),
          unread: Math.max(0, (Number(current?.stats?.unread) || 0) - 1),
        },
      }))
    } catch (err) {
      setError(err?.message || 'Could not acknowledge the market alert.')
    }
  }

  function exportAnalysisReport() {
    if (!activeAnalysis) return
    const generatedAt = new Date().toISOString()
    const report = {
      exported_at: generatedAt,
      application: APP_TITLE,
      asset,
      timeframe,
      analysis: activeAnalysis,
    }
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${asset.toLowerCase()}-analysis-${generatedAt.replaceAll(':', '-')}.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    setMessage(`${asset} analysis report exported.`)
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

  async function saveOandaFeed() {
    setOandaVerification({ status: 'VERIFYING', ok: false })
    const payload = {
      oanda_api_token: oandaToken || undefined,
      oanda_environment: oandaEnvironment,
    }
    try {
      const verification = await verifyOandaFeed(payload)
      setOandaVerification(verification)
      if (asset === 'XAUUSD') setTvSymbol('OANDA:XAUUSD')
      setMessage(verification.message || 'OANDA feed verified, saved, and synchronized.')
      setOandaToken('')
      await refresh(timeframe)
    } catch (err) {
      const verification = err?.payload || {
        ok: false,
        status: 'VERIFICATION_FAILED',
        message: err?.message || 'OANDA verification failed.',
      }
      setOandaVerification(verification)
      setMessage(verification.message)
    }
  }

  async function saveTelegramAlerts() {
    setTelegramVerification({ status: 'VERIFYING', ok: false })
    const payload = {
      bot_token: telegramBotToken.trim() || undefined,
      chat_id: telegramChatId.trim() || undefined,
      enabled: telegramEnabled,
    }
    try {
      const result = telegramEnabled
        ? await testTelegramAlert(payload)
        : await saveTelegramAlertSettings(payload)
      const nextSettings = result.telegram || telegramSettings
      setTelegramSettings(nextSettings)
      setTelegramEnabled(Boolean(nextSettings?.enabled))
      setTelegramVerification({
        ok: true,
        status: result.status || (telegramEnabled ? 'VERIFIED' : 'SAVED'),
        message: result.message || (telegramEnabled ? 'Telegram alerts connected.' : 'Telegram alerts paused.'),
      })
      setTelegramBotToken('')
      setTelegramChatId('')
      setMessage(result.message || 'Telegram alert settings saved.')
    } catch (err) {
      const failure = err?.payload || {
        ok: false,
        status: 'CONNECTION_FAILED',
        message: err?.message || 'Telegram connection failed.',
      }
      setTelegramVerification(failure)
      setMessage(failure.message)
    }
  }

  async function saveTelegramCommunityLink() {
    setTelegramCommunitySave({ status: 'SAVING', ok: false })
    try {
      const result = await saveTelegramCommunity(telegramCommunityInput.trim())
      const nextCommunity = result.community || { configured: false, url: null }
      setTelegramCommunity(nextCommunity)
      setTelegramCommunityInput(nextCommunity.url || '')
      telegramCommunityDirtyRef.current = false
      setTelegramCommunitySave({
        ok: true,
        status: nextCommunity.configured ? 'SAVED' : 'REMOVED',
        message: result.message || (nextCommunity.configured ? 'Community link saved.' : 'Community link removed.'),
      })
      setMessage(result.message || 'Telegram Community link updated.')
    } catch (err) {
      const failure = err?.payload || {}
      setTelegramCommunitySave({
        ok: false,
        status: failure.code || 'NOT SAVED',
        message: failure.message || err?.message || 'Could not save the community link.',
      })
    }
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
      data_mode_label: 'SERVICE UNAVAILABLE',
      backend_status: 'BACKEND_OFFLINE',
      provider_status: 'OFFLINE',
      analysis_state: 'Service Unavailable',
      can_analyze: false,
      can_refresh: false,
      can_smart_setup: false,
      description: 'Live updates are temporarily paused.',
    }
    setBoot(state => ({ ...state, phase: 'BACKEND_OFFLINE', continueOffline: true }))
    setDataMode(offlineMode)
    setDataState({ data_state: 'BACKEND_OFFLINE_MODE', analysis_state: 'Service Unavailable', data_mode_lock: offlineMode })
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

  function handleResetScale() {
    setResetSignal(value => value + 1)
  }

  function handleChartMode(nextMode) {
    const mode = Object.keys(CHART_MODES).includes(nextMode) ? nextMode : 'tradingview'
    setChartMode(mode)
    setMenuOpen(false)
    setMobileTab('live')
  }

  function handleMobileFocus(target) {
    setMobileFocus(target)
    if (target === 'chart' || target === 'history') {
      handleChartMode('signal')
      setMobileFocusRequest({ target, id: Date.now() })
      return
    }
    if (target === 'news') {
      setNewsCalendarOpen(true)
      return
    }
    if (target === 'alerts') {
      setAlertCenterOpen(true)
      return
    }
    if (target === 'account') setAccountPanelOpen(true)
  }

  async function handleAsset(nextAsset) {
    const normalized = MARKET_ASSETS[nextAsset] ? nextAsset : 'XAUUSD'
    viewSelectionRef.current = { asset: normalized, timeframe, tradingStyle }
    timeframeSwitchIdRef.current += 1
    setTimeframeTransition({ active: false, target: null, phase: 'idle' })
    setAsset(normalized)
    setTvSymbol(MARKET_ASSETS[normalized].tradingViewSymbol)
    setAnalysis(null)
    setAnalysisExplanation(null)
    setStrategyGovernance(null)
    setMarketAlerts(null)
    setKeyZones(null)
    setNewsIntelligence(null)
    setAnalysisDrawerOpen(false)
    setMobileTab('live')
    setMessage(`${normalized} selected.`)
    chartBootstrapPendingRef.current = true
    loadCachedChartSnapshot(normalized, timeframe, true)
      .then(result => {
        const current = viewSelectionRef.current
        if (current.asset === normalized && current.timeframe === timeframe) {
          applyChartViewSnapshot(result, normalized, timeframe, false)
        }
      })
      .catch(() => {
        const current = viewSelectionRef.current
        if (current.asset === normalized && current.timeframe === timeframe) {
          chartBootstrapPendingRef.current = false
        }
      })
    await refresh(timeframe, showStaleHistory, normalized, tradingStyle)
  }

  async function handleTimeframe(nextTimeframe) {
    const normalized = TOOLBAR_TIMEFRAMES.includes(nextTimeframe) ? nextTimeframe : timeframe
    const nextStyle = ['5M', '15M'].includes(normalized)
      ? 'SCALPING'
      : ['1H', '4H'].includes(normalized)
        ? 'SWING'
        : tradingStyle
    const switchId = timeframeSwitchIdRef.current + 1
    timeframeSwitchIdRef.current = switchId
    viewSelectionRef.current = { asset, timeframe: normalized, tradingStyle: nextStyle }
    setTimeframe(normalized)
    setTradingStyle(nextStyle)
    setTimeframeTransition({ active: true, target: normalized, phase: 'snapshot' })
    setAnalysis(null)
    setAnalysisExplanation(null)
    setStrategyGovernance(null)
    setMarketAlerts(null)
    setDiamondValidation(null)
    setSessionFramework(null)
    setKeyZones(null)
    setNewsIntelligence(null)
    setMessage('')
    chartBootstrapPendingRef.current = true

    const isCurrentSwitch = () => timeframeSwitchIdRef.current === switchId
    const cached = chartViewCacheRef.current.get(`${asset}:${normalized}`)
    if (cached) applyChartViewSnapshot(cached, asset, normalized, false)

    try {
      const snapshot = await loadCachedChartSnapshot(asset, normalized)
      if (!isCurrentSwitch()) return
      applyChartViewSnapshot(snapshot, asset, normalized, false)
      setTimeframeTransition({ active: false, target: normalized, phase: 'ready' })

      getMarketSignalView(asset, normalized, 500, nextStyle, false).then(result => {
        if (!isCurrentSwitch()) return
        applyChartViewSnapshot(result, asset, normalized, true)
        getMarketMtfSnapshot(asset).then(snapshotResult => {
          if (isCurrentSwitch()) setMtfSnapshot(snapshotResult)
        }).catch(() => {})
      }).catch(err => {
        if (!isCurrentSwitch()) return
        setLiveChartState(state => ({
          ...safeObject(state),
          status: 'CACHE_READY',
          message: err?.message || 'Background analysis will retry on the next live candle.',
        }))
      })
      getDiamondValidation(asset, normalized).then(result => {
        if (isCurrentSwitch()) setDiamondValidation(result)
      }).catch(() => {
        if (isCurrentSwitch()) setDiamondValidation({ status: 'NOT_RUN', symbol: asset, timeframe: normalized })
      })
    } catch (err) {
      if (!isCurrentSwitch()) return
      chartBootstrapPendingRef.current = false
      const fallback = cached || chartViewCacheRef.current.get(`${asset}:${normalized}`)
      const fallbackReady = chartSnapshotCandleCount(fallback?.chart_data) >= 35
        && isIndicatorSnapshotReady(fallback?.panels)
      setLiveChartState(state => ({
        ...safeObject(state),
        status: fallbackReady ? 'CACHE_READY' : 'SYNC_PAUSED',
        message: fallbackReady
          ? 'Indicators are ready from matched history; live synchronization will retry automatically.'
          : err?.message || 'Timeframe synchronization paused.',
      }))
      setMessage(fallbackReady ? '' : `${timeframeLabel(normalized)} candles are still synchronizing.`)
    } finally {
      if (isCurrentSwitch()) setTimeframeTransition({ active: false, target: normalized, phase: 'ready' })
    }
  }

  async function handleTradingStyle(nextStyle) {
    const normalized = TRADING_STYLES[nextStyle] ? nextStyle : 'SCALPING'
    const nextTimeframe = TRADING_STYLES[normalized].executionTimeframe
    viewSelectionRef.current = { asset, timeframe: nextTimeframe, tradingStyle: normalized }
    setTradingStyle(normalized)
    setTimeframe(nextTimeframe)
    setMessage(`${TRADING_STYLES[normalized].label} profile selected: ${TRADING_STYLES[normalized].timeframes}.`)
    await handleTimeframe(nextTimeframe)
  }

  function handleTradingViewSymbol(nextSymbol) {
    const matchedAsset = Object.entries(MARKET_ASSETS).find(([, config]) => config.tradingViewSymbol === nextSymbol)?.[0]
    if (matchedAsset) {
      setAsset(matchedAsset)
      setTvSymbol(nextSymbol)
    }
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
    const visualSymbol = activeProviderAlignment?.visual_symbol
    if (asset !== 'XAUUSD' || !TRADINGVIEW_SYMBOLS.includes(visualSymbol)) return
    setTvSymbol(visualSymbol)
  }, [asset, activeProviderAlignment?.visual_symbol])

  useEffect(() => {
    clearBrokenLocalStorage()
    if (import.meta.env.DEV) {
      console.group('SH Market Analyzer Boot')
      console.log('App mounted')
      console.log('API base URL', API_BASE_URL)
      console.groupEnd()
    }
    const slowTimer = setTimeout(() => {
      setBoot(state => state.phase === 'STARTING' ? { ...state, slow: true } : state)
    }, 5000)
    let cancelled = false
    loadCachedChartSnapshot(asset, timeframe, true)
      .then(result => {
        if (!cancelled) applyChartViewSnapshot(result, asset, timeframe, false)
      })
      .catch(() => {
        chartBootstrapPendingRef.current = false
      })
    refresh(timeframe)
    return () => {
      cancelled = true
      clearTimeout(slowTimer)
    }
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
      localStorage.setItem('sh_trading_style', tradingStyle)
    } catch (_) {
      // Ignore blocked storage; runtime state is enough.
    }
  }, [tradingStyle])

  useEffect(() => {
    try {
      localStorage.setItem('sh_gold_chart_mode', chartMode)
      localStorage.setItem('sh_gold_chart_mode_v2', chartMode)
      localStorage.setItem('sh_gold_tv_symbol', tvSymbol)
      localStorage.setItem('sh_market_asset', asset)
    } catch (_) {
      // Ignore blocked storage; runtime state is enough.
    }
  }, [asset, chartMode, tvSymbol])

  useEffect(() => {
    if (!newsCalendarOpen) return
    loadNewsCalendar(false)
  }, [newsCalendarOpen, asset])

  useEffect(() => {
    if (!newsCalendarOpen || !safeArray(newsCalendar?.events).some(event => event.actual_status === 'UPDATING')) return undefined
    const timer = window.setInterval(() => loadNewsCalendar(true), 90_000)
    return () => window.clearInterval(timer)
  }, [newsCalendarOpen, newsCalendar?.generated_at])

  useEffect(() => {
    if (backendOffline || boot.phase !== 'READY' || chartMode !== 'signal') return undefined
    let cancelled = false
    const timer = window.setTimeout(async () => {
      const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection
      if (document.hidden || connection?.saveData) return
      const pairedTimeframes = { '1M': '5M', '5M': '15M', '15M': '5M', '1H': '4H', '4H': '1H', '1D': '4H' }
      const candidates = isMobileLayout
        ? [pairedTimeframes[timeframe]].filter(Boolean)
        : ['5M', '15M', '1H', '4H', '1D'].filter(item => item !== timeframe)
      for (const candidate of candidates) {
        if (cancelled) break
        try {
          await loadCachedChartSnapshot(asset, candidate)
        } catch (_) {
          // Prefetch is opportunistic; the active switch still has its own retry path.
        }
      }
    }, isMobileLayout ? 2800 : 700)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [asset, backendOffline, boot.phase, chartMode, timeframe, isMobileLayout])

  useEffect(() => {
    const query = window.matchMedia('(max-width: 760px)')
    const sync = () => setIsMobileLayout(query.matches)
    sync()
    query.addEventListener?.('change', sync)
    return () => query.removeEventListener?.('change', sync)
  }, [])

  useEffect(() => {
    if (backendOffline) return undefined
    let cancelled = false
    let timer = null

    const basePollDelay = () => {
      const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection
      if (connection?.saveData) return 15000
      if (asset === 'BTCUSD') return isMobileLayout ? 6000 : 4000
      return isMobileLayout ? 5000 : 3000
    }

    const schedule = delay => {
      if (!cancelled) timer = window.setTimeout(pollLiveCandle, delay)
    }
    const pollLiveCandle = async () => {
      const pollStartedAt = performance.now()
      if (document.hidden) {
        schedule(30000)
        return
      }
      if (chartLivePollRef.current) {
        schedule(800)
        return
      }
      if (chartBootstrapPendingRef.current) {
        schedule(400)
        return
      }
      chartLivePollRef.current = true
      let nextDelay = basePollDelay()
      try {
        const result = await getMarketCandleTick(asset, timeframe, tradingStyle)
        if (!cancelled && result?.chart_delta) {
          const nextChartSignature = chartSnapshotSignature(result.chart_delta)
          const chartChanged = nextChartSignature !== liveCandleSignatureRef.current
          const nextAnalysisSignature = result.analysis?.symbol
            ? analysisSnapshotSignature(result.analysis, result.auto_analysis)
            : ''
          const analysisChanged = Boolean(nextAnalysisSignature)
            && nextAnalysisSignature !== liveAnalysisSignatureRef.current

          if (chartChanged) liveCandleSignatureRef.current = nextChartSignature
          if (analysisChanged) liveAnalysisSignatureRef.current = nextAnalysisSignature

          startTransition(() => {
            if (chartChanged) {
              setChartData(current => mergeChartDelta(current, result.chart_delta))
              if (result.chart_delta.data_integrity) {
                setDataIntegrity(current => ({
                  ...safeObject(current),
                  ...safeObject(result.chart_delta.data_integrity),
                }))
              }
            }

            if (analysisChanged) {
              if (result.panels) setPanels(result.panels)
              if (result.session_framework) setSessionFramework(result.session_framework)
              if (result.key_zones) setKeyZones(result.key_zones)
              if (result.news_intelligence) setNewsIntelligence(result.news_intelligence)
              if (result.setup_tracker) setSetupTracker(result.setup_tracker)
              if (result.diamond_history) setDiamondHistory(result.diamond_history)

              const nextAnalysis = result.analysis
              setAnalysis(nextAnalysis)
              setAnalysisExplanation(nextAnalysis.analysis_explanation || null)
              if (nextAnalysis.strategy_governance) setStrategyGovernance(nextAnalysis.strategy_governance)
              if (nextAnalysis.closed_candle_alert) {
                setMarketAlerts(current => {
                  const existing = safeArray(current?.alerts).filter(alert => alert.id !== nextAnalysis.closed_candle_alert.id)
                  return {
                    ...safeObject(current),
                    alerts: [nextAnalysis.closed_candle_alert, ...existing].slice(0, 20),
                    stats: {
                      ...safeObject(current?.stats),
                      total: Math.max(Number(current?.stats?.total) || 0, existing.length + 1),
                      unread: [nextAnalysis.closed_candle_alert, ...existing].filter(alert => !alert.acknowledged).length,
                    },
                  }
                })
              }
              if (nextAnalysis.key_zones) setKeyZones(nextAnalysis.key_zones)
              if (nextAnalysis.news_intelligence) setNewsIntelligence(nextAnalysis.news_intelligence)
              if (result.auto_analysis?.ran && nextAnalysis.diamond_auto_entry?.status === 'AUTO_ARMED') {
                setMessage(`${asset} confirmed Diamond entry tracked automatically from the latest completed candle.`)
              }
            }

            if (result.auto_analysis) {
              setAutoAnalysisStatus(current => (
                autoAnalysisSignature(current) === autoAnalysisSignature(result.auto_analysis)
                  ? current
                  : result.auto_analysis
              ))
            }

            const nextLiveState = {
              ...safeObject(result.live_sync),
              provider_alignment: result.provider_alignment || null,
              history_provenance: result.history_provenance || null,
            }
            setLiveChartState(current => (
              liveSyncSignature(current) === liveSyncSignature(nextLiveState)
                ? current
                : nextLiveState
            ))
          })

          const serverDelay = Number(result.live_sync?.poll_after_ms) || 0
          nextDelay = Math.max(basePollDelay(), serverDelay)
        }
      } catch (err) {
        if (!cancelled) {
          setAutoAnalysisStatus({ status: 'SYNC_PAUSED', error: err?.message })
          setLiveChartState(state => ({
            ...safeObject(state),
            ok: false,
            status: 'SYNC_PAUSED',
            message: err?.message || 'Live candle sync paused.',
          }))
        }
      } finally {
        chartLivePollRef.current = false
        const elapsed = performance.now() - pollStartedAt
        schedule(Math.max(250, nextDelay - elapsed))
      }
    }

    const handleVisibilityChange = () => {
      if (!document.hidden && timer) {
        window.clearTimeout(timer)
        schedule(100)
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    pollLiveCandle()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [asset, backendOffline, timeframe, tradingStyle, isMobileLayout])

  useEffect(() => {
    let running = false
    const syncHealth = async () => {
      if (running || document.hidden) return
      running = true
      try {
        const healthResult = await getHealth()
        setHealth(current => (
          healthSnapshotSignature(current) === healthSnapshotSignature(healthResult)
            ? current
            : healthResult
        ))
        if (backendOffline) await refresh(timeframe, showStaleHistory)
      } catch (err) {
        await handleApiError(err)
      } finally {
        running = false
      }
    }
    const interval = window.setInterval(syncHealth, isMobileLayout ? 20000 : 10000)
    const handleVisibilityChange = () => {
      if (!document.hidden) syncHealth()
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [backendOffline, timeframe, showStaleHistory, isMobileLayout])

  if (boot.phase === 'STARTING' && !boot.continueOffline && !chartData) {
    return (
      <BootScreen
        boot={boot}
        health={health}
        apiError={apiErrorInfo}
        onRetry={() => refresh(timeframe)}
        onContinueOffline={continueOffline}
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
    onRefresh: () => refresh(),
    resetSignal,
    onResetScale: handleResetScale,
    onTimeframeChange: handleTimeframe,
    onOpenOverlayMenu: handleOpenOverlays,
    backendOffline,
    actionsDisabled,
  }
  const liveChartProps = {
    symbol: tvSymbol,
    timeframe,
    internalReady: asset === 'XAUUSD' ? internalDataReady : Boolean(activeAnalysis?.trade_plan),
  }

  return (
    <main className="app terminal-app modern-ui-2026">
      <TopToolbar
        asset={asset}
        timeframe={timeframe}
        tradingStyle={tradingStyle}
        chartMode={chartMode}
        latestPrice={activeLatestPrice}
        onAsset={handleAsset}
        onTimeframe={handleTimeframe}
        onTradingStyle={handleTradingStyle}
        onChartMode={handleChartMode}
        onNews={() => setNewsCalendarOpen(true)}
        onMenu={() => setMenuOpen(true)}
        newsRisk={(newsIntelligence || activeAnalysis?.news_intelligence)?.risk_level}
        communityUrl={telegramCommunity?.url || DEFAULT_TELEGRAM_COMMUNITY_URL}
      />

      <AppNotice
        error={error}
        message={message}
        warnings={activeAnalysis?.data_mode === 'REAL_MODE' ? [] : asset === 'XAUUSD' ? warnings : []}
        backendOffline={backendOffline}
        apiBaseUrl={API_BASE_URL}
      />
      {chartMode === 'tradingview' && (
        <CompactStatusStrip
          asset={asset}
          analysis={activeAnalysis}
          providerAlignment={activeProviderAlignment}
          lockedMode={lockedMode}
          readiness={dataReadiness}
          dataIntegrity={dataIntegrity}
          backendOffline={backendOffline}
        />
      )}

      {chartMode === 'signal' && (
        <WorkspaceErrorBoundary resetToken={`${asset}:${timeframe}:${chartData?.candles?.at(-1)?.time || chartData?.segments?.active?.at(-1)?.time || 'empty'}`}>
          <SignalChartView
            asset={asset}
            timeframe={timeframe}
            timeframeTransition={timeframeTransition}
            chartData={chartData}
            overlays={overlays}
            panels={panels}
            analysis={activeAnalysis}
            providerAlignment={activeProviderAlignment}
            liveSync={liveChartState}
            mtfSnapshot={mtfSnapshot}
            diamondHistory={diamondHistory}
            diamondValidation={diamondValidation}
            strategyGovernance={strategyGovernance || activeAnalysis?.strategy_governance}
            marketAlerts={marketAlerts}
            validationLoading={validationLoading}
            setupTracker={setupTracker}
            sessionFramework={sessionFramework || activeAnalysis?.session_framework}
            keyZones={keyZones || activeAnalysis?.key_zones}
            newsIntelligence={newsIntelligence || activeAnalysis?.news_intelligence}
            focusRequest={mobileFocusRequest}
            onRunValidation={validateDiamondEvidence}
            onAcknowledgeAlert={handleAcknowledgeAlert}
            onTimeframe={handleTimeframe}
            onTradingView={() => handleChartMode('tradingview')}
            onNews={() => setNewsCalendarOpen(true)}
          />
        </WorkspaceErrorBoundary>
      )}

      {chartMode === 'tradingview' && !isMobileLayout && (
        <section className="decision-workspace">
          <aside className="workspace-market-rail">
            <MarketScanner
              overview={marketOverview}
              asset={asset}
              onAsset={handleAsset}
              loading={refreshing}
            />
          </aside>
          <div className="workspace-chart">
            <TradingViewLiveChart {...liveChartProps} />
          </div>
          <aside className="workspace-decision">
            <LiveAnalysisPanel
              asset={asset}
              analysis={activeAnalysis}
              explanation={activeExplanation}
              lockedMode={activeLockedMode}
              latestPrice={activeLatestPrice}
              timeframe={timeframe}
              loading={autoScanning}
              backendOffline={backendOffline}
            />
            <SetupValidationPanel analysis={activeAnalysis} loading={autoScanning} />
          </aside>
        </section>
      )}

      {chartMode === 'tradingview' && isMobileLayout && (
        <section className="mobile-workspace">
          <MarketScanner
            overview={marketOverview}
            asset={asset}
            onAsset={handleAsset}
            loading={refreshing}
          />
          <div className="mobile-tab-switcher">
            {[
              ['live', 'Live Chart'],
              ['workflow', 'Analysis'],
              ...(asset === 'XAUUSD' ? [['data', 'Data Hub']] : []),
            ].map(([key, label]) => (
              <button key={key} className={mobileTab === key ? 'active' : ''} onClick={() => setMobileTab(key)}>
                {label}
              </button>
            ))}
          </div>
          {mobileTab === 'live' && <TradingViewLiveChart {...liveChartProps} />}
          {mobileTab === 'workflow' && (
            <section className="mobile-analysis-stack">
              <LiveAnalysisPanel
                asset={asset}
                analysis={activeAnalysis}
                explanation={activeExplanation}
                lockedMode={activeLockedMode}
                latestPrice={activeLatestPrice}
                timeframe={timeframe}
                loading={autoScanning}
                backendOffline={backendOffline}
              />
              <SetupValidationPanel analysis={activeAnalysis} loading={autoScanning} />
            </section>
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
              {isAdmin && <button className="mobile-data-hub-button" onClick={handleOpenDataHub} disabled={actionsDisabled}>Market Data Tools</button>}
            </>
          )}
        </section>
      )}

      <div className="bottom-status">
        <span className={`dot ${tone(status?.status)}`} />
        <strong>{status?.status || 'STARTING'}</strong>
        <span>{backendOffline ? 'Service Unavailable' : routeError ? 'Feature Update Required' : activeProviderAlignment?.matched === false ? 'Research Only - Unmatched Feed' : lockedMode.analysis_state || dataReadiness?.analysis_state || dataIntegrity?.status || 'Waiting for Data'}</span>
        <em className={`data-mode-mini ${tone(activeProviderAlignment?.matched === false ? 'RESEARCH_ONLY' : lockedMode.locked_mode)}`}>{activeProviderAlignment?.matched === false ? 'RESEARCH' : lockedMode.data_mode_label || dataReadiness?.data_mode_label || 'NO DATA'}</em>
      </div>

      <MobileFocusNav
        active={mobileFocus}
        unread={Number(marketAlerts?.stats?.unread ?? safeArray(marketAlerts?.alerts).filter(item => !item.acknowledged).length)}
        onSelect={handleMobileFocus}
      />

      <WeeklyNewsDrawer
        open={newsCalendarOpen}
        asset={asset}
        calendar={newsCalendar?.symbol === asset ? newsCalendar : null}
        loading={newsCalendarLoading}
        error={newsCalendarError}
        onRefresh={() => loadNewsCalendar(true)}
        onClose={() => setNewsCalendarOpen(false)}
      />

      <AlertCenterDrawer
        open={alertCenterOpen}
        alerts={marketAlerts}
        asset={asset}
        onAcknowledge={handleAcknowledgeAlert}
        onClose={() => setAlertCenterOpen(false)}
      />

      <AccountDrawer
        open={accountPanelOpen}
        onClose={() => setAccountPanelOpen(false)}
      />

      <MobileMenuDrawer
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        status={status}
        counts={counts}
        onStart={startBuilder}
        onStop={stopBuilder}
        onSeed={seedHistoryAndRefresh}
        onDownload={downloadHistoryAndRefresh}
        onRefresh={() => refresh()}
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
        chartMode={chartMode}
        onChartMode={handleChartMode}
        tvSymbol={tvSymbol}
        onTvSymbol={handleTradingViewSymbol}
        engineMode={engineStatus?.engine_mode || 'balanced'}
        onEngineMode={changeEngineMode}
        oandaToken={oandaToken}
        setOandaToken={setOandaToken}
        oandaEnvironment={oandaEnvironment}
        setOandaEnvironment={setOandaEnvironment}
        onSaveOanda={saveOandaFeed}
        oandaVerification={oandaVerification}
        telegramSettings={telegramSettings}
        telegramBotToken={telegramBotToken}
        setTelegramBotToken={setTelegramBotToken}
        telegramChatId={telegramChatId}
        setTelegramChatId={setTelegramChatId}
        telegramEnabled={telegramEnabled}
        setTelegramEnabled={setTelegramEnabled}
        telegramVerification={telegramVerification}
        onSaveTelegram={saveTelegramAlerts}
        telegramCommunity={telegramCommunity}
        telegramCommunityInput={telegramCommunityInput}
        setTelegramCommunityInput={value => {
          telegramCommunityDirtyRef.current = true
          setTelegramCommunityInput(value)
          setTelegramCommunitySave(null)
        }}
        telegramCommunitySave={telegramCommunitySave}
        onSaveTelegramCommunity={saveTelegramCommunityLink}
        providerAlignment={activeProviderAlignment}
        onUploadCsv={uploadCsv}
        onImportHistory={importRealHistory}
        onClearLocalStorage={clearLocalStorageAndReload}
        asset={asset}
      />

      {isAdmin && (
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
          onExport={exportCandlesAndRefresh}
          onReset={resetDatabaseAndRefresh}
          onWizard={runWizardAndRefresh}
          actionsDisabled={actionsDisabled}
        />
      )}

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
        onExport={exportAnalysisReport}
        analysis={activeAnalysis}
        lockedMode={lockedMode}
        dataIntegrity={dataIntegrity}
        explanation={activeExplanation}
      />
    </main>
  )
}
