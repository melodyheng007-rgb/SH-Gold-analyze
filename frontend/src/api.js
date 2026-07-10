import { apiRequest } from './services/apiClient.js'

export async function getHealth() {
  return await apiRequest('/api/health', { timeoutMs: 2500 })
}

export async function getRoutes() {
  return await apiRequest('/api/routes')
}

export async function getLivePrice() {
  return await apiRequest('/api/xauusd/live-price', { timeoutMs: 3500 })
}

export async function getCandles(timeframe = '15M', limit = 300) {
  return await apiRequest('/api/xauusd/candles', { query: { timeframe, limit } })
}

export async function getChartData(timeframe = '15M', limit = 500, includeStale = false) {
  return await apiRequest('/api/xauusd/chart-data', { query: { timeframe, limit, include_stale: includeStale }, timeoutMs: 7000 })
}

export async function getCandleHealth(timeframe = '15M', limit = 1000) {
  return await apiRequest('/api/xauusd/candle-health', { query: { timeframe, limit }, timeoutMs: 5000 })
}

export async function getHistoryAlignment(timeframe = '15M', limit = 1000) {
  return await apiRequest('/api/xauusd/history-alignment', { query: { timeframe, limit }, timeoutMs: 5000 })
}

export async function getDataIntegrity(timeframe = '15M', limit = 300) {
  return await apiRequest('/api/xauusd/data-integrity', { query: { timeframe, limit } })
}

export async function getOverlays(timeframe = '15M', limit = 300) {
  return await apiRequest('/api/xauusd/overlays', { query: { timeframe, limit } })
}

export async function getOverlayStatus(timeframe = '15M', limit = 300) {
  return await apiRequest('/api/xauusd/overlay-status', { query: { timeframe, limit } })
}

export async function getIndicatorPanels(timeframe = '15M', limit = 300) {
  return await apiRequest('/api/xauusd/indicator-panels', { query: { timeframe, limit } })
}

export async function getIndicatorPanelsV2(timeframe = '15M', limit = 300) {
  return await apiRequest('/api/xauusd/indicator-panels-v2', { query: { timeframe, limit } })
}

export async function getIndicatorPanelsV3(timeframe = '15M', limit = 300) {
  return await apiRequest('/api/xauusd/indicator-panels-v3', { query: { timeframe, limit } })
}

export async function getOverlaysV2(timeframe = '15M', limit = 300) {
  return await apiRequest('/api/xauusd/overlays-v2', { query: { timeframe, limit } })
}

export async function getChartIndicators(timeframe = '15M', limit = 300) {
  return await apiRequest('/api/xauusd/chart-indicators', { query: { timeframe, limit } })
}

export async function getDataReadiness() {
  return await apiRequest('/api/xauusd/data-readiness')
}

export async function getReadiness() {
  return await apiRequest('/api/xauusd/readiness')
}

export async function getDataMode() {
  return await apiRequest('/api/xauusd/data-mode')
}

export async function getDataHub() {
  return await apiRequest('/api/xauusd/data-hub')
}

export async function getBackendStatus() {
  return await apiRequest('/api/xauusd/backend-status')
}

export async function getAnalysisState() {
  return await apiRequest('/api/xauusd/analysis-state')
}

export async function getDataState() {
  return await apiRequest('/api/xauusd/data-state')
}

export async function getGapDiagnosis(timeframe = '15M') {
  return await apiRequest('/api/xauusd/gap-diagnosis', { query: { timeframe } })
}

export async function seedHistory() {
  return await apiRequest('/api/xauusd/seed-history', { method: 'POST' })
}

export async function downloadFreeHistory() {
  return await apiRequest('/api/xauusd/download-free-history', { method: 'POST' })
}

export async function reloadHistory() {
  return await apiRequest('/api/xauusd/reload-history', { method: 'POST' })
}

export async function rebuildCandleEngine() {
  return await apiRequest('/api/xauusd/rebuild-candle-engine', { method: 'POST' })
}

export async function validateCandles(timeframe = null) {
  return await apiRequest('/api/xauusd/validate-candles', {
    method: 'POST',
    query: timeframe ? { timeframe } : {},
  })
}

export async function generateTestHistory() {
  return await apiRequest('/api/xauusd/generate-test-history', { method: 'POST' })
}

export async function generateTestHistoryV2() {
  return await apiRequest('/api/xauusd/generate-test-history-v2', { method: 'POST' })
}

export async function generateLiveAnchoredTestHistory() {
  return await apiRequest('/api/xauusd/generate-live-anchored-test-history', { method: 'POST' })
}

export async function clearTestHistory() {
  return await apiRequest('/api/xauusd/clear-test-history', { method: 'POST' })
}

export async function oneClickWarmup() {
  return await apiRequest('/api/xauusd/one-click-warmup', { method: 'POST' })
}

