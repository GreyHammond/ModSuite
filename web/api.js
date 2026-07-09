// ─── API Client ───────────────────────────────────────────────────────────────
// Single source of truth for the API base URL.
// Agent 4: import { API_BASE, apiFetch } from '../api.js'
//
// Empty base means all API calls are relative to the current origin.
// This makes the dashboard work whether it's served from 127.0.0.1, localhost,
// an SSH tunnel, or a reverse proxy -- the browser resolves paths against
// whatever origin loaded the page.

export const API_BASE = '';

export async function apiFetch(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}${text ? ': ' + text : ''}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ─── Convenience wrappers (used by Agent 4 pages) ─────────────────────────────
export const get  = (path)       => apiFetch(path);
export const post = (path, body) => apiFetch(path, { method: 'POST',   body: JSON.stringify(body) });
export const put  = (path, body) => apiFetch(path, { method: 'PUT',    body: JSON.stringify(body) });
export const del  = (path)       => apiFetch(path, { method: 'DELETE' });
