/**
 * Resolves the correct API base URL.
 *
 * Dev:            VITE_API_URL not set → returns '' → Vite proxy forwards /api to localhost:8000
 * Prod (web):     VITE_API_URL=https://your-api.onrender.com → used as prefix
 * Native (mobile):VITE_API_URL=https://your-api.onrender.com → used as prefix
 *
 * Usage:  `${apiBase()}/api/v1/research/run`
 */
export function apiBase(): string {
  const url = import.meta.env.VITE_API_URL
  return url ? url.replace(/\/$/, '') : ''
}