export async function runRealModeWizard() {
  return await apiRequest('/api/xauusd/real-mode-wizard', { method: 'POST' })
}

export async function smartSetup() {
  return await apiRequest('/api/xauusd/smart-setup', { method: 'POST' })
}

export async function fixGap(mode) {
  return await apiRequest('/api/xauusd/fix-gap', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  })
}

export async function setDataMode(mode, showStaleHistory) {
  return await apiRequest('/api/xauusd/set-data-mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, show_stale_history: showStaleHistory }),
  })
}

export async function archiveStaleHistory() {
  return await apiRequest('/api/xauusd/archive-stale-history', { method: 'POST' })
}

export async function toggleTestMode(enabled) {
  return await apiRequest('/api/xauusd/toggle-test-mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
}

export async function getDebugData() {
  return await apiRequest('/api/xauusd/debug-data')
}

export async function getProviderStatus() {
  return await apiRequest('/api/xauusd/provider-status', { timeoutMs: 3500 })
}

export async function saveProviderSettings(settings) {
  return await apiRequest('/api/xauusd/provider-settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
}

export async function startLiveBuilder() {
  return await apiRequest('/api/xauusd/start-live-builder', { method: 'POST' })
}

export async function stopLiveBuilder() {
  return await apiRequest('/api/xauusd/stop-live-builder', { method: 'POST' })
}

export async function analyzeLiveXauusd() {
  return await apiRequest('/api/xauusd/analyze-live', { method: 'POST' })
}

export async function getEngineStatus() {
  return await apiRequest('/api/xauusd/engine-status')
}

export async function setEngineMode(mode) {
  return await apiRequest('/api/xauusd/set-engine-mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  })
}

export async function analyzeMode(mode = 'balanced') {
  return await apiRequest(`/api/xauusd/analyze-${mode}`, { method: 'POST' })
}

export async function analyzePro() {
  return await apiRequest('/api/xauusd/analyze-pro', { method: 'POST' })
}

export async function analyzeV4() {
  return await apiRequest('/api/xauusd/analyze-v4', { method: 'POST' })
}

export async function getProAnalysis(mode = 'balanced') {
  return await apiRequest('/api/xauusd/pro-analysis', { query: { mode } })
}

export async function getProAnalysisV4(mode = 'balanced') {
  return await apiRequest('/api/xauusd/pro-analysis-v4', { query: { mode } })
}

export async function getAnalysisExplanation(mode = 'balanced') {
  return await apiRequest('/api/xauusd/analysis-explanation', { query: { mode } })
}

export async function getAnalysisCache() {
  return await apiRequest('/api/xauusd/analysis-cache')
}

export async function getProAnalysisCache() {
  return await apiRequest('/api/xauusd/pro-analysis-cache')
}

export async function clearAnalysisCache() {
  return await apiRequest('/api/xauusd/clear-cache', { method: 'POST' })
}

export async function getEngineLogs() {
  return await apiRequest('/api/xauusd/engine-logs')
}

export async function clearEngineLogs() {
  return await apiRequest('/api/xauusd/clear-logs', { method: 'POST' })
}

export async function uploadCsvForBacktest(file) {
  const formData = new FormData()
  formData.append('file', file)
  return await apiRequest('/api/xauusd/upload-csv', {
    method: 'POST',
    body: formData,
  })
}

export async function backtestCsvXauusd() {
  return await apiRequest('/api/xauusd/backtest-csv', { method: 'POST' })
}

export async function rebuildCandles() {
  return await apiRequest('/api/xauusd/rebuild-candles', { method: 'POST' })
}

export async function clearInvalidCandles() {
  return await apiRequest('/api/xauusd/clear-invalid-candles', { method: 'POST' })
}

export async function importRecentHistory(file, timeframe = '15M') {
  const formData = new FormData()
  formData.append('file', file)
  return await apiRequest('/api/xauusd/import-recent-history', {
    method: 'POST',
    query: { timeframe },
    body: formData,
  })
}

export async function importRealRecentHistory(file, timeframe = '15M') {
  const formData = new FormData()
  formData.append('file', file)
  return await apiRequest('/api/xauusd/import-real-recent-history', {
    method: 'POST',
    query: { timeframe },
    body: formData,
  })
}

export async function importRealHistory(file, timeframe = '15M') {
  const formData = new FormData()
  formData.append('file', file)
  return await apiRequest('/api/xauusd/import-real-history', {
    method: 'POST',
    query: { timeframe },
    body: formData,
  })
}

export async function exportCurrentCandles(limit = 5000) {
  return await apiRequest('/api/xauusd/export-current-candles', { query: { limit } })
}

export async function resetDatabase(confirm = false) {
  return await apiRequest('/api/xauusd/reset-database', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm }),
  })
}
