export function safeNumber(value, fallback = '-') {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

export function safePrice(value, decimals = 2) {
  if (value === null || value === undefined || value === '') return '-'
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(decimals) : '-'
}

export function safeText(value, fallback = '-') {
  if (value === null || value === undefined || value === '') return fallback
  return String(value)
}

export function safeArray(value) {
  return Array.isArray(value) ? value : []
}

export function safeObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

export function safeDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString()
}
