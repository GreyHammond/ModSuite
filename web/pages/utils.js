// ============================================================
//  ModSuite v2.0 -- Page Utilities
// ============================================================

/**
 * Returns HTML string for a full-width loading state.
 */
export function loading(msg = 'Loading…') {
  return `
    <div class="page-loading">
      <div class="spinner"></div>
      <span>${msg}</span>
    </div>`;
}

/**
 * Returns HTML string for an error state with optional retry.
 * retryFn: () => void  -- called when Retry is clicked
 */
export function errorState(msg, retryFn) {
  const id = `retry-${Math.random().toString(36).slice(2)}`;
  // Attach listener after rendering
  setTimeout(() => {
    const btn = document.getElementById(id);
    if (btn && retryFn) btn.addEventListener('click', retryFn);
  }, 0);
  return `
    <div class="page-error">
      <span class="error-icon">⚠️</span>
      <p>${msg}</p>
      ${retryFn ? `<button class="btn btn-ghost btn-sm" id="${id}">Retry</button>` : ''}
    </div>`;
}

/**
 * Returns HTML string for an empty state.
 */
export function emptyState(icon, msg) {
  return `
    <div class="page-empty">
      <span class="empty-icon">${icon}</span>
      <span>${msg}</span>
    </div>`;
}

/**
 * Human-readable relative time (e.g. "3 minutes ago").
 */
export function timeAgo(dateStr) {
  if (!dateStr) return '--';
  const d    = new Date(dateStr);
  const diff = Date.now() - d.getTime();
  if (isNaN(diff)) return dateStr;

  const s  = Math.floor(diff / 1000);
  const m  = Math.floor(s / 60);
  const h  = Math.floor(m / 60);
  const dy = Math.floor(h / 24);

  if (s < 60)  return 'just now';
  if (m < 60)  return `${m}m ago`;
  if (h < 24)  return `${h}h ago`;
  if (dy < 7)  return `${dy}d ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/**
 * Escape HTML to prevent XSS in user-supplied strings.
 */
export function escHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Simple paginator helper. Returns { page, pageCount, slice(arr) }.
 */
export function paginator(arr, perPage = 50) {
  let page = 1;
  const pageCount = () => Math.max(1, Math.ceil(arr.length / perPage));
  const slice     = () => arr.slice((page - 1) * perPage, page * perPage);

  return {
    get page()      { return page; },
    get pageCount() { return pageCount(); },
    next() { if (page < pageCount()) page++; },
    prev() { if (page > 1) page--; },
    reset() { page = 1; },
    slice,
  };
}
