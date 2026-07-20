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
    description: 'Show the TradingView chart for the selected market.',
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
    id: 'data.liveOnlyMode',
    label: 'Live Only Mode',
    group: 'Data',
    description: 'Use live price only and disable full real analysis.',
    enabled: state => !state.actionsDisabled,
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
    id: 'system.backendHealth',
    label: 'Refresh Services',
    group: 'System',
    description: 'Refresh market services and current data status.',
  },
  {
    id: 'system.clearLocalStorage',
    label: 'Reset App Data',
    group: 'System',
    description: 'Reset saved preferences and reload the workspace.',
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
