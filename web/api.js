// ─── API Client ───────────────────────────────────────────────────────────────
// Single source of truth for the API base URL.
// Agent 4: import { API_BASE, apiFetch } from '../api.js'

export const API_BASE = 'http://localhost:8000';

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
