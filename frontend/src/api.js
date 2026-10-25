/**
 * api.js – centralised API client for WindSight UK
 *
 * The backend URL is configured via VITE_API_BASE_URL environment variable.
 * Default: http://localhost:8000 for local development.
 *
 * Never put secrets in Vite env vars; these are embedded in the JS bundle.
 */

const BASE = import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '')

async function apiFetch(path) {
  if (!BASE) throw new Error('Backend URL is not configured for this deployment.')
  const url = `${BASE}${path}`
  // The first backend request may fetch a full month of Elexon history.
  const res = await fetch(url, { signal: AbortSignal.timeout(120_000) })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${res.status}: ${text}`)
  }
  return res.json()
}

export const api = {
  health: () => apiFetch('/api/health'),
  overview: () => apiFetch('/api/overview'),

  forecastDay: (date) =>
    apiFetch(`/api/forecast-accuracy?date=${date}`),

  forecastSummary: (from, to) =>
    apiFetch(`/api/forecast-accuracy/summary?from=${from}&to=${to}`),

  leadTimes: (from, to) =>
    apiFetch(`/api/forecast-accuracy/lead-times?from=${from}&to=${to}`),
}
