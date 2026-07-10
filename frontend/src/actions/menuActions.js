const MENU_GROUPS = ['Chart', 'Data', 'Analysis', 'System']

function warnMissingHandler(id) {
  if (import.meta.env.DEV) {
    console.warn(`[MenuActionRegistry] Missing handler for "${id}". Using safe noop.`)
  }
}

function safeHandler(id, handler) {
  if (typeof handler === 'function') return handler
  return (...args) => {
    warnMissingHandler(id)
    return undefined
  }
}

function normalizeAction(action, handlers, state) {
  const enabled = typeof action.enabled === 'function' ? action.enabled(state) : action.enabled
  const visible = typeof action.visible === 'function' ? action.visible(state) : action.visible
  return {
    id: action.id,
    label: action.label,
    group: action.group,
    description: action.description,
    enabled: enabled !== false,
    visible: visible !== false,
    handler: safeHandler(action.id, handlers[action.id]),
  }
}

const DEFINITIONS = [
  {
    id: 'chart.tradingview',
    label: 'TradingView Live',
    group: 'Chart',
    description: 'Show the TradingView live reference chart.',
  },
  {
    id: 'chart.analysis',
    label: 'SH Analysis',
    group: 'Chart',
    description: 'Show the internal SH analysis candle chart.',
  },
  {
    id: 'chart.split',
    label: 'Split View',
    group: 'Chart',
    description: 'Show TradingView and SH analysis together.',
  },
  {
    id: 'chart.resetScale',
    label: 'Reset Scale',
    group: 'Chart',
    description: 'Reset chart zoom and price scale.',
  },
  {
    id: 'data.hub',
    label: 'Data Hub',
    group: 'Data',
    description: 'Open real data status, counts, and source tools.',
    enabled: state => !state.actionsDisabled,
  },
  {
    id: 'data.realModeWizard',
    label: 'Real Mode Wizard',
    group: 'Data',
    description: 'Run the real-mode setup workflow.',
    enabled: state => !state.actionsDisabled,
  },
  {
    id: 'data.importRealHistory',
    label: 'Import Real History',
    group: 'Data',
    description: 'Upload real XAUUSD candle history CSV.',
    enabled: state => !state.actionsDisabled,
  },
  {
    id: 'data.generateTestHistory',
    label: 'Generate Test History',
    group: 'Data',
    description: 'Generate clearly marked test candles for development.',
    enabled: state => !state.actionsDisabled,
  },
  {
    id: 'data.clearTestHistory',
    label: 'Clear Test History',
    group: 'Data',
    description: 'Remove generated test candles.',
    enabled: state => !state.actionsDisabled,
  },
  {
    id: 'data.liveOnlyMode',
    label: 'Live Only Mode',
    group: 'Data',
    description: 'Use live price only and disable full real analysis.',
    enabled: state => !state.actionsDisabled,
  },
  {
    id: 'analysis.analyze',
    label: 'Analyze',
    group: 'Analysis',
    description: 'Run the institutional analysis engine.',
    enabled: state => !state.analyzeDisabled,
  },
  {
    id: 'analysis.smartSetup',
    label: 'Smart Setup',
    group: 'Analysis',
    description: 'Run setup checks and prepare real data workflow.',
    enabled: state => !state.actionsDisabled,
  },
  {
    id: 'analysis.fixGap',
    label: 'Fix Gap',
    group: 'Analysis',
    description: 'Open data gap recovery options.',
    enabled: state => !state.actionsDisabled,
  },
  {
    id: 'analysis.clearCache',
    label: 'Clear Analysis Cache',
    group: 'Analysis',
    description: 'Clear cached analysis results.',
    enabled: state => !state.actionsDisabled,
  },
  {
    id: 'system.debug',
    label: 'Debug',
    group: 'System',
    description: 'Open debug data and route checks.',
  },
  {
    id: 'system.backendHealth',
    label: 'Backend Health',
    group: 'System',
    description: 'Refresh backend health and data status.',
  },
  {
    id: 'system.clearLocalStorage',
    label: 'Clear Local Storage',
    group: 'System',
    description: 'Clear local browser state and reload the app.',
  },
]

export function createMenuActions(handlers = {}, state = {}) {
  return DEFINITIONS.map(action => normalizeAction(action, handlers, state))
}

export function groupMenuActions(actions) {
  return MENU_GROUPS.map(group => ({
    group,
    actions: actions.filter(action => action.group === group && action.visible),
  })).filter(section => section.actions.length)
}

export { MENU_GROUPS }
